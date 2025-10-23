from __future__ import annotations

from flask import Blueprint, render_template, redirect, jsonify

from .profiles import get_active_profile
from .collector import collect_metrics
import utils as _utils  # only for first_cached_metrics one-shot


dashboard_bp = Blueprint("dashboard_bp", __name__)


@dashboard_bp.route("/dashboard", endpoint="dashboard")
def dashboard():
    s = get_active_profile()
    if not s:
        return redirect("/settings")
    host = (s.get("pi_host") or "").strip()
    user = (s.get("pi_user") or "").strip()
    auth = (s.get("auth_method") or "key").strip()
    keyp = (s.get("ssh_key_path") or "").strip()
    pw = s.get("password") or ""
    if not host or not user:
        return redirect("/settings")
    if auth == "key" and not keyp:
        return redirect("/settings")
    if auth == "password" and not pw:
        return redirect("/settings")
    return render_template("dashboard.html")


@dashboard_bp.route("/metrics")
def metrics():
    # Serve the very first cached sample once, then always compute fresh.
    try:
        if getattr(_utils, "first_cached_metrics", {}):
            data = dict(_utils.first_cached_metrics)
            try:
                _utils.first_cached_metrics = {}
            except Exception:
                pass
            # Enrich and return early for the one-shot
            try:
                from .metrics_cpu import get_cpu_freq_info
                f = get_cpu_freq_info() or {}
                data["cpu_freq_current_mhz"] = f.get("current_mhz") or 0
                data["cpu_freq_max_mhz"] = f.get("max_mhz") or 0
                data["cpu_per_core_mhz"] = f.get("per_core") or []
            except Exception:
                pass
            return jsonify(data)
    except Exception:
        pass

    # Always compute fresh metrics for ongoing requests
    data = collect_metrics()

    # Enrich with frequency details when available
    try:
        from .metrics_cpu import get_cpu_freq_info
        f = get_cpu_freq_info() or {}
        data["cpu_freq_current_mhz"] = f.get("current_mhz") or 0
        data["cpu_freq_max_mhz"] = f.get("max_mhz") or 0
        data["cpu_per_core_mhz"] = f.get("per_core") or []
    except Exception:
        pass

    return jsonify(data)
