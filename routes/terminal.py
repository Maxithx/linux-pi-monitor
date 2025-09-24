# === IMPORTS ===
import os
import threading
import paramiko
import socket
from flask import Blueprint, render_template, current_app, jsonify, request
from flask_socketio import emit
from socketio_instance import socketio

# === FLASK BLUEPRINT ===
terminal_bp = Blueprint("terminal", __name__)

# === GLOBAL VARIABLES ===
shell_channel = None
shell_lock = threading.Lock()

# === ROUTE: Render the terminal web UI ===
@terminal_bp.route("/terminal")
def terminal():
    return render_template("terminal.html")

# === SOCKETIO: Handle input from the browser terminal ===
@socketio.on("input")
def handle_input(data):
    global shell_channel
    with shell_lock:
        if shell_channel:
            try:
                shell_channel.send(data)
            except Exception as e:
                emit("output", f"Error sending data: {e}")

# === SOCKETIO: On WebSocket connect from the browser ===
@socketio.on("connect")
def handle_connect():
    global shell_channel
    try:
        settings = current_app.config.get("SSH_SETTINGS", {})
        if not settings:
            emit("output", "Error: SSH settings not found.")
            return

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        # === Establish SSH connection (key or password) ===
        if settings.get("auth_method") == "key":
            key_path = settings.get("ssh_key_path", "")
            if not os.path.exists(key_path):
                emit("output", f"Error: SSH key does not exist: {key_path}")
                return
            key = paramiko.RSAKey.from_private_key_file(key_path)
            ssh.connect(settings["pi_host"], username=settings["pi_user"], pkey=key)
        else:
            ssh.connect(settings["pi_host"], username=settings["pi_user"], password=settings["password"])

        # === Open shell and set environment ===
        with shell_lock:
            shell_channel = ssh.invoke_shell(term='xterm-256color')
            shell_channel.settimeout(0.1)
            shell_channel.send("export LANG=en_US.UTF-8\n")
            shell_channel.send("export LC_ALL=en_US.UTF-8\n")
            shell_channel.send("clear\n")

        # === Start background thread for reading shell output ===
        threading.Thread(target=read_output_loop, daemon=True).start()

    except Exception as e:
        emit("output", f"Connection error: {e}")

# === BACKGROUND LOOP: Read output from SSH and emit to browser ===
def read_output_loop():
    global shell_channel
    while True:
        with shell_lock:
            if shell_channel and shell_channel.recv_ready():
                try:
                    output = shell_channel.recv(4096).decode("utf-8", errors="replace")
                    socketio.emit("output", output)
                except Exception:
                    break
        socketio.sleep(0.1)

# === ROUTE: Check SSH availability (called by frontend) ===
@terminal_bp.route("/check-ssh-status")
def check_ssh_status():
    settings = current_app.config.get("SSH_SETTINGS", {})
    pi_host = settings.get("pi_host")
    if not pi_host:
        return jsonify({"status": "disconnected"})

    try:
        with socket.create_connection((pi_host, 22), timeout=1):
            return jsonify({"status": "connected"})
    except:
        return jsonify({"status": "disconnected"})

# === ROUTE: Reboot Linux via SSH (triggered from frontend button) ===
@terminal_bp.route("/terminal/reboot-linux", methods=["POST"])
def reboot_linux():
    try:
        settings = current_app.config.get("SSH_SETTINGS", {})
        if not settings:
            return jsonify({"success": False, "message": "SSH settings not found."})

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        if settings.get("auth_method") == "key":
            key_path = settings.get("ssh_key_path", "")
            if not os.path.exists(key_path):
                return jsonify({"success": False, "message": "SSH key does not exist."})
            key = paramiko.RSAKey.from_private_key_file(key_path)
            ssh.connect(settings["pi_host"], username=settings["pi_user"], pkey=key)
        else:
            ssh.connect(settings["pi_host"], username=settings["pi_user"], password=settings["password"])

        # Execute reboot command in background
        ssh.exec_command("nohup sudo reboot > /dev/null 2>&1 &")
        ssh.close()

        return jsonify({"success": True, "message": "Rebooting Linux..."})

    except Exception as e:
        print(f"Error during reboot: {e}")
        return jsonify({"success": False, "message": f"Error: {e}"})

# === SOCKETIO: Handle terminal disconnect ===
@socketio.on("disconnect")
def handle_disconnect():
    global shell_channel
    with shell_lock:
        if shell_channel:
            try:
                shell_channel.close()
            except Exception as e:
                print(f"Error closing SSH channel: {e}")
            shell_channel = None
