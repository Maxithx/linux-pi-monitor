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


def _load_active_profile() -> dict:
    """Load active SSH profile from PROFILES_PATH JSON (disk)."""
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
                    "password": p.get("password") or "",
                }
    except Exception:
        pass
    return {}

