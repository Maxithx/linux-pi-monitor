from __future__ import annotations

from typing import Dict

from .metrics_cpu import parse_cpu_info, get_cpu_usage, get_cpu_source
from .metrics_mem import parse_mem_free
from .metrics_disk import parse_disk_df, get_disk_hardware_info
from .metrics_net import parse_net_speed
from .sensors import get_cpu_temp
from .ssh_client import ssh_run
from .glances_client import fetch_glances_metrics


def _get_uptime() -> str:
    try:
        total_seconds = int(float((ssh_run("cat /proc/uptime") or "0").split()[0]))
        h = total_seconds // 3600
        m = (total_seconds % 3600) // 60
        s = total_seconds % 60
        return f"{h}t {m}m {s}s"
    except Exception:
        return "?"


def collect_metrics() -> Dict:
    """Assemble the metrics JSON, preferring Glances data when available."""
    glances, glances_error = fetch_glances_metrics()
    glances = glances or {}
    telemetry = "glances" if glances else "native"

    cpu_name, cpu_cores, cpu_freq = parse_cpu_info()
    cpu_from_glances = glances.get("cpu")
    if cpu_from_glances is not None:
        cpu_usage = float(cpu_from_glances)
        cpu_source = "glances"
    else:
        cpu_usage = get_cpu_usage()
        cpu_source = get_cpu_source()

    ram_usage, ram_total, ram_free = parse_mem_free()
    if glances.get("ram") is not None:
        try:
            ram_usage = float(glances["ram"])
        except Exception:
            pass
    if glances.get("ram_total_mb"):
        ram_total = int(glances["ram_total_mb"])
    if glances.get("ram_free_mb"):
        ram_free = int(glances["ram_free_mb"])

    disk_usage, disk_total, disk_used, disk_free = parse_disk_df()
    if glances.get("disk") is not None:
        try:
            disk_usage = float(glances["disk"])
        except Exception:
            pass
    disk_total = glances.get("disk_total", disk_total)
    disk_used = glances.get("disk_used", disk_used)
    disk_free = glances.get("disk_free", disk_free)

    net_total, net_rx, net_tx, net_iface = parse_net_speed()
    if glances.get("network") is not None:
        try:
            net_total = float(glances["network"])
            net_rx = float(glances.get("net_rx", net_rx))
            net_tx = float(glances.get("net_tx", net_tx))
        except Exception:
            pass
        net_iface = glances.get("net_iface", net_iface)

    uptime = _get_uptime()
    cpu_temp = get_cpu_temp()
    disk_model, disk_device, disk_temp = get_disk_hardware_info()

    return {
        "cpu": cpu_usage,
        "cpu_source": cpu_source,
        "cpu_name": cpu_name,
        "cpu_cores": cpu_cores,
        "cpu_freq": cpu_freq,
        "cpu_temp": cpu_temp,
        "ram": ram_usage,
        "ram_total": ram_total,
        "ram_free": ram_free,
        "disk": disk_usage,
        "disk_total": disk_total,
        "disk_used": disk_used,
        "disk_free": disk_free,
        "disk_model": disk_model,
        "disk_device": disk_device,
        "disk_temp": disk_temp,
        "network": net_total,
        "net_rx": net_rx,
        "net_tx": net_tx,
        "net_iface": net_iface,
        "uptime": uptime,
        "telemetry_source": telemetry,
        "telemetry_hint": glances_error if telemetry != "glances" else "",
    }
