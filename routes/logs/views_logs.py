# === Logs routes ===
# This file handles log viewing and opening the log file in Windows

import os
from flask import render_template, jsonify, current_app
from . import logs_bp

# === ROUTE: Display the latest lines from the log file in the UI ===
@logs_bp.route("/logs", endpoint="logs")
def logs():
    log_file_path = current_app.config["LOG_FILE_PATH"]
    try:
        with open(log_file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        recent_lines = lines[-100:]  # Show only the last 100 lines
    except Exception as e:
        recent_lines = [f"Error loading log file: {e}"]

    return render_template("logs.html", logs=recent_lines)

# === ROUTE: Open the log file in Windows default text viewer (e.g. Notepad) ===
@logs_bp.route("/open-log", methods=["POST"])
def open_log():
    log_file_path = current_app.config["LOG_FILE_PATH"]
    try:
        os.startfile(log_file_path)  # Windows only
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
