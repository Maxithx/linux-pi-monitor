import eventlet
eventlet.monkey_patch()

import webview
import webbrowser
from flask import Flask, render_template, jsonify, request, redirect
from utils import background_updater
from socketio_instance import socketio
import paramiko
import threading
import os
import logging
import sys
import json
import time

# Importér dine routes og SSH konfiguration
from routes import register_routes

app = Flask(__name__)
socketio.init_app(app)

from routes.sidebar import register_sidebar_context
register_sidebar_context(app)

# efter app = Flask(...)
register_sidebar_context(app)


# Konfigurations- og logstier
appdata_dir = os.path.join(os.getenv("APPDATA"), "raspberry_pi_monitor")
os.makedirs(appdata_dir, exist_ok=True)
settings_path = os.path.join(appdata_dir, "settings.json")
log_file_path = os.path.join(appdata_dir, "server_logs.txt")

app.config["SETTINGS_PATH"] = settings_path
app.config["LOG_FILE_PATH"] = log_file_path

# === Indlæs SSH-indstillinger fra settings.json FØR routes ===
if os.path.exists(settings_path):
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
        print(f"[app.py] Fejl ved indlæsning af settings.json: {e}")
        app.config["SSH_SETTINGS"] = {}
else:
    app.config["SSH_SETTINGS"] = {}

# === Registrér routes efter SSH_SETTINGS er klar ===
register_routes(app)

# Global shell-channel til terminalen
shell_channel = None
shell_lock = threading.Lock()

# Logging
logging.basicConfig(filename=log_file_path, level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s")
handler = logging.FileHandler(log_file_path)
handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(message)s')
handler.setFormatter(formatter)
app.logger.addHandler(handler)

logfile = open(log_file_path, 'a', encoding='utf-8')
sys.stderr = sys.stdout


# === Flask routes ===
@app.route("/")
def index():
    try:
        if not os.path.exists(settings_path):
            return redirect("/settings")

        with open(settings_path, "r", encoding="utf-8") as f:
            settings = json.load(f)

        if not settings.get("pi_host") or not settings.get("pi_user"):
            return redirect("/settings")

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        if settings["auth_method"] == "key":
            key = paramiko.RSAKey.from_private_key_file(settings["ssh_key_path"])
            ssh.connect(settings["pi_host"], username=settings["pi_user"], pkey=key)
        elif settings["auth_method"] == "password":
            ssh.connect(settings["pi_host"], username=settings["pi_user"], password=settings["password"])

        ssh.close()
        return redirect("/dashboard")

    except Exception as e:
        app.logger.warning(f"Startside kunne ikke forbinde til Raspberry Pi: {e}")
        return redirect("/settings")


# === Flask server start ===
def run_flask():
    threading.Thread(target=background_updater, daemon=True).start()
    socketio.run(app, host="0.0.0.0", port=8080, debug=True, use_reloader=False)

def on_window_closed():
    print("Vinduet blev lukket. Lukker hele Raspberry Pi Monitor...")
    os._exit(0)

def run_browser_mode():
    print("Starter Raspberry Pi Monitor i browser...")
    print(" * Running on http://127.0.0.1:8080 (Tryk CTRL+C for at stoppe)\n")
    threading.Thread(target=run_flask).start()
    webbrowser.open("http://127.0.0.1:8080")
    while True:
        time.sleep(1)

def run_webview_mode():
    print("Starter Raspberry Pi Monitor i WebView...")
    threading.Thread(target=run_flask).start()
    window = webview.create_window(
        'Raspberry Pi Monitor',
        'http://127.0.0.1:8080',
        width=1450,
        height=850
    )
    window.events.closed += on_window_closed
    webview.start(gui='qt')

if __name__ == "__main__":
    if "--webview" in sys.argv:
        run_webview_mode()
    else:
        run_browser_mode()
