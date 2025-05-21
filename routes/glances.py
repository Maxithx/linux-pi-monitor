# === routes/glances.py ===
import os
import paramiko
from flask import Blueprint, jsonify, current_app as app, Response, stream_with_context

# === INITIALISERING ===
# Opretter et Flask Blueprint til alle Glances-relaterede ruter
glances_bp = Blueprint("glances", __name__, url_prefix="/glances")

# === SSH-FORBINDELSE ===
# Etablerer en SSH-forbindelse baseret på brugerens gemte settings
def ssh_connect():
    ssh_settings = app.config.get("SSH_SETTINGS", {})
    pi_host = ssh_settings.get("pi_host")
    pi_user = ssh_settings.get("pi_user")
    auth_method = ssh_settings.get("auth_method")
    ssh_key_path = ssh_settings.get("ssh_key_path")
    ssh_password = ssh_settings.get("password")

    if not pi_host or not pi_user:
        raise ValueError("pi_host og pi_user skal være angivet.")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    if auth_method == "key":
        if not ssh_key_path or not os.path.exists(ssh_key_path):
            raise FileNotFoundError(f"SSH-nøgle ikke fundet: {ssh_key_path}")
        key = paramiko.RSAKey.from_private_key_file(ssh_key_path)
        ssh.connect(pi_host, username=pi_user, pkey=key)
    elif auth_method == "password":
        if not ssh_password:
            raise ValueError("Password ikke angivet.")
        ssh.connect(pi_host, username=pi_user, password=ssh_password)
    else:
        raise ValueError("Ukendt godkendelsesmetode.")
    return ssh

# === INSTALLATION AF GLANCES ===
# Kører installationskommandoer og streamer output løbende til browseren
@glances_bp.route("/install-glances", methods=["POST"])
def install_glances():
    def generate():
        try:
            ssh = ssh_connect()
            pi_user = app.config["SSH_SETTINGS"].get("pi_user")

            install_cmds = [
                "sudo apt update",
                "sudo apt install -y python3-pip",
                "pip3 install --break-system-packages 'glances[all]'",
                "pip3 install --break-system-packages jinja2",
                "pip3 install --break-system-packages psutil",
                "pip3 install --break-system-packages requests",
                "pip3 install --break-system-packages fastapi",
                "pip3 install --break-system-packages uvicorn",
                f"mkdir -p /home/{pi_user}/.glances_logs",
                f"""echo "[Unit]
                Description=Glances Web UI
                After=network.target

                [Service]
                ExecStart=/home/{pi_user}/.local/bin/glances -w
                WorkingDirectory=/home/{pi_user}
                StandardOutput=file:/home/{pi_user}/.glances_logs/web.log
                Restart=always
                User={pi_user}
                Environment=PATH=/usr/bin:/bin:/usr/local/bin:/home/{pi_user}/.local/bin

                [Install]
                WantedBy=multi-user.target" | sudo tee /etc/systemd/system/glances-web.service""",
                "sudo systemctl daemon-reexec",
                "sudo systemctl daemon-reload",
                "sudo systemctl enable glances-web.service",
                "sudo systemctl start glances-web.service"
            ]

            for cmd in install_cmds:
                yield f"$ {cmd}\n"
                stdin, stdout, stderr = ssh.exec_command(cmd)
                for line in stdout:
                    yield line
                for line in stderr:
                    yield line
                yield "\n"

            ssh.close()
            yield "[✓] Installation gennemført.\n"
        except Exception as e:
            yield f"[✗] Fejl under installation: {e}\n"

    return Response(stream_with_context(generate()), mimetype='text/plain')

# === AFINSTALLATION AF GLANCES ===
# Stopper tjenesten, fjerner systemd og afinstallerer alle relaterede Python-pakker
@glances_bp.route("/uninstall-glances", methods=["POST"])
def uninstall_glances():
    try:
        ssh = ssh_connect()
        pi_user = app.config["SSH_SETTINGS"].get("pi_user")

        uninstall_cmds = [
            "sudo systemctl stop glances-web.service",
            "sudo systemctl disable glances-web.service",
            "sudo test -f /etc/systemd/system/glances-web.service && sudo rm /etc/systemd/system/glances-web.service",
            "sudo systemctl daemon-reload",

            # Afinstaller alle relaterede moduler
            "pip3 uninstall --break-system-packages -y glances",
            "pip3 uninstall --break-system-packages -y jinja2",
            "pip3 uninstall --break-system-packages -y psutil",
            "pip3 uninstall --break-system-packages -y requests",
            "pip3 uninstall --break-system-packages -y fastapi",
            "pip3 uninstall --break-system-packages -y uvicorn",
            "pip3 uninstall --break-system-packages -y pkg_resources",

            # Ryd kun logfiler, ikke hele mappen
            f"rm -f /home/{pi_user}/.glances_logs/*.log"
        ]

        output = ""
        for cmd in uninstall_cmds:
            stdin, stdout, stderr = ssh.exec_command(cmd)
            out = stdout.read().decode()
            err = stderr.read().decode()
            output += f"$ {cmd}\n{out}{err}\n"

        ssh.close()
        return jsonify(success=True, output=output)

    except Exception as e:
        return jsonify(success=False, output=f"Fejl under afinstallation: {e}")

# === STATUS: Tjek om Glances er installeret og kører ===
@glances_bp.route("/check-glances-status")
def check_glances_status():
    try:
        ssh = ssh_connect()

        # Tjek om Glances binær findes
        stdin, stdout, stderr = ssh.exec_command("test -f ~/.local/bin/glances && echo 'found'")
        installed = stdout.read().decode().strip() == "found"

        # Tjek om tjenesten kører
        stdin, stdout, stderr = ssh.exec_command("pgrep -f 'glances -w'")
        running = stdout.read().decode().strip() != ""

        ssh.close()
        return jsonify(installed=installed, running=running)
    except Exception as e:
        return jsonify(installed=False, running=False, error=str(e))

# === VIS LOG: Hent de sidste 100 linjer af Glances-logfilen ===
@glances_bp.route("/glances-service-log")
def glances_service_log():
    try:
        ssh = ssh_connect()
        pi_user = app.config["SSH_SETTINGS"].get("pi_user")
        log_path = f"/home/{pi_user}/.glances_logs/web.log"
        stdin, stdout, stderr = ssh.exec_command(f"tail -n 100 {log_path}")
        log = stdout.read().decode()
        err = stderr.read().decode()
        ssh.close()
        return jsonify(log=log if log else err)
    except Exception as e:
        return jsonify(log=f"Fejl ved hentning af log: {e}")

# === START TJENESTE: Manuel start af Glances-web.service ===
@glances_bp.route("/start-glances-service", methods=["POST"])
def start_glances_service():
    try:
        ssh = ssh_connect()
        stdin, stdout, stderr = ssh.exec_command("sudo systemctl start glances-web.service")
        out = stdout.read().decode()
        err = stderr.read().decode()
        ssh.close()
        output = out + err
        return jsonify(success=True, output=output or "Glances-tjenesten forsøgt startet.")
    except Exception as e:
        return jsonify(success=False, output=f"Fejl ved start af tjeneste: {e}")
