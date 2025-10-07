# === app.py ===
# Main entry point for the Linux Pi Monitor web app

import eventlet
eventlet.monkey_patch()

import webview
import webbrowser
from flask import Flask, render_template, jsonify, request, redirect, session, url_for, Response
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
import traceback
from typing import List

# --- Glances proxy blueprints (fail-soft if file not present) ---
try:
    from routes.glances import glances_bp, glances_api_bp
except Exception:
    glances_bp = None
    glances_api_bp = None

# === Import routes and sidebar context injection ===
from routes import register_routes
from routes.sidebar import register_sidebar_context

# === Flask app setup ===
app = Flask(__name__, instance_relative_config=True)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-change-me-please")
app.config.update(
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,
    TEMPLATES_AUTO_RELOAD=True,
    SEND_FILE_MAX_AGE_DEFAULT=0,
)

# Sørg for instance/logs
try:
    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(os.path.join(app.instance_path, "logs"), exist_ok=True)
except Exception as _e:
    print(f"[app.py] Could not create instance/logs dirs: {_e}")

socketio.init_app(app)

# ──────────────────────────────────────────────────────────────────────────────
# GLOBAL template context (status + settings + glances_url i ALLE templates)
# ──────────────────────────────────────────────────────────────────────────────
@app.context_processor
def inject_global_template_vars():
    try:
        from routes.settings import (
            test_ssh_connection,
            _get_active_ssh_settings,
            _glances_url_from_settings,
        )
        s = _get_active_ssh_settings() or {}
        status = "connected" if test_ssh_connection() else "disconnected"
        glances_url = _glances_url_from_settings(s) if s else ""
        return {"connection_status": status, "settings": s, "glances_url": glances_url}
    except Exception:
        return {"connection_status": "disconnected", "settings": {}, "glances_url": ""}

# Importér session blueprint
from session import session_bp
app.register_blueprint(session_bp)

# Registrér sidebar og ALLE app-ruter
register_sidebar_context(app)
register_routes(app)

# Tilføj Glances-proxy hvis den ikke allerede er registreret
def _register_if_missing(bp):
    if not bp:
        return
    try:
        if bp.name not in app.blueprints:
            app.register_blueprint(bp)
            app.logger.info("Registered blueprint: %s", bp.name)
        else:
            app.logger.info("Blueprint already present, skipped: %s", bp.name)
    except Exception as e:
        app.logger.warning("Could not register blueprint %s: %s", getattr(bp, "name", "?"), e)

_register_if_missing(glances_bp)
_register_if_missing(glances_api_bp)

# ── App data paths ────────────────────────────────────────────────────────────
def _resolve_appdata_dir() -> str:
    env_override = os.getenv("RPI_MONITOR_DATA")
    if env_override:
        return env_override
    if os.name == "nt":
        base = os.getenv("APPDATA") or os.path.expanduser(r"~\AppData\Roaming")
        return os.path.join(base, "raspberry_pi_monitor")
    xdg = os.getenv("XDG_CONFIG_HOME")
    base = xdg if xdg else os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "raspberry_pi_monitor")

appdata_dir = _resolve_appdata_dir()
os.makedirs(appdata_dir, exist_ok=True)

settings_path = os.path.join(appdata_dir, "settings.json")
log_file_path  = os.path.join(appdata_dir, "server_logs.txt")
profiles_path  = os.path.join(appdata_dir, "ssh_profiles.json")

app.config["SETTINGS_PATH"] = settings_path
app.config["LOG_FILE_PATH"] = log_file_path
app.config["PROFILES_PATH"] = profiles_path
os.environ["RPI_MONITOR_PROFILES_PATH"] = app.config["PROFILES_PATH"]

# ── Profiles helpers + legacy migration ───────────────────────────────────────
def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def _load_profiles():
    if os.path.exists(profiles_path):
        with open(profiles_path, "r", encoding="utf-8") as f:
            return json.load(f)
    base = {"profiles": [], "active_profile_id": None, "default_profile_id": None}
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                s = json.load(f)
            pid = str(uuid.uuid4())
            prof = {
                "id": pid, "name": "Default",
                "pi_host": s.get("pi_host", ""), "pi_user": s.get("pi_user", ""),
                "auth_method": s.get("auth_method", "key"),
                "ssh_key_path": s.get("ssh_key_path", ""), "password": s.get("password", "")
            }
            base["profiles"] = [prof]
            base["active_profile_id"] = pid
            base["default_profile_id"] = pid
            _write_json(profiles_path, base)
            return base
        except Exception as e:
            print(f"[app.py] Profiles migration failed: {e}")
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

@app.context_processor
def inject_profiles():
    data = _load_profiles()
    return dict(
        profiles=data.get("profiles", []),
        active_profile_id=data.get("active_profile_id"),
        default_profile_id=data.get("default_profile_id"),
    )

# ── Logging config ────────────────────────────────────────────────────────────
logging.basicConfig(
    filename=log_file_path,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
handler = logging.FileHandler(log_file_path, encoding="utf-8")
handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(message)s')
handler.setFormatter(formatter)
app.logger.addHandler(handler)

logfile = open(log_file_path, 'a', encoding='utf-8')
sys.stderr = sys.stdout

# Slå cache fra for JSON/plain
@app.after_request
def _no_cache_for_api(resp):
    ct = (resp.headers.get("Content-Type") or "")
    if ct.startswith("application/json") or ct.startswith("text/plain"):
        resp.headers["Cache-Control"] = "no-store"
    return resp

# ── Forbedret error handler: vis traceback i browseren ────────────────────────
@app.errorhandler(Exception)
def _unhandled(e: Exception):
    tb = traceback.format_exc()
    try:
        app.logger.error("Unhandled error: %s\n%s", e, tb)
    except Exception:
        pass
    body = (
        "Unhandled error (500)\n\n"
        f"{e}\n\n"
        "Traceback:\n"
        f"{tb}"
    )
    # Returnér en simpel tekstside så vi kan se præcis hvilken linje/fil fejler
    return Response(body, status=500, mimetype="text/plain; charset=utf-8")

# === Små DEBUG endpoints ===
@app.get("/_debug/health")
def _debug_health():
    return jsonify({"ok": True, "time": time.time()})

@app.get("/_debug/config")
def _debug_config():
    return jsonify({
        "instance_path": app.instance_path,
        "instance_logs_dir": os.path.join(app.instance_path, "logs"),
        "glances_install_log": os.path.join(app.instance_path, "logs", "glances_install.log"),
        "appdata_dir": appdata_dir,
        "settings_path": settings_path,
        "profiles_path": profiles_path,
        "server_log": log_file_path,
    })

@app.get("/_debug/routes")
def _debug_routes():
    routes = []
    for rule in app.url_map.iter_rules():
        routes.append({
            "rule": str(rule),
            "endpoint": rule.endpoint,
            "methods": sorted(m for m in rule.methods if m not in ("HEAD", "OPTIONS")),
        })
    routes.sort(key=lambda r: r["rule"])
    return jsonify({"count": len(routes), "routes": routes})

def _tail_lines(path: str, max_lines: int = 500) -> List[str]:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block = 4096
            data = b""
            while size > 0 and data.count(b"\n") <= max_lines:
                read_size = block if size >= block else size
                size -= read_size
                f.seek(size)
                data = f.read(read_size) + data
            text = data.decode("utf-8", errors="replace")
            lines = text.splitlines()[-max_lines:]
            return lines
    except FileNotFoundError:
        return []
    except Exception as e:
        return [f"[tail error] {e}"]

@app.get("/_debug/glances-log")
def _debug_glances_log():
    n = request.args.get("n", default=300, type=int)
    log_path = os.path.join(app.instance_path, "logs", "glances_install.log")
    lines = _tail_lines(log_path, max_lines=max(50, min(n, 2000)))
    return ("\n".join(lines), 200, {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "no-store",
    })

# ── Back-compat: udfyld app.config["SSH_SETTINGS"] fra aktiv profil ──────────
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
    else:
        return bool(p.get("password"))

@app.route("/")
def index():
    try:
        prof = _get_active_profile()
        if not prof:
            return redirect("/settings")

        host = (prof.get("pi_host") or "").strip()
        user = (prof.get("pi_user") or "").strip()
        auth = (prof.get("auth_method") or "key").strip()
        keyp = (prof.get("ssh_key_path") or "").strip()
        pw   = prof.get("password") or ""

        if not host or not user:
            return redirect("/settings")
        if auth == "key" and not keyp:
            return redirect("/settings")
        if auth == "password" and not pw:
            return redirect("/settings")

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        if auth == "key":
            pkey = paramiko.RSAKey.from_private_key_file(keyp)
            ssh.connect(host, username=user, pkey=pkey, timeout=4)
        else:
            ssh.connect(host, username=user, password=pw, timeout=4)
        ssh.close()

        return redirect("/dashboard")

    except Exception as e:
        app.logger.warning(f"Home page: Could not connect: {e}")
        return redirect("/settings")

# Legacy shims til glances-filer i roden
@app.route("/glances.js")
def _root_glances_js():
    return Response("/* legacy root glances.js shim */", mimetype="application/javascript", status=200)

@app.route("/glances.css")
def _root_glances_css():
    return Response("/* legacy root glances.css shim */", mimetype="text/css", status=200)

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
    print(" * Running at http://127.0.0.1:8080 (CTRL+C to stop)")
    print(" * Debug routes: /_debug/health  /_debug/routes  /_debug/config  /_debug/glances-log\n")
    threading.Thread(target=run_flask).start()
    webbrowser.open("http://127.0.0.1:8080")
    while True:
        time.sleep(1)

# === Run app in embedded WebView window ===
def run_webview_mode():
    print("Starting Linux Pi Monitor in WebView...")
    threading.Thread(target=run_flask).start()
    window = webview.create_window('Raspberry Pi Monitor', 'http://127.0.0.1:8080', width=1450, height=850)
    window.events.closed += on_window_closed
    webview.start(gui='qt')

# === Entry point ===
if __name__ == "__main__":
    if "--webview" in sys.argv:
        run_webview_mode()
    else:
        run_browser_mode()
