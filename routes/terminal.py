import os
import threading
import paramiko
import socket
from flask import Blueprint, render_template, current_app, jsonify, request
from flask_socketio import emit
from socketio_instance import socketio

terminal_bp = Blueprint("terminal", __name__)

shell_channel = None
shell_lock = threading.Lock()

@terminal_bp.route("/terminal")
def terminal():
    return render_template("terminal.html")

@socketio.on("input")
def handle_input(data):
    global shell_channel
    with shell_lock:
        if shell_channel:
            try:
                shell_channel.send(data)
            except Exception as e:
                emit("output", f"Fejl ved afsendelse: {e}")

@socketio.on("connect")
def handle_connect():
    global shell_channel
    try:
        settings = current_app.config.get("SSH_SETTINGS", {})
        if not settings:
            emit("output", "Fejl: SSH-indstillinger ikke fundet.")
            return

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        if settings.get("auth_method") == "key":
            key_path = settings.get("ssh_key_path", "")
            if not os.path.exists(key_path):
                emit("output", f"Fejl: SSH-nøgle findes ikke: {key_path}")
                return
            key = paramiko.RSAKey.from_private_key_file(key_path)
            ssh.connect(settings["pi_host"], username=settings["pi_user"], pkey=key)
        else:
            ssh.connect(settings["pi_host"], username=settings["pi_user"], password=settings["password"])

        with shell_lock:
            shell_channel = ssh.invoke_shell(term='xterm-256color')
            shell_channel.settimeout(0.1)
            shell_channel.send("export LANG=en_US.UTF-8\n")
            shell_channel.send("export LC_ALL=en_US.UTF-8\n")
            shell_channel.send("clear\n")

        threading.Thread(target=read_output_loop, daemon=True).start()

    except Exception as e:
        emit("output", f"Fejl under forbindelse: {e}")

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

# ✅ NY ROUTE – Genstart Linux via SSH
@terminal_bp.route("/terminal/reboot-linux", methods=["POST"])
def reboot_linux():
    try:
        settings = current_app.config.get("SSH_SETTINGS", {})
        if not settings:
            return jsonify({"success": False, "message": "SSH-indstillinger ikke fundet."})

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        if settings.get("auth_method") == "key":
            key_path = settings.get("ssh_key_path", "")
            if not os.path.exists(key_path):
                return jsonify({"success": False, "message": "SSH-nøgle findes ikke."})
            key = paramiko.RSAKey.from_private_key_file(key_path)
            ssh.connect(settings["pi_host"], username=settings["pi_user"], pkey=key)
        else:
            ssh.connect(settings["pi_host"], username=settings["pi_user"], password=settings["password"])

        ssh.exec_command("nohup sudo reboot > /dev/null 2>&1 &")
        ssh.close()

        return jsonify({"success": True, "message": "Genstarter Linux..."})

    except Exception as e:
        print(f"Fejl under genstart: {e}")
        return jsonify({"success": False, "message": f"Fejl: {e}"})

@socketio.on("disconnect")
def handle_disconnect():
    global shell_channel
    with shell_lock:
        if shell_channel:
            try:
                shell_channel.close()
            except Exception as e:
                print(f"Fejl ved lukning af SSH-kanal: {e}")
            shell_channel = None
