from __future__ import annotations

from typing import Dict

from .metrics_cpu import parse_cpu_info, get_cpu_usage
from .metrics_mem import parse_mem_free
from .metrics_disk import parse_disk_df, get_disk_hardware_info
from .metrics_net import parse_net_speed
from .sensors import get_cpu_temp
from .ssh_client import ssh_run


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
    """Assemble the metrics JSON preserving the existing contract exactly."""
    cpu_name, cpu_cores, cpu_freq = parse_cpu_info()
    cpu_usage = get_cpu_usage()

    ram_usage, ram_total, ram_free = parse_mem_free()
    disk_usage, disk_total, disk_used, disk_free = parse_disk_df()
    net_total, net_rx, net_tx, net_iface = parse_net_speed()
    uptime = _get_uptime()
    cpu_temp = get_cpu_temp()
    disk_model, disk_device, disk_temp = get_disk_hardware_info()

    return {
        "cpu": cpu_usage,
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
    }

