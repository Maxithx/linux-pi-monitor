# routes/settings.py
import os
import json
import re
import shlex
import socket
import paramiko
from flask import Blueprint, render_template, request, jsonify, current_app
from .ssh_utils import ssh_connect, ssh_exec


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

def _with_sudo_password(cmd: str, settings: dict) -> str:
    """
    Hvis profilen har sudo-password, konverter alle 'sudo' tokens til:
      printf "%s\n" "<pw>" | sudo -S -p "" ...
    Ellers returneres cmd uændret.
    """
    pw = (settings.get("password") or "").strip()
    if not pw or "sudo" not in cmd:
        return cmd
    quoted_pw = shlex.quote(pw)
    return re.sub(
        r'(?<![A-Za-z0-9_-])sudo(?![A-Za-z0-9_-])',
        f'printf "%s\\n" {quoted_pw} | sudo -S -p ""',
        cmd
    )

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
    active = _get_active_ssh_settings()
    connection_status = "connected" if test_ssh_connection() else "disconnected"
    return render_template("settings.html", settings=active, connection_status=connection_status)

# ---------------------------------------------------------------------------
# Legacy "save-settings" (backwards compat). UI bruger nu "Save profile".
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
# HTOP/Glances view (bruger kun host til at bygge siden)
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

        # Brug samme sudo-password teknik
        cmd = _with_sudo_password("sudo reboot", s)
        ssh.exec_command(cmd)
        ssh.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# ---------------------------------------------------------------------------
# Updates UI
# ---------------------------------------------------------------------------
@settings_bp.route("/updates", endpoint="updates")
def updates():
    """
    'Windows Update'-agtig side for Linux (APT/Flatpak/Snap/Docker).
    Viser også connection-status badge.
    """
    connection_status = "connected" if test_ssh_connection() else "disconnected"
    return render_template("update.html", connection_status=connection_status)

# ---------------------------------------------------------------------------
# Run update actions via SSH (JSON POST)
# Body: {"action": "<one-of>"}
# ---------------------------------------------------------------------------
def _active_ssh():
    s = _get_active_ssh_settings()
    if not _is_configured(s):
        raise RuntimeError("SSH not configured")
    return s

_ACTIONS = {
    # --- APT (Ubuntu/Mint) ---
    "apt_update":        "sudo apt update",
    "apt_list":          "apt list --upgradable",
    "apt_dry_full":      "sudo apt-get -s dist-upgrade",
    "apt_upgrade":       "sudo apt upgrade -y",
    "apt_full_upgrade":  "sudo apt full-upgrade -y",
    "reboot_required":   'if [ -f /run/reboot-required ]; then echo "REBOOT_REQUIRED"; else echo "NO_REBOOT"; fi',

    # --- Flatpak ---
    "flatpak_dry":       "flatpak update --appstream && flatpak update --assumeyes --dry-run",
    "flatpak_apply":     "flatpak update -y",

    # --- Snap ---
    "snap_list":         "sudo snap refresh --list",
    "snap_refresh":      "sudo snap refresh",

    # --- Docker (info) ---
    "docker_ps":         'docker ps --format "{{.Names}}\\t{{.Image}}\\t{{.Status}}" || true',

    # --- One-click full update (apt + cleanup + flatpak/snap + reboot-check) ---
    "full_noob_update": (
        "sudo DEBIAN_FRONTEND=noninteractive apt update && "
        "sudo DEBIAN_FRONTEND=noninteractive apt full-upgrade -y && "
        "sudo apt autoremove --purge -y && "
        "sudo apt autoclean && "
        "( command -v flatpak >/dev/null 2>&1 && flatpak update -y || true ) && "
        "( command -v snap >/dev/null 2>&1 && sudo snap refresh || true ) && "
        '( test -f /run/reboot-required && echo "REBOOT_REQUIRED" || echo "NO_REBOOT" )'
    ),
}

@settings_bp.post("/updates/run")
def updates_run():
    try:
        data = request.get_json(force=True) or {}
        action = (data.get("action") or "").strip()
        cmd = _ACTIONS.get(action)
        if not cmd:
            return jsonify({"ok": False, "error": f"Unknown action: {action}"}), 400

        s = _active_ssh()
        cmd = _with_sudo_password(cmd, s)  # <-- feed sudo password when needed

        ssh = ssh_connect(
            host=s["pi_host"],
            user=s["pi_user"],
            auth=s.get("auth_method", "key"),
            key_path=s.get("ssh_key_path",""),
            password=s.get("password",""),
            timeout=20
        )
        rc, out, err = ssh_exec(ssh, cmd, timeout=180)
        try:
            ssh.close()
        except Exception:
            pass

        return jsonify({
            "ok": True,
            "rc": rc,
            "stdout": out,
            "stderr": err
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

# ---------------------------------------------------------------------------
# List available updates (structured JSON for UI table)
# ---------------------------------------------------------------------------
@settings_bp.get("/updates/list")
def updates_list():
    """
    Return a structured list of available APT updates:
    name, current -> candidate, repo/pocket, security flag, short changelog, CVEs.
    """
    try:
        s = _active_ssh()
        ssh = ssh_connect(
            host=s["pi_host"],
            user=s["pi_user"],
            auth=s.get("auth_method", "key"),
            key_path=s.get("ssh_key_path",""),
            password=s.get("password",""),
            timeout=20
        )

        # 1) Ensure fresh package lists (use sudo password if needed)
        ssh_exec(ssh, _with_sudo_password("sudo apt update", s), timeout=180)

        # 2) Raw upgradable list (skip first header line)
        rc, out, err = ssh_exec(ssh, "apt list --upgradable 2>/dev/null | tail -n +2", timeout=120)
        if rc != 0:
            try: ssh.close()
            except: pass
            return jsonify({"ok": False, "error": err or "apt list failed"}), 500

        pkgs = []
        for line in (out or "").splitlines():
            line = line.strip()
            if not line or "/" not in line:
                continue
            # Example:
            # pkg/noble-updates 1.2.3 amd64 [upgradable from: 1.2.2]
            # (localized bracket text supported)
            name = line.split("/", 1)[0]

            # Candidate version heuristic from tokens
            parts = line.split()
            candidate = None
            for p in parts:
                if any(ch.isdigit() for ch in p) and not p.endswith(",now"):
                    candidate = p
                    break

            # Current (from bracket)
            m = re.search(r"\[(?:.*?:|.*?fra:)\s*([^\]]+)\]", line)
            current = m.group(1).strip() if m else ""

            # 3) apt-cache policy for repo/pocket + real installed/candidate
            rc2, pol, _ = ssh_exec(ssh, f"apt-cache policy {name}", timeout=60)
            repo = ""
            if rc2 == 0 and pol:
                mcand = re.search(r"Candidate:\s*([^\s]+)", pol)
                if mcand:
                    candidate = mcand.group(1).strip()
                mcurr = re.search(r"Installed:\s*([^\s]+)", pol)
                if mcurr and (not current or current == "(none)"):
                    current = mcurr.group(1).strip()
                # suite/pocket from 'http ... noble-security ...'
                msuite = re.search(r"\s[a-z0-9-]+://[^\s]+\s+([a-z0-9-]+)\s", pol, re.I)
                if msuite:
                    repo = msuite.group(1).strip()

            security = repo.endswith("-security") if repo else False

            # 4) Short changelog + link + CVEs
            summary = ""
            cl_link = ""
            rc3, chlog, _ = ssh_exec(ssh, f"apt-get changelog -qq {name}", timeout=90)
            if rc3 == 0 and chlog:
                for l in chlog.splitlines():
                    t = l.strip()
                    if t and not t.startswith("---"):
                        summary = t
                        break
                murl = re.search(r"(https?://\S+)", chlog)
                if murl:
                    cl_link = murl.group(1)
            cves = re.findall(r"(CVE-\d{4}-\d+)", chlog or "")
            cve_links = [f"https://ubuntu.com/security/{cve}" for cve in cves]

            pkgs.append({
                "name": name,
                "current": current,
                "candidate": candidate or "",
                "repo": repo,
                "security": bool(security),
                "summary": summary,
                "cves": cves[:6],
                "links": {
                    "changelog": cl_link,
                    "cves": cve_links[:6]
                }
            })

        try:
            ssh.close()
        except Exception:
            pass

        return jsonify({"ok": True, "updates": pkgs})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
