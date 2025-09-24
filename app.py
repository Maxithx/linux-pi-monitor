# === app.py ===
# Main entry point for the Linux Pi Monitor web app

import eventlet
eventlet.monkey_patch()

import webview
import webbrowser
from flask import Flask, render_template, jsonify, request, redirect, session
from utils import background_updater
from socketio_instance import socketio
import paramiko
import threading
import os
import logging
import sys
import json
import time
import uuid
import pathlib

# === Import routes and sidebar context injection ===
from routes import register_routes
from routes.sidebar import register_sidebar_context

# === Flask app setup ===
app = Flask(__name__)

# 🔐 Nødvendig for Flask-sessioner (skift til en stærk hemmelighed i prod/ENV)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-change-me-please")
app.config.update(
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,  # sæt True bag HTTPS
)

socketio.init_app(app)

# Importér session blueprint (gem/indlæs/ryd af terminal-output)
from session import session_bp
app.register_blueprint(session_bp)

# Register global sidebar context + alle routes/blueprints
register_sidebar_context(app)
register_routes(app)

# ── App data paths (Windows + Linux/Mac) ───────────────────────────────────────
# Regler:
# 1) Hvis miljøvariablen RPI_MONITOR_DATA er sat, bruges den (portable mode).
# 2) Windows: %APPDATA%\raspberry_pi_monitor
# 3) Linux/Mac: $XDG_CONFIG_HOME/raspberry_pi_monitor eller ~/.config/raspberry_pi_monitor
def _resolve_appdata_dir() -> str:
    env_override = os.getenv("RPI_MONITOR_DATA")
    if env_override:
        return env_override

    if os.name == "nt":
        base = os.getenv("APPDATA") or os.path.expanduser(r"~\AppData\Roaming")
        return os.path.join(base, "raspberry_pi_monitor")

    # POSIX (Linux/Mac)
    xdg = os.getenv("XDG_CONFIG_HOME")
    base = xdg if xdg else os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "raspberry_pi_monitor")

appdata_dir = _resolve_appdata_dir()
os.makedirs(appdata_dir, exist_ok=True)

# Filer (bevar de eksisterende filnavne)
settings_path = os.path.join(appdata_dir, "settings.json")       # legacy single-target
log_file_path = os.path.join(appdata_dir, "server_logs.txt")
profiles_path = os.path.join(appdata_dir, "ssh_profiles.json")   # new multi-profile store

# Eksporter til Flask config
app.config["SETTINGS_PATH"] = settings_path
app.config["LOG_FILE_PATH"] = log_file_path
app.config["PROFILES_PATH"] = profiles_path

# Gør også stien tilgængelig for under-moduler der læser env
os.environ["RPI_MONITOR_PROFILES_PATH"] = app.config["PROFILES_PATH"]

# -------------------------------------------------------------------
# Profiles: storage helpers + migration from legacy settings.json
# -------------------------------------------------------------------
def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def _load_profiles():
    """Return dict: {profiles: [...], active_profile_id: str|None, default_profile_id: str|None}."""
    if os.path.exists(profiles_path):
        with open(profiles_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # No profiles yet → try to migrate from old settings.json
    base = {"profiles": [], "active_profile_id": None, "default_profile_id": None}
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                s = json.load(f)
            pid = str(uuid.uuid4())
            prof = {
                "id": pid,
                "name": "Default",
                "pi_host": s.get("pi_host", ""),
                "pi_user": s.get("pi_user", ""),
                "auth_method": s.get("auth_method", "key"),
                "ssh_key_path": s.get("ssh_key_path", ""),
                "password": s.get("password", "")
            }
            base["profiles"] = [prof]
            base["active_profile_id"] = pid
            base["default_profile_id"] = pid
            _write_json(profiles_path, base)
            return base
        except Exception as e:
            print(f"[app.py] Profiles migration failed: {e}")

    # Brand new file
    _write_json(profiles_path, base)
    return base

def _save_profiles(data):
    _write_json(profiles_path, data)

def _get_active_profile():
    data = _load_profiles()
    pid = data.get("active_profile_id")
    for p in data.get("profiles", []):
        if p["id"] == pid:
            return p
    return None

# Expose profiles to templates (Settings UI gets dropdown ready on first load)
@app.context_processor
def inject_profiles():
    data = _load_profiles()
    return dict(
        profiles=data.get("profiles", []),
        active_profile_id=data.get("active_profile_id"),
        default_profile_id=data.get("default_profile_id"),
    )

# === Logging configuration ===
logging.basicConfig(
    filename=log_file_path,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
handler = logging.FileHandler(log_file_path)
handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(message)s')
handler.setFormatter(formatter)
app.logger.addHandler(handler)

logfile = open(log_file_path, 'a', encoding='utf-8')
sys.stderr = sys.stdout   # Redirect errors to log

# -------------------------------------------------------------------
# Back-compat: populate app.config["SSH_SETTINGS"] for routes that
# still read a single target from config (they’ll see the active profile).
# -------------------------------------------------------------------
active_prof = _get_active_profile()
if active_prof:
    app.config["SSH_SETTINGS"] = {
        "pi_host": active_prof.get("pi_host", ""),
        "pi_user": active_prof.get("pi_user", ""),
        "auth_method": active_prof.get("auth_method", "key"),
        "ssh_key_path": active_prof.get("ssh_key_path", ""),
        "password": active_prof.get("password", "")
    }
elif os.path.exists(settings_path):
    # last resort legacy file
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            user_settings = json.load(f)
        app.config["SSH_SETTINGS"] = {
            "pi_host": user_settings.get("pi_host", ""),
            "pi_user": user_settings.get("pi_user", ""),
            "auth_method": user_settings.get("auth_method", "key"),
            "ssh_key_path": user_settings.get("ssh_key_path", ""),
            "password": user_settings.get("password", "")
        }
    except Exception as e:
        print(f"[app.py] Error loading settings.json: {e}")
        app.config["SSH_SETTINGS"] = {}
else:
    app.config["SSH_SETTINGS"] = {}

# === Terminal session globals ===
shell_channel = None
shell_lock = threading.Lock()

# === Home route ===
def _profile_is_configured(p: dict) -> bool:
    """Returner True hvis profilen har nok til at kunne forbinde via SSH."""
    if not p:
        return False
    host = (p.get("pi_host") or "").strip()
    user = (p.get("pi_user") or "").strip()
    auth = (p.get("auth_method") or "key").strip()
    if not host or not user:
        return False
    if auth == "key":
        key_path = (p.get("ssh_key_path") or "").strip()
        return bool(key_path)
    else:   # password
        return bool(p.get("password"))

@app.route("/")
def index():
    try:
        # Brug aktiv profil først
        prof = _get_active_profile()
        if not prof:
            return redirect("/settings")

        host = (prof.get("pi_host") or "").strip()
        user = (prof.get("pi_user") or "").strip()
        auth = (prof.get("auth_method") or "key").strip()
        keyp = (prof.get("ssh_key_path") or "").strip()
        pw   = prof.get("password") or ""

        # Mangler nødvendige felter? → direkte til settings
        if not host or not user:
            return redirect("/settings")
        if auth == "key" and not keyp:
            return redirect("/settings")
        if auth == "password" and not pw:
            return redirect("/settings")

        # Let forbindelse-test med korte timeouts
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        if auth == "key":
            pkey = paramiko.RSAKey.from_private_key_file(keyp)
            ssh.connect(host, username=user, pkey=pkey, timeout=4)
        else:
            ssh.connect(host, username=user, password=pw, timeout=4)
        ssh.close()

        # OK → dashboard
        return redirect("/dashboard")

    except Exception as e:
        # Kunne ikke forbinde → vis settings i stedet for 500
        app.logger.warning(f"Home page: Could not connect: {e}")
        return redirect("/settings")

# === Start Flask server in a background thread ===
def run_flask():
    threading.Thread(target=background_updater, daemon=True).start()
    socketio.run(app, host="0.0.0.0", port=8080, debug=True, use_reloader=False)

# === Callback when WebView window is closed ===
def on_window_closed():
    print("Window closed. Shutting down Linux Pi Monitor...")
    os._exit(0)

# === Run app in browser mode ===
def run_browser_mode():
    print("Starting Linux Pi Monitor in browser...")
    print(" * Running at http://127.0.0.1:8080 (CTRL+C to stop)\n")
    threading.Thread(target=run_flask).start()
    webbrowser.open("http://127.0.0.1:8080")
    while True:
        time.sleep(1)

# === Run app in embedded WebView window ===
def run_webview_mode():
    print("Starting Linux Pi Monitor in WebView...")
    threading.Thread(target=run_flask).start()
    window = webview.create_window(
        'Raspberry Pi Monitor',
        'http://127.0.0.1:8080',
        width=1450,
        height=850
    )
    window.events.closed += on_window_closed
    webview.start(gui='qt')

# === Entry point ===
if __name__ == "__main__":
    if "--webview" in sys.argv:
        run_webview_mode()
    else:
        run_browser_mode()
