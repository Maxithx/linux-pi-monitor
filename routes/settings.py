import os
import json
import paramiko
from flask import Blueprint, render_template, request, jsonify, current_app

# === Blueprint for Settings-routes ===
settings_bp = Blueprint("settings", __name__)

# === Route: Nulstil indstillinger ===
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

        settings_path = current_app.config["SETTINGS_PATH"]
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(default_settings, f, indent=4)

        # ✅ Nulstil grafer og data
        global chart_data_cache, latest_metrics, first_cached_metrics
        chart_data_cache = {
            "cpu": [],
            "ram": [],
            "disk": [],
            "network": []
        }
        latest_metrics = {}
        first_cached_metrics = {}

        current_app.logger.info("Indstillinger nulstillet af brugeren.")
        return jsonify({"success": True})
    except Exception as e:
        current_app.logger.error(f"Fejl ved nulstilling: {e}")
        return jsonify({"success": False, "message": "Kunne ikke nulstille indstillinger."})


# === Funktion: Test SSH-forbindelse ===
def test_ssh_connection():
    try:
        settings_path = current_app.config["SETTINGS_PATH"]

        if not os.path.exists(settings_path):
            return False

        with open(settings_path, "r") as f:
            settings = json.load(f)

        if not settings.get("pi_host") or not settings.get("pi_user"):
            return False

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        if settings["auth_method"] == "key":
            key = paramiko.RSAKey.from_private_key_file(settings["ssh_key_path"])
            ssh.connect(settings["pi_host"], username=settings["pi_user"], pkey=key)
        else:
            ssh.connect(settings["pi_host"], username=settings["pi_user"], password=settings["password"])

        ssh.close()
        return True
    except Exception:
        return False

# === Route: Indstillinger-side ===
@settings_bp.route("/settings", endpoint="settings")
def settings():

    settings_path = current_app.config["SETTINGS_PATH"]

    if os.path.exists(settings_path):
        with open(settings_path, "r") as f:
            settings_data = json.load(f)
    else:
        settings_data = {
            "pi_host": "",
            "pi_user": "",
            "auth_method": "key",
            "ssh_key_path": "",
            "password": ""
        }

    connection_status = "connected" if test_ssh_connection() else "disconnected"
    return render_template("settings.html", settings=settings_data, connection_status=connection_status)


# === Route: Gem indstillinger (form submit) ===
@settings_bp.route("/save-settings", methods=["POST"])
def save_settings():
    settings_path = current_app.config["SETTINGS_PATH"]
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

        # ✅ Nulstil caches
        current_app.chart_data_cache = {
            "cpu": [],
            "ram": [],
            "disk": [],
            "network": []
        }
        current_app.latest_metrics = {}
        current_app.first_cached_metrics = {}

        # ✅ Test SSH
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            if new_settings["auth_method"] == "key":
                key_path = new_settings["ssh_key_path"]
                if not os.path.isfile(key_path):
                    return jsonify({"success": False, "message": "SSH-nøglefilen findes ikke: " + key_path})
                if key_path.endswith(".pub"):
                    return jsonify({"success": False, "message": "Du har valgt en .pub-nøgle. Brug den private nøgle (uden .pub)."})
                try:
                    key = paramiko.RSAKey.from_private_key_file(key_path)
                except paramiko.PasswordRequiredException:
                    return jsonify({"success": False, "message": "SSH-nøglen kræver en adgangskode."})
                ssh.connect(new_settings["pi_host"], username=new_settings["pi_user"], pkey=key)

            elif new_settings["auth_method"] == "password":
                ssh.connect(new_settings["pi_host"], username=new_settings["pi_user"], password=new_settings["password"])

            ssh.close()
            current_app.logger.info("Forbindelse til Raspberry Pi godkendt via settings.")
            return jsonify({"success": True, "message": "✔️ Indstillinger blev gemt. Forbindelse oprettet."})

        except Exception as ssh_error:
            current_app.logger.warning(f"Forbindelse mislykkedes: {ssh_error}")
            return jsonify({"success": False, "message": f"Forbindelse mislykkedes: {ssh_error}"})

    except Exception as e:
        current_app.logger.error(f"Fejl i save_settings: {e}")
        return jsonify({"success": False, "message": f"Fejl i gemning: {e}"})

    return jsonify({"success": False, "message": "Ukendt fejl under gem af indstillinger."})


# === Route: Tjek SSH-status (bruges til statusindikator og reboot-check) ===
@settings_bp.route("/check-ssh")
def check_ssh():
    return jsonify({"connected": test_ssh_connection()})


# === Route: HTOP visning ===
@settings_bp.route("/htop-monitor")
def htop_monitor():
    settings_path = current_app.config["SETTINGS_PATH"]
    if os.path.exists(settings_path):
        with open(settings_path, "r") as f:
            settings = json.load(f)
        pi_host = settings.get("pi_host", "")
    else:
        pi_host = ""
    return render_template("htop-monitor.html", settings={"pi_host": pi_host})


# === Route: Genstart Raspberry Pi ===
@settings_bp.route("/reboot-linux", methods=["POST"])
def reboot_linux():
    try:
        settings_path = current_app.config["SETTINGS_PATH"]
        with open(settings_path, "r") as f:
            settings = json.load(f)

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        if settings["auth_method"] == "key":
            key = paramiko.RSAKey.from_private_key_file(settings["ssh_key_path"])
            ssh.connect(settings["pi_host"], username=settings["pi_user"], pkey=key)
        else:
            ssh.connect(settings["pi_host"], username=settings["pi_user"], password=settings["password"])

        ssh.exec_command("sudo reboot")
        ssh.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
