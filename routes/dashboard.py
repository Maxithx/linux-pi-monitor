import json
import os
import time
from flask import Blueprint, render_template, jsonify, current_app, redirect
from utils import (
    parse_net_speed, parse_cpu_info, parse_cpu_usage,
    parse_mem, parse_disk, get_uptime, get_cpu_temp,
    ssh_run
)

dashboard_bp = Blueprint("dashboard_bp", __name__)

# Cache for metrics
latest_metrics = {}
first_cached_metrics = {}
first_sent = False

# === DASHBOARD SIDE ===
@dashboard_bp.route("/dashboard", endpoint="dashboard")
def dashboard():
    settings_path = current_app.config["SETTINGS_PATH"]
    if not os.path.exists(settings_path):
        return redirect("/settings")

    with open(settings_path, "r") as f:
        settings = json.load(f)

    if not settings.get("pi_host") or not settings.get("pi_user"):
        return redirect("/settings")

    try:
        # Brug direkte sti til Glances installeret i ~/.local/bin
        result = ssh_run("test -f ~/.local/bin/glances && echo 'ok'")
        if not result.strip() == "ok":
            return redirect("/settings")
    except Exception:
        return redirect("/settings")

    return render_template("dashboard.html")

# === API: SYSTEMMETRICS ===
@dashboard_bp.route("/metrics")
def metrics():
    global latest_metrics, first_cached_metrics, first_sent

    if not first_sent and first_cached_metrics:
        first_sent = True
        current_app.logger.info("Bruger cached metrics til første kald.")
        return jsonify(first_cached_metrics)

    try:
        cpu_raw = ssh_run("top -bn1 | grep 'Cpu(s)'")
        mem_raw = ssh_run("free -m")
        disk_raw = ssh_run("df -h /")
        net_raw = ssh_run("cat /proc/net/dev")

        cpu_name, cpu_cores, cpu_freq = parse_cpu_info()
        cpu_usage = parse_cpu_usage(cpu_raw)
        ram_usage, ram_total, ram_free = parse_mem(mem_raw)
        disk_usage, disk_total, disk_used, disk_free = parse_disk(disk_raw)
        net_total, net_rx, net_tx, net_iface = parse_net_speed(net_raw)
        uptime = get_uptime()
        cpu_temp = get_cpu_temp()

        metrics = {
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
            "network": net_total,
            "net_rx": net_rx,
            "net_tx": net_tx,
            "net_iface": net_iface,
            "uptime": uptime
        }

        latest_metrics = metrics
        first_cached_metrics = metrics

        return jsonify(metrics)

    except Exception as e:
        current_app.logger.warning(f"Fejl i metrics: {e}")
        return jsonify({})
