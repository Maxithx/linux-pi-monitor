from flask import Blueprint, request, jsonify
import os

# === Initialisering ===
session_bp = Blueprint("session", __name__)
appdata_dir = os.path.join(os.getenv("APPDATA"), "raspberry_pi_monitor")
os.makedirs(appdata_dir, exist_ok=True)
session_file = os.path.join(appdata_dir, "terminal_session.txt")

# === Gem terminal-output ===
@session_bp.route("/save-session", methods=["POST"])
def save_session():
    data = request.json.get("data", "")
    if data:
        with open(session_file, "a", encoding="utf-8") as f:
            f.write(data)
        return jsonify({"status": "saved"})
    return jsonify({"status": "no data"}), 400

# === Indlæs tidligere terminal-output ===
@session_bp.route("/load-session", methods=["GET"])
def load_session():
    if os.path.exists(session_file):
        with open(session_file, "r", encoding="utf-8") as f:
            return f.read()
    return "", 200

# === Ryd terminal-session ===
@session_bp.route("/clear-session", methods=["POST"])
def clear_session():
    if os.path.exists(session_file):
        os.remove(session_file)
    return jsonify({"status": "cleared"})
