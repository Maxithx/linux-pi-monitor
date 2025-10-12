# routes/settings.py
import os
import json
import socket
import paramiko
from flask import render_template, request, jsonify, current_app

from routes.common.ssh_utils import ssh_connect, ssh_exec
from . import settings_bp

# --- Legacy settings helpers (uændret) ---
def _legacy_settings_path() -> str:
    return current_app.config.get("SETTINGS_PATH")

def _load_legacy_settings() -> dict:
    path = _legacy_settings_path()
    if not path or not os.path.exists(path):
        return {"pi_host": "", "pi_user": "", "auth_method": "key",
                "ssh_key_path": "", "password": ""}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"pi_host": "", "pi_user": "", "auth_method": "key",
                "ssh_key_path": "", "password": ""}

def _get_active_ssh_settings() -> dict:
    cfg = (current_app.config.get("SSH_SETTINGS") or {}).copy()
    if cfg.get("pi_host") and cfg.get("pi_user"):
        return cfg
    return _load_legacy_settings()

def _is_configured(s: dict) -> bool:
    host = (s.get("pi_host") or "").strip()
    user = (s.get("pi_user") or "").strip()
    auth = (s.get("auth_method") or "key").strip()
    keyp = (s.get("ssh_key_path") or "").strip()
    pw   = s.get("password") or ""
    if not host or not user:
        return False
    return bool(keyp) if auth == "key" else bool(pw)

def _quick_port_check(host: str, port: int = 22, timeout: float = 0.7) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False

def _paramiko_ping(s: dict, timeout: float = 2.0) -> bool:
    host = s.get("pi_host"); user = s.get("pi_user")
    auth = (s.get("auth_method") or "key").strip()
    keyp = s.get("ssh_key_path"); pw = s.get("password") or ""

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    if auth == "key":
        key_path = os.path.expanduser(keyp or "")
        key_path = os.path.expandvars(key_path)
        pkey = paramiko.RSAKey.from_private_key_file(key_path)
        ssh.connect(host, username=user, pkey=pkey, timeout=timeout)
    else:
        ssh.connect(host, username=user, password=pw, timeout=timeout)
    ssh.close()
    return True

# --- Settings page + status ---
@settings_bp.route("/settings", endpoint="settings")
def settings():
    active = _get_active_ssh_settings()
    connection_status = "connected" if test_ssh_connection() else "disconnected"
    return render_template("settings.html", settings=active, connection_status=connection_status)

@settings_bp.route("/save-settings", methods=["POST"])
def save_settings():
    settings_path = _legacy_settings_path()
    try:
        new_settings = {
            "pi_host": request.form.get("pi_host","").strip(),
            "pi_user": request.form.get("pi_user","").strip(),
            "auth_method": request.form.get("auth_method","key"),
            "ssh_key_path": request.form.get("ssh_key_path","").strip(),
            "password": request.form.get("password","").strip(),
        }
        os.makedirs(os.path.dirname(settings_path), exist_ok=True)
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(new_settings, f, indent=4)

        # nulstil caches
        current_app.chart_data_cache = {"cpu": [], "ram": [], "disk": [], "network": []}
        current_app.latest_metrics = {}
        current_app.first_cached_metrics = {}

        try:
            if not _is_configured(new_settings):
                return jsonify({"success": False, "message": "Missing required fields."})
            if not _quick_port_check(new_settings["pi_host"], 22, timeout=0.7):
                return jsonify({"success": False, "message": "Host unreachable on port 22."})
            _paramiko_ping(new_settings, timeout=2.0)
            current_app.logger.info("Connection verified")
            return jsonify({"success": True, "message": "✔️ Settings saved. Connection established."})
        except Exception as ssh_error:
            return jsonify({"success": False, "message": f"Connection failed: {ssh_error}"})
    except Exception as e:
        return jsonify({"success": False, "message": f"Error saving settings: {e}"})

def test_ssh_connection() -> bool:
    try:
        s = _get_active_ssh_settings()
        if not _is_configured(s): return False
        if not _quick_port_check(s["pi_host"], 22, timeout=0.7): return False
        return _paramiko_ping(s, timeout=2.0)
    except Exception:
        return False

def _status_payload():
    s = _get_active_ssh_settings()
    if not _is_configured(s):
        return {"ok": False, "connected": False, "reason": "not_configured"}
    if not _quick_port_check(s["pi_host"], 22, timeout=0.7):
        return {"ok": False, "connected": False, "reason": "host_unreachable"}
    try:
        _paramiko_ping(s, timeout=2.0)
        return {"ok": True, "connected": True}
    except Exception as e:
        return {"ok": False, "connected": False, "reason": str(e)}

@settings_bp.get("/check-ssh-status")
def check_ssh_status():
    return jsonify(_status_payload())

@settings_bp.get("/check-ssh")
def check_ssh():
    return jsonify(_status_payload())

# --- Glances iframe (uændret) ---
def _glances_url_from_settings(s: dict) -> str:
    host = (s.get("pi_host") or "").strip()
    return f"http://{host}:61208/" if host else ""

@settings_bp.route("/glances", endpoint="glances")
def glances_page():
    s = (current_app.config.get("SSH_SETTINGS") or {}).copy()
    host = (s.get("pi_host") or "").strip()
    if not host:
        try:
            path = current_app.config.get("SETTINGS_PATH")
            if path and os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    legacy = json.load(f)
                host = (legacy.get("pi_host") or "").strip()
        except Exception:
            host = ""
    glances_url = f"http://{host}:61208/" if host else ""
    return render_template("glances.html", glances_url=glances_url)

# --- Reboot (uændret) ---
@settings_bp.route("/reboot-linux", methods=["POST"])
def reboot_linux():
    try:
        s = _get_active_ssh_settings()
        if not _is_configured(s):
            return jsonify({"success": False, "error": "SSH not configured"})

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        if (s.get("auth_method") or "key") == "key":
            key_path = os.path.expanduser(s.get("ssh_key_path") or "")
            key_path = os.path.expandvars(key_path)
            pkey = paramiko.RSAKey.from_private_key_file(key_path)
            ssh.connect(s["pi_host"], username=s["pi_user"], pkey=pkey, timeout=4)
        else:
            ssh.connect(s["pi_host"], username=s["pi_user"], password=s.get("password",""), timeout=4)

        ssh.exec_command("sudo reboot")
        ssh.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

