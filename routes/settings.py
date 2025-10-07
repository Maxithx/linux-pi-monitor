# routes/settings.py
import os
import json
import socket
import paramiko
from flask import Blueprint, render_template, request, jsonify, current_app

# === Blueprint for Settings routes ===
settings_bp = Blueprint("settings", __name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _legacy_settings_path() -> str:
    return current_app.config.get("SETTINGS_PATH")

def _load_legacy_settings() -> dict:
    """Læs legacy settings.json (single target). Bruges som fallback."""
    path = _legacy_settings_path()
    if not path or not os.path.exists(path):
        return {
            "pi_host": "",
            "pi_user": "",
            "auth_method": "key",
            "ssh_key_path": "",
            "password": ""
        }
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "pi_host": "",
            "pi_user": "",
            "auth_method": "key",
            "ssh_key_path": "",
            "password": ""
        }

def _get_active_ssh_settings() -> dict:
    """
    Returnér den aktive SSH-konfiguration.
    1) Primært fra app.config["SSH_SETTINGS"] (sat ud fra aktiv profil)
    2) Fallback: legacy settings.json
    """
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
    if auth == "key":
        return bool(keyp)
    return bool(pw)

def _quick_port_check(host: str, port: int = 22, timeout: float = 0.7) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False

def _paramiko_ping(s: dict, timeout: float = 2.0) -> bool:
    """Kort Paramiko-forbindelse for at markere 'connected'."""
    host = s.get("pi_host")
    user = s.get("pi_user")
    auth = (s.get("auth_method") or "key").strip()
    keyp = s.get("ssh_key_path")
    pw   = s.get("password") or ""

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    if auth == "key":
        pkey = paramiko.RSAKey.from_private_key_file(keyp)
        ssh.connect(host, username=user, pkey=pkey, timeout=timeout)
    else:
        ssh.connect(host, username=user, password=pw, timeout=timeout)

    ssh.close()
    return True

# ---------------------------------------------------------------------------
# Clear settings (legacy) – bruges hvis man vil nulstille gamle settings.json
# ---------------------------------------------------------------------------
@settings_bp.route("/clear-settings", methods=["POST"])
def clear_settings():
    try:
        default_settings = {
            "pi_host": "",
            "pi_user": "",
            "auth_method": "key",
            "ssh_key_path": "",
            "password": ""
        }
        path = _legacy_settings_path()
        if path:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default_settings, f, indent=4)

        # Nulstil evt. caches på app-objektet (hvis de bruges andre steder)
        current_app.chart_data_cache = {"cpu": [], "ram": [], "disk": [], "network": []}
        current_app.latest_metrics = {}
        current_app.first_cached_metrics = {}

        current_app.logger.info("Legacy settings.json reset.")
        return jsonify({"success": True})
    except Exception as e:
        current_app.logger.error(f"Error resetting settings: {e}")
        return jsonify({"success": False, "message": "Could not reset settings."})

# ---------------------------------------------------------------------------
# Test SSH (hurtig og non-blocking hvis ikke konfigureret)
# ---------------------------------------------------------------------------
def test_ssh_connection() -> bool:
    try:
        s = _get_active_ssh_settings()
        if not _is_configured(s):
            return False  # Ikke sat op → ikke connected

        # lynhurtig porttest før Paramiko
        if not _quick_port_check(s["pi_host"], 22, timeout=0.7):
            return False

        # kort paramiko ping
        return _paramiko_ping(s, timeout=2.0)
    except Exception:
        return False

# ---------------------------------------------------------------------------
# Settings side
# ---------------------------------------------------------------------------
@settings_bp.route("/settings", endpoint="settings")
def settings():
    """
    Viser settings-siden. Felterne udfyldes fra aktive SSH settings (profil) eller legacy.
    """
    # Brug aktive settings (profil) for at udfylde formularen
    active = _get_active_ssh_settings()
    connection_status = "connected" if test_ssh_connection() else "disconnected"
    return render_template("settings.html", settings=active, connection_status=connection_status)

# ---------------------------------------------------------------------------
# Legacy "save-settings" (backwards compat). UI bruger nu "Save profile".
# Beholder denne route for ikke at bryde andre dele – men den testes stadig.
# ---------------------------------------------------------------------------
@settings_bp.route("/save-settings", methods=["POST"])
def save_settings():
    settings_path = _legacy_settings_path()
    try:
        new_settings = {
            "pi_host": request.form.get("pi_host", "").strip(),
            "pi_user": request.form.get("pi_user", "").strip(),
            "auth_method": request.form.get("auth_method", "key"),
            "ssh_key_path": request.form.get("ssh_key_path", "").strip(),
            "password": request.form.get("password", "").strip()
        }

        os.makedirs(os.path.dirname(settings_path), exist_ok=True)
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(new_settings, f, indent=4)

        # nulstil caches hvis de findes
        current_app.chart_data_cache = {"cpu": [], "ram": [], "disk": [], "network": []}
        current_app.latest_metrics = {}
        current_app.first_cached_metrics = {}

        # kort verifikation
        try:
            if not _is_configured(new_settings):
                return jsonify({"success": False, "message": "Missing required fields."})

            if not _quick_port_check(new_settings["pi_host"], 22, timeout=0.7):
                return jsonify({"success": False, "message": "Host unreachable on port 22."})

            _paramiko_ping(new_settings, timeout=2.0)
            current_app.logger.info("Connection to target verified via legacy save-settings.")
            return jsonify({"success": True, "message": "✔️ Settings saved. Connection established."})
        except Exception as ssh_error:
            current_app.logger.warning(f"Connection failed: {ssh_error}")
            return jsonify({"success": False, "message": f"Connection failed: {ssh_error}"})

    except Exception as e:
        current_app.logger.error(f"Error in save_settings: {e}")
        return jsonify({"success": False, "message": f"Error saving settings: {e}"})

# ---------------------------------------------------------------------------
# Status endpoints (bruges af JS-indikatorer)
#  - /check-ssh-status : bruges i eksisterende JS
#  - /check-ssh        : simplere alias
# Begge svarer hurtigt 'not_configured' når felter mangler (ingen Paramiko)
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# HTOP view (uændret – bruger kun host til at bygge siden)
# ---------------------------------------------------------------------------
@settings_bp.route("/glances")
def glances():
    s = _get_active_ssh_settings()
    return render_template("glances.html", settings={"pi_host": s.get("pi_host", "")})

# ---------------------------------------------------------------------------
# Reboot – brug aktiv profil/legacy med korte timeouts
# ---------------------------------------------------------------------------
@settings_bp.route("/reboot-linux", methods=["POST"])
def reboot_linux():
    try:
        s = _get_active_ssh_settings()
        if not _is_configured(s):
            return jsonify({"success": False, "error": "SSH not configured"})

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        if (s.get("auth_method") or "key") == "key":
            pkey = paramiko.RSAKey.from_private_key_file(s.get("ssh_key_path"))
            ssh.connect(s["pi_host"], username=s["pi_user"], pkey=pkey, timeout=4)
        else:
            ssh.connect(s["pi_host"], username=s["pi_user"], password=s.get("password",""), timeout=4)

        ssh.exec_command("sudo reboot")
        ssh.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
