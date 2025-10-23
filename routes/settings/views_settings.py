# routes/settings/views_settings.py
import os
import json
import socket
import base64
import paramiko
from flask import render_template, request, jsonify, current_app
from shlex import quote as sh_quote

from routes.common.ssh_utils import ssh_connect, ssh_exec
from . import settings_bp


# -----------------------------
# Legacy settings helpers
# -----------------------------
def _legacy_settings_path() -> str:
    return current_app.config.get("SETTINGS_PATH")


def _load_legacy_settings() -> dict:
    path = _legacy_settings_path()
    if not path or not os.path.exists(path):
        return {
            "pi_host": "",
            "pi_user": "",
            "auth_method": "key",
            "ssh_key_path": "",
            "password": "",
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
            "password": "",
        }


def _get_active_ssh_settings() -> dict:
    cfg = (current_app.config.get("SSH_SETTINGS") or {}).copy()
    if cfg.get("pi_host") and cfg.get("pi_user"):
        return cfg
    return _load_legacy_settings()


def _is_configured(s: dict) -> bool:
    host = (s.get("pi_host") or "").strip()
    user = (s.get("pi_user") or "").strip()
    auth = (s.get("auth_method") or "key").strip()
    keyp = (s.get("ssh_key_path") or "").strip()
    pw = s.get("password") or ""
    if not host or not user:
        return False
    return bool(keyp) if auth == "key" else bool(pw)


def _quick_port_check(host: str, port: int = 22, timeout: float = 0.7) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _paramiko_ping(s: dict, timeout: float = 2.0) -> bool:
    """Lightweight SSH probe supporting both Ed25519 and RSA keys."""
    host = s.get("pi_host")
    user = s.get("pi_user")
    auth = (s.get("auth_method") or "key").strip()
    keyp = s.get("ssh_key_path")
    pw = s.get("password") or ""

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    if auth == "key":
        key_path = os.path.expanduser(keyp or "")
        key_path = os.path.expandvars(key_path)
        try:
            pkey = paramiko.Ed25519Key.from_private_key_file(key_path)
        except Exception:
            pkey = paramiko.RSAKey.from_private_key_file(key_path)
        ssh.connect(host, username=user, pkey=pkey, timeout=timeout)
    else:
        ssh.connect(host, username=user, password=pw, timeout=timeout)

    ssh.close()
    return True


# -----------------------------
# Settings page + status
# -----------------------------
@settings_bp.route("/settings", endpoint="settings")
def settings():
    active = _get_active_ssh_settings()
    connection_status = "connected" if test_ssh_connection() else "disconnected"
    return render_template("settings.html", settings=active, connection_status=connection_status)


@settings_bp.route("/save-settings", methods=["POST"])
def save_settings():
    settings_path = _legacy_settings_path()
    try:
        new_settings = {
            "pi_host": request.form.get("pi_host", "").strip(),
            "pi_user": request.form.get("pi_user", "").strip(),
            "auth_method": request.form.get("auth_method", "key"),
            "ssh_key_path": request.form.get("ssh_key_path", "").strip(),
            "password": request.form.get("password", "").strip(),
        }
        os.makedirs(os.path.dirname(settings_path), exist_ok=True)
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(new_settings, f, indent=4)

        # reset caches
        current_app.chart_data_cache = {"cpu": [], "ram": [], "disk": [], "network": []}
        current_app.latest_metrics = {}
        current_app.first_cached_metrics = {}

        try:
            if not _is_configured(new_settings):
                return jsonify({"success": False, "message": "Missing required fields."})
            if not _quick_port_check(new_settings["pi_host"], 22, timeout=0.7):
                return jsonify({"success": False, "message": "Host unreachable on port 22."})
            _paramiko_ping(new_settings, timeout=2.0)
            current_app.logger.info("Connection verified")
            return jsonify({"success": True, "message": "Settings saved. Connection established."})
        except Exception as ssh_error:
            return jsonify({"success": False, "message": f"Connection failed: {ssh_error}"})
    except Exception as e:
        return jsonify({"success": False, "message": f"Error saving settings: {e}"})


def test_ssh_connection() -> bool:
    try:
        s = _get_active_ssh_settings()
        if not _is_configured(s):
            return False
        if not _quick_port_check(s["pi_host"], 22, timeout=0.7):
            return False
        return _paramiko_ping(s, timeout=2.0)
    except Exception:
        return False


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


# -----------------------------
# Glances iframe
# -----------------------------
def _glances_url_from_settings(s: dict) -> str:
    host = (s.get("pi_host") or "").strip()
    return f"http://{host}:61208/" if host else ""


@settings_bp.route("/glances", endpoint="glances")
def glances_page():
    s = (current_app.config.get("SSH_SETTINGS") or {}).copy()
    host = (s.get("pi_host") or "").strip()
    if not host:
        try:
            path = current_app.config.get("SETTINGS_PATH")
            if path and os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    legacy = json.load(f)
                host = (legacy.get("pi_host") or "").strip()
        except Exception:
            host = ""
    glances_url = f"http://{host}:61208/" if host else ""
    return render_template("glances.html", glances_url=glances_url)


# -----------------------------
# Reboot (unchanged)
# -----------------------------
@settings_bp.route("/reboot-linux", methods=["POST"])
def reboot_linux():
    try:
        s = _get_active_ssh_settings()
        if not _is_configured(s):
            return jsonify({"success": False, "error": "SSH not configured"})

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        if (s.get("auth_method") or "key") == "key":
            key_path = os.path.expanduser(s.get("ssh_key_path") or "")
            key_path = os.path.expandvars(key_path)
            try:
                pkey = paramiko.Ed25519Key.from_private_key_file(key_path)
            except Exception:
                pkey = paramiko.RSAKey.from_private_key_file(key_path)
            ssh.connect(s["pi_host"], username=s["pi_user"], pkey=pkey, timeout=4)
        else:
            ssh.connect(s["pi_host"], username=s["pi_user"], password=s.get("password", ""), timeout=4)

        ssh.exec_command("sudo reboot")
        ssh.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ============================================================
# Firewall helper: passwordless UFW status (read-only)
# ============================================================

@settings_bp.get("/settings/firewall/sudoers/status")
def firewall_helper_status():
    """
    Check whether passwordless UFW status is enabled on the remote host.
    We do NOT prompt for sudo password here; everything uses 'sudo -n'.
    """
    try:
        s = _get_active_ssh_settings()
        if not _is_configured(s):
            return jsonify({"ok": False, "error": "SSH not configured"})

        ssh = ssh_connect(
            host=s.get("pi_host"),
            user=s.get("pi_user"),
            auth=s.get("auth_method") or "key",
            key_path=s.get("ssh_key_path") or "",
            password=s.get("password") or "",
        )

        exec_steps = []

        def step(name: str, cmd: str, shell: bool = True):
            try:
                rc, out, err = ssh_exec(ssh, cmd, shell=shell)
            except Exception as e:
                rc, out, err = 255, "", str(e)
            exec_steps.append({"step": name, "rc": rc, "out": out or "", "err": err or ""})
            return rc, out or "", err or ""

        # Detect current user and ufw path
        _, out_u, _ = step("detect_user", "id -un")
        user = (out_u or "").strip()
        _, out_p, _ = step("detect_ufw", "command -v ufw 2>/dev/null || echo /usr/sbin/ufw")
        ufw_path = (out_p or "").strip() or "/usr/sbin/ufw"

        # Try sudo -n checks
        rc_s1, _, _ = step("postcheck_sudo_n_status", f"sudo -n {sh_quote(ufw_path)} status >/dev/null 2>&1")
        rc_s2, _, _ = step(
            "postcheck_sudo_n_numbered", f"sudo -n {sh_quote(ufw_path)} status numbered >/dev/null 2>&1"
        )

        sudoers_target = "/etc/sudoers.d/linux-pi-monitor-ufw"
        rc_fp, _, _ = step("check_sudoers_present", f"sudo -n test -f {sh_quote(sudoers_target)}")
        file_mode = ""
        if rc_fp == 0:
            _, out_md, _ = step("chmod_mode", f"sudo -n stat -c %a {sh_quote(sudoers_target)}")
            file_mode = (out_md or "").strip()

        enabled = (rc_s1 == 0 and rc_s2 == 0)

        try:
            ssh.close()
        except Exception:
            pass

        return jsonify(
            {
                "ok": True,
                "enabled": enabled,
                "user": user,
                "ufw_path": ufw_path,
                "sudoers_target": sudoers_target,
                "file_present": (rc_fp == 0),
                "file_mode": file_mode,
                "exec": exec_steps,
            }
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@settings_bp.post('/settings/firewall/sudoers/install')
def firewall_helper_install():
    """
    Install a read-only sudoers helper to allow passwordless:
      ufw status / ufw status verbose / ufw status numbered
    No enable/disable/allow permissions are granted.
    """
    try:
        s = _get_active_ssh_settings()
        if not _is_configured(s):
            return jsonify({"ok": False, "error": "SSH not configured"})

        ssh = ssh_connect(
            host=s.get('pi_host'),
            user=s.get('pi_user'),
            auth=s.get('auth_method') or 'key',
            key_path=s.get('ssh_key_path') or '',
            password=s.get('password') or ''
        )

        sudo_pw = (request.get_json(silent=True) or {}).get('sudo_pw', '')

        # Detect remote user (non-root) once — THIS is who gets NOPASSWD
        rc_u, out_u, _ = ssh_exec(ssh, "id -un", shell=True)
        remote_user = (out_u or "").strip()
        if rc_u != 0 or not remote_user:
            remote_user = s.get('pi_user') or 'root'

        # Root script with rich debug markers
        root_script = r"""#!/usr/bin/env bash
set -u
echo "[LPM] start"
: "${LPM_USER:?missing LPM_USER}"
UFW="$(command -v ufw 2>/dev/null || echo /usr/sbin/ufw)"
TMP="$(mktemp /tmp/lpm-ufw.XXXXXX)"
SUDOERS_TARGET="/etc/sudoers.d/linux-pi-monitor-ufw"

{
  printf 'Cmnd_Alias UFW_STATUS = %s status, %s status verbose, %s status numbered\n' "$UFW" "$UFW" "$UFW"
  printf '%s ALL=(root) NOPASSWD: UFW_STATUS\n' "$LPM_USER"
} > "$TMP" || { echo "[LPM] write_tmp_fail"; exit 2; }

if visudo -cf "$TMP"; then
  echo "[LPM] visudo_ok"
else
  echo "[LPM] visudo_fail"
  exit 3
fi

if install -m 440 "$TMP" "$SUDOERS_TARGET"; then
  echo "[LPM] install_ok"
else
  echo "[LPM] install_fail"
  exit 4
fi
rm -f "$TMP" || true

sudo -n "$UFW" status >/dev/null 2>&1 && echo "[LPM] postcheck_status_ok" || echo "[LPM] postcheck_status_fail"
sudo -n "$UFW" status numbered >/dev/null 2>&1 && echo "[LPM] postcheck_numbered_ok" || echo "[LPM] postcheck_numbered_fail"
echo "[LPM] done"
exit 0
"""

        sb = base64.b64encode(root_script.encode("utf-8")).decode("ascii")
        steps = []

        # Early out: already enabled?
        rc_pre, out_pre, err_pre = ssh_exec(
            ssh,
            'UFW="$(command -v ufw 2>/dev/null || echo /usr/sbin/ufw)"; sudo -n "$UFW" status >/dev/null 2>&1',
            shell=True
        )
        steps.append({"step": "postcheck_sudo_n_status_before", "rc": rc_pre, "out": out_pre, "err": err_pre})
        if rc_pre == 0:
            try: ssh.close()
            except Exception: pass
            return jsonify({"ok": True, "enabled": True, "exec": steps})

        # Write script to remote tmp file
        write_sf = (
            "SF=$(mktemp /tmp/lpm-run.XXXXXX); "
            f"env SB={sh_quote(sb)} python3 - <<'PY' > \"$SF\"\n"
            "import os,base64,sys\n"
            "sys.stdout.buffer.write(base64.b64decode(os.environ['SB']))\n"
            "PY\n"
            "chmod +x \"$SF\"; "
        )

        # Run under sudo with correct user injected
        lpm = sh_quote(remote_user)
        if sudo_pw:
            pwb = base64.b64encode(sudo_pw.encode("utf-8")).decode("ascii")
            run_sf = (
                f"env PWB={sh_quote(pwb)} python3 - <<'PY' | "
                f"sudo -S -k -p '' env LPM_USER={lpm} bash \"$SF\"; RC=$?\n"
                "import os,base64,sys\n"
                "sys.stdout.write(base64.b64decode(os.environ['PWB']).decode('utf-8') + '\\n')\n"
                "PY\n"
            )
        else:
            run_sf = f"sudo -n env LPM_USER={lpm} bash \"$SF\"; RC=$?\n"

        cleanup = "rm -f \"$SF\"; exit ${RC:-1}"
        cmd = write_sf + run_sf + cleanup

        rc, out, err = ssh_exec(ssh, cmd, shell=True)
        steps.append({"step": "sudo_install", "rc": rc, "out": out, "err": err})

        # Verify sudoers file is there and content looks right
        rc_fp, out_fp, err_fp = ssh_exec(ssh, 'sudo -n test -f /etc/sudoers.d/linux-pi-monitor-ufw', shell=True)
        steps.append({"step": "check_sudoers_present", "rc": rc_fp, "out": out_fp, "err": err_fp})
        rc_head, out_head, err_head = ssh_exec(
            ssh, 'sudo -n head -n 4 /etc/sudoers.d/linux-pi-monitor-ufw 2>/dev/null || true', shell=True
        )
        steps.append({"step": "cat_sudoers_head", "rc": rc_head, "out": out_head, "err": err_head})
        rc_mode, out_mode, err_mode = ssh_exec(
            ssh, 'sudo -n stat -c %a /etc/sudoers.d/linux-pi-monitor-ufw 2>/dev/null || true', shell=True
        )
        steps.append({"step": "sudoers_mode", "rc": rc_mode, "out": out_mode, "err": err_mode})

        # Verify it works now
        rc2, out2, err2 = ssh_exec(
            ssh,
            'UFW="$(command -v ufw 2>/dev/null || echo /usr/sbin/ufw)"; sudo -n "$UFW" status >/dev/null 2>&1',
            shell=True
        )
        steps.append({"step": "postcheck_sudo_n_status", "rc": rc2, "out": out2, "err": err2})

        rc3, out3, err3 = ssh_exec(
            ssh,
            'UFW="$(command -v ufw 2>/dev/null || echo /usr/sbin/ufw)"; sudo -n "$UFW" status numbered >/dev/null 2>&1',
            shell=True
        )
        steps.append({"step": "postcheck_sudo_n_numbered", "rc": rc3, "out": out3, "err": err3})

        try:
            ssh.close()
        except Exception:
            pass

        enabled = (rc2 == 0 and rc3 == 0)
        return jsonify({"ok": enabled, "enabled": enabled, "exec": steps})

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@settings_bp.post('/settings/firewall/sudoers/remove')
def firewall_helper_remove():
    """Remove sudoers helper."""
    try:
        s = _get_active_ssh_settings()
        if not _is_configured(s):
            return jsonify({"ok": False, "error": "SSH not configured"})

        ssh = ssh_connect(
            host=s.get('pi_host'),
            user=s.get('pi_user'),
            auth=s.get('auth_method') or 'key',
            key_path=s.get('ssh_key_path') or '',
            password=s.get('password') or ''
        )

        sudo_pw = (request.get_json(silent=True) or {}).get('sudo_pw', '')

        if sudo_pw:
            pwb = base64.b64encode(sudo_pw.encode("utf-8")).decode("ascii")
            remote = (
                f"env PWB={sh_quote(pwb)} python3 - <<'PY' | "
                "sudo -S -k -p '' sh -lc 'rm -f /etc/sudoers.d/linux-pi-monitor-ufw && echo removed || true'\n"
                "import os,base64,sys\n"
                "sys.stdout.write(base64.b64decode(os.environ['PWB']).decode('utf-8') + '\\n')\n"
                "PY"
            )
        else:
            remote = "sudo -n rm -f /etc/sudoers.d/linux-pi-monitor-ufw && echo removed || true"

        rc, out, err = ssh_exec(ssh, remote, shell=True)

        # Post-check: should fail without password now
        rc2, _, _ = ssh_exec(
            ssh,
            'UFW="$(command -v ufw 2>/dev/null || echo /usr/sbin/ufw)"; sudo -n "$UFW" status >/dev/null 2>&1',
            shell=True
        )

        try:
            ssh.close()
        except Exception:
            pass

        return jsonify({"ok": rc == 0, "enabled": (rc2 == 0), "log": (out or err or "").strip()})

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
