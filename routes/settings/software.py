from flask import Blueprint, jsonify
from utils import ssh_run  # Henter SSH-fjernkommando funktionen

# === SOFTWARE BLUEPRINT ===
software_bp = Blueprint("software", __name__)

# === INSTALLATION: NEOFETCH ===
@software_bp.route("/install-neofetch", methods=["POST"])
def install_neofetch():
    output = ssh_run("sudo apt-get update && sudo apt-get install -y neofetch")
    return jsonify({"success": True, "output": output})

# === AFINSTALLATION: NEOFETCH ===
@software_bp.route("/uninstall-neofetch", methods=["POST"])
def uninstall_neofetch():
    output = ssh_run("sudo apt-get remove -y neofetch")
    return jsonify({"success": True, "output": output})

# === INSTALLATION: CMATRIX ===
@software_bp.route("/install-cmatrix", methods=["POST"])
def install_cmatrix():
    output = ssh_run("sudo apt-get update && sudo apt-get install -y cmatrix")
    return jsonify({"success": True, "output": output})

# === AFINSTALLATION: CMATRIX ===
@software_bp.route("/uninstall-cmatrix", methods=["POST"])
def uninstall_cmatrix():
    output = ssh_run("sudo apt-get remove -y cmatrix")
    return jsonify({"success": True, "output": output})

# === INSTALLATIONSTJEK: Viser hvilke programmer der er installeret ===
@software_bp.route("/check-install-status", methods=["GET"])
def check_install_status():
    # Brug dpkg-query til at tjekke om pakken er korrekt installeret
    status_neofetch = "Status: install ok installed" in ssh_run("dpkg-query -s neofetch 2>/dev/null")
    status_cmatrix = "Status: install ok installed" in ssh_run("dpkg-query -s cmatrix 2>/dev/null")

    return jsonify({
        "neofetch": status_neofetch,
        "cmatrix": status_cmatrix
    })

