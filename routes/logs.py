# === Logs routes ===
# Denne fil håndterer logvisning og åbning af logfil i Windows

import os
from flask import Blueprint, render_template, jsonify, current_app

logs_bp = Blueprint("logs", __name__)

@logs_bp.route("/logs", endpoint="logs")
def logs():
    log_file_path = current_app.config["LOG_FILE_PATH"]
    try:
        with open(log_file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        recent_lines = lines[-100:]
    except Exception as e:
        recent_lines = [f"Fejl ved indlæsning af log: {e}"]

    return render_template("logs.html", logs=recent_lines)

@logs_bp.route("/open-log", methods=["POST"])
def open_log():
    log_file_path = current_app.config["LOG_FILE_PATH"]
    try:
        os.startfile(log_file_path)  # Kun på Windows
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
