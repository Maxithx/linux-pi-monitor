# === IMPORTS ===
import json
import os
from flask import Blueprint, render_template, jsonify, current_app, redirect

# Utils: all parsing and SSH helpers live here
from utils import (
    parse_net_speed, parse_cpu_info, parse_cpu_usage,
    parse_mem, parse_disk, get_uptime, get_cpu_temp,
    ssh_run, get_disk_hardware_info
)

# Some repos place this helper in utils as well. Import if present.
try:
    # Expected to return: {
    #   "current_mhz": float|int|None,
    #   "max_mhz": float|int|None,
    #   "per_core_mhz": list[float]|None
    # }
    from utils import get_cpu_freq_info  # type: ignore
except Exception:  # pragma: no cover
    get_cpu_freq_info = None  # fallback handled below

# === FLASK BLUEPRINT ===
dashboard_bp = Blueprint("dashboard_bp", __name__)

# === OPTIONAL CACHING FOR METRICS (simple in-memory) ===
latest_metrics = {}
first_cached_metrics = {}

# ---------- Internal helpers ----------

def _get_active_profile() -> dict:
    """Return the currently active profile from app.config, if any."""
    profiles = current_app.config.get("PROFILES") or {}
    active = profiles.get("active") if isinstance(profiles, dict) else None
    return active or {}

def _sync_active_into_legacy_cfg(active: dict) -> None:
    """
    Keep legacy utils.ssh_run reading its target host from app.config["SSH_SETTINGS"].
    Called on each request that may hit SSH to avoid stale cache.
    """
    if not isinstance(active, dict) or not active:
        current_app.config["SSH_SETTINGS"] = {}
        return
    current_app.config["SSH_SETTINGS"] = {
        "pi_host": active.get("pi_host", ""),
        "pi_user": active.get("pi_user", ""),
        "auth_method": active.get("auth_method", "key"),
        "ssh_key_path": active.get("ssh_key_path", ""),
        "ssh_port": int(active.get("ssh_port", 22) or 22),
        "password": active.get("password", ""),
        "timeout": int(active.get("timeout", 10) or 10),
    }

def _safe_get_cpu_freq_info() -> dict:
    """Return CPU frequency info using utils.get_cpu_freq_info if available."""
    if callable(get_cpu_freq_info):
        try:
            data = get_cpu_freq_info()  # type: ignore[misc, call-arg]
            if isinstance(data, dict):
                return {
                    "current_mhz": data.get("current_mhz"),
                    "max_mhz": data.get("max_mhz"),
                    "per_core_mhz": data.get("per_core_mhz"),
                }
        except Exception as e:
            current_app.logger.warning(f"get_cpu_freq_info failed: {e}")
    # Fallback: None values to keep JSON shape stable
    return {"current_mhz": None, "max_mhz": None, "per_core_mhz": None}

# ---------- Routes ----------

@dashboard_bp.route("/")
def _root_redirect():
    # Keep root of this blueprint clean; redirect to the dashboard page.
    return redirect("/dashboard")


@dashboard_bp.route("/dashboard", endpoint="dashboard")
def dashboard_page():
    """Render the main dashboard page."""
    return render_template("dashboard.html")


@dashboard_bp.route("/metrics")
def metrics():
    """Aggregate metrics for the UI as JSON."""
    try:
        active = _get_active_profile()
        _sync_active_into_legacy_cfg(active)

        # Basic system info
        cpu_name, cpu_cores, cpu_freq_label = parse_cpu_info()
        cpu_usage = parse_cpu_usage()
        mem_info = parse_mem()
        disk_info = parse_disk()
        uptime = get_uptime()
        cpu_temp = get_cpu_temp()
        net = parse_net_speed()
        disk_hw = get_disk_hardware_info()

        # Frequency details (per-core etc.)
        freq_info = _safe_get_cpu_freq_info()

        payload = {
            "profile": {
                "name": active.get("name") or active.get("pi_host", ""),
                "host": active.get("pi_host", ""),
                "user": active.get("pi_user", ""),
            },
            "cpu": {
                "name": cpu_name,
                "cores": cpu_cores,
                "usage": cpu_usage,
                "temp_c": cpu_temp,
                "freq_label": cpu_freq_label,
                "freq_current_mhz": freq_info.get("current_mhz"),
                "freq_max_mhz": freq_info.get("max_mhz"),
                "per_core_mhz": freq_info.get("per_core_mhz"),
            },
            "memory": mem_info,
            "disk": {
                "partitions": disk_info,
                "hardware": disk_hw,
            },
            "network": net,
            "uptime": uptime,
        }

        # Update simple caches (optional – helps initial paint)
        global latest_metrics, first_cached_metrics
        latest_metrics = payload
        if not first_cached_metrics:
            first_cached_metrics = payload

        return jsonify(payload)

    except Exception as e:
        current_app.logger.exception(f"/metrics failed: {e}")
        # Return best effort cached data if available
        if latest_metrics:
            return jsonify({"cached": True, **latest_metrics})
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route("/system/os")
def system_os():
    """Detect OS PRETTY_NAME via /etc/os-release on the target host."""
    try:
        active = _get_active_profile()
        _sync_active_into_legacy_cfg(active)

        os_name = ""
        # Prefer /etc/os-release parsing
        os_release = ssh_run("cat /etc/os-release") or ""
        for line in os_release.splitlines():
            if line.startswith("PRETTY_NAME="):
                val = line.split("=", 1)[1].strip()
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                os_name = val.strip()
                break
        if not os_name:
            # Fallback
            os_name = (ssh_run("uname -sr") or "Linux").strip()

        return jsonify({"os_name": os_name})
    except Exception as e:
        current_app.logger.warning(f"Error in system_os: {e}")
        return jsonify({"os_name": ""})

