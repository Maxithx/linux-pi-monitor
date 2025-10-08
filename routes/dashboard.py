# === IMPORTS ===
import json
import os
from flask import Blueprint, render_template, jsonify, current_app, redirect
from utils import (
    parse_net_speed, parse_cpu_info, parse_cpu_usage,
    parse_mem, parse_disk, get_uptime, get_cpu_temp,
    ssh_run, get_disk_hardware_info
)

# === FLASK BLUEPRINT ===
dashboard_bp = Blueprint("dashboard_bp", __name__)

# === CACHING FOR METRICS ===
latest_metrics = {}
first_cached_metrics = {}
first_sent = False


def _load_active_profile():
    """
    Load active profile directly from profiles.json (PROFILES_PATH).
    Returns a dict with: pi_host, pi_user, auth_method, ssh_key_path, password
    or {} if not found.
    """
    try:
        prof_path = current_app.config.get("PROFILES_PATH")
        if not prof_path or not os.path.exists(prof_path):
            return {}
        with open(prof_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        active_id = data.get("active_profile_id")
        if not active_id:
            return {}
        for p in data.get("profiles", []):
            if p.get("id") == active_id:
                return {
                    "pi_host": (p.get("pi_host") or "").strip(),
                    "pi_user": (p.get("pi_user") or "").strip(),
                    "auth_method": (p.get("auth_method") or "key").strip(),
                    "ssh_key_path": (p.get("ssh_key_path") or "").strip(),
                    "password": p.get("password") or ""
                }
    except Exception:
        pass
    return {}


def _sync_active_into_legacy_cfg(active):
    """
    Keep utils/ssh_run (legacy) reading its target host from app.config["SSH_SETTINGS"].
    Called on each /metrics request to avoid stale cache.
    """
    if not isinstance(active, dict) or not active:
        current_app.config["SSH_SETTINGS"] = {}
        return
    current_app.config["SSH_SETTINGS"] = {
        "pi_host": active.get("pi_host", ""),
        "pi_user": active.get("pi_user", ""),
        "auth_method": active.get("auth_method", "key"),
        "ssh_key_path": active.get("ssh_key_path", ""),
        "password": active.get("password", "")
    }


# === ROUTE: Dashboard page (main UI) ===
@dashboard_bp.route("/dashboard", endpoint="dashboard")
def dashboard():
    """
    Open dashboard. Validate the active profile has needed fields.
    """
    active = _load_active_profile()
    if not active.get("pi_host") or not active.get("pi_user"):
        return redirect("/settings")
    if active.get("auth_method", "key") == "key" and not active.get("ssh_key_path"):
        return redirect("/settings")
    if active.get("auth_method", "key") == "password" and not active.get("password"):
        return redirect("/settings")

    return render_template("dashboard.html", settings=active)


# === ROUTE: API endpoint for real-time system metrics ===
@dashboard_bp.route("/metrics")
def metrics():
    """
    Fetch live metrics via SSH against the ACTIVE profile.
    Soft-fail: returns empty object on error.
    First call can serve cached values for faster first paint.
    """
    global latest_metrics, first_cached_metrics, first_sent

    if not first_sent and first_cached_metrics:
        first_sent = True
        current_app.logger.info("Using cached metrics for first call.")
        return jsonify(first_cached_metrics)

    try:
        # 1) Sync active profile
        active = _load_active_profile()
        _sync_active_into_legacy_cfg(active)

        # 2) Command outputs
        cpu_raw  = ssh_run("top -bn1 | grep 'Cpu(s)'")
        mem_raw  = ssh_run("free -m")
        disk_raw = ssh_run("df -h /")
        net_raw  = ssh_run("cat /proc/net/dev")

        # 3) Parse core metrics
        cpu_name, cpu_cores, cpu_freq = parse_cpu_info()
        cpu_usage = parse_cpu_usage(cpu_raw or "")
        ram_usage, ram_total, ram_free = parse_mem(mem_raw or "")
        disk_usage, disk_total, disk_used, disk_free = parse_disk(disk_raw or "")
        net_total, net_rx, net_tx, net_iface = parse_net_speed(net_raw or "")
        uptime   = get_uptime()
        cpu_temp = get_cpu_temp()
        disk_model, disk_device, disk_temp = get_disk_hardware_info()

        # 4) Payload
        payload = {
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
            "uptime": uptime
        }

        latest_metrics = payload
        first_cached_metrics = payload
        return jsonify(payload)

    except Exception as e:
        current_app.logger.warning(f"Error in metrics: {e}")
        return jsonify({})


# === ROUTE: OS name (for connection line) ===
@dashboard_bp.route("/system/os")
def system_os():
    """
    Return OS name of the active target, e.g. 'Linux Mint 21.3' or 'Raspberry Pi OS'.
    Primary source: /etc/os-release -> PRETTY_NAME
    Fallback: 'uname -sr'
    """
    try:
        # Keep SSH settings in sync
        active = _load_active_profile()
        _sync_active_into_legacy_cfg(active)

        # Read /etc/os-release if available
        osrel = ssh_run("cat /etc/os-release 2>/dev/null || true") or ""
        os_name = ""

        if osrel:
            for line in osrel.splitlines():
                if line.startswith("PRETTY_NAME="):
                    # Value can be quoted; strip surrounding quotes if present
                    val = line.split("=", 1)[1].strip()
                    if len(val) >= 2 and ((val[0] == val[-1] == '"') or (val[0] == val[-1] == "'")):
                        val = val[1:-1]
                    os_name = val.strip()
                    break

        # Fallback if PRETTY_NAME is not present
        if not os_name:
            os_name = (ssh_run("uname -sr") or "Linux").strip()

        return jsonify({"os_name": os_name})

    except Exception as e:
        current_app.logger.warning(f"Error in system_os: {e}")
        return jsonify({"os_name": ""})
