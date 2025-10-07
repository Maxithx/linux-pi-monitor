# routes/glances_manage.py
from __future__ import annotations

import os
from flask import Blueprint, jsonify, request, make_response, current_app
from collections import deque
from datetime import datetime

from .ssh_utils import ssh_connect, ssh_exec
from .settings import _get_active_ssh_settings, _is_configured

glances_bp = Blueprint("glances_admin", __name__)

# --------------------- small log helpers ---------------------

def _glances_log_path() -> str:
    logdir = os.path.join(current_app.instance_path, "logs")
    os.makedirs(logdir, exist_ok=True)
    return os.path.join(logdir, "glances_install.log")

def _log_append(text: str):
    try:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(_glances_log_path(), "a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {text.rstrip()}\n")
    except Exception:
        pass

def _log_reset():
    try:
        p = _glances_log_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Log started\n")
    except Exception:
        pass

# --------------------- SSH helpers ---------------------

def _sudo_cmd(cmd: str, sudo_pw: str | None) -> str:
    quoted = cmd.replace('"', r'\"')
    if sudo_pw:
        return f'echo "{sudo_pw}" | sudo -S sh -lc "{quoted}"'
    return f'sudo -n sh -lc "{quoted}"'

def _ssh_run_logged(ssh, cmd: str, sudo_pw: str | None = None, timeout: int = 300) -> int:
    _log_append(f"$ {cmd}")
    rc, out, err = ssh_exec(ssh, _sudo_cmd(cmd, sudo_pw) if sudo_pw is not None else cmd, timeout=timeout)
    if out: _log_append(out.rstrip())
    if err: _log_append("[stderr]\n" + err.rstrip())
    _log_append(f"[exit {rc}]")
    return rc

def _ssh_run_user(ssh, cmd: str, timeout: int = 300) -> int:
    _log_append(f"$ (user) {cmd}")
    rc, out, err = ssh_exec(ssh, f"bash -lc \"{cmd}\"", timeout=timeout)
    if out: _log_append(out.rstrip())
    if err: _log_append("[stderr]\n" + err.rstrip())
    _log_append(f"[exit {rc}]")
    return rc

def _active_ssh():
    s = _get_active_ssh_settings()
    if not _is_configured(s):
        raise RuntimeError("SSH not configured")
    return s

def _remote_home(ssh, user: str) -> str:
    rc, out, _ = ssh_exec(ssh, f"getent passwd {user} | cut -d: -f6", timeout=8)
    return (out.strip() or f"/home/{user}")

# --------------------- cross-distro pipx discovery ---------------------

def _detect_pkg_manager(ssh) -> str | None:
    for tool, cmd in [
        ("apt",    "command -v apt-get >/dev/null 2>&1"),
        ("dnf",    "command -v dnf >/dev/null 2>&1"),
        ("pacman", "command -v pacman >/dev/null 2>&1"),
        ("zypper", "command -v zypper >/dev/null 2>&1"),
    ]:
        rc, _, _ = ssh_exec(ssh, cmd, timeout=5)
        if rc == 0:
            return tool
    return None

def _ensure_pipx_cmd(ssh, sudo_pw: str | None, user: str) -> str | None:
    # user-local pipx?
    rc, _, _ = ssh_exec(ssh, "test -x ~/.local/bin/pipx || false", timeout=5)
    if rc == 0:
        return "~/.local/bin/pipx"
    # system pipx?
    rc, _, _ = ssh_exec(ssh, "test -x /usr/bin/pipx || false", timeout=5)
    if rc == 0:
        return "/usr/bin/pipx"
    # install via package manager
    mgr = _detect_pkg_manager(ssh)
    if not mgr:
        _log_append("[stderr]\nNo known package manager found; cannot install pipx automatically.")
        return None
    _log_append(f"[*] Installing pipx via {mgr} …")
    if mgr == "apt":
        _ssh_run_logged(ssh, "DEBIAN_FRONTEND=noninteractive apt-get update -yq || true", sudo_pw, timeout=600)
        _ssh_run_logged(ssh, "DEBIAN_FRONTEND=noninteractive apt-get install -yq pipx python3-venv python3-pip || true", sudo_pw, timeout=600)
        rc, _, _ = ssh_exec(ssh, "test -x /usr/bin/pipx || false", timeout=5)
        if rc == 0: return "/usr/bin/pipx"
    elif mgr == "dnf":
        _ssh_run_logged(ssh, "dnf -y install pipx python3-pip python3-virtualenv || true", sudo_pw, timeout=600)
        rc, _, _ = ssh_exec(ssh, "command -v pipx || false", timeout=5)
        if rc == 0: return "pipx"
    elif mgr == "pacman":
        _ssh_run_logged(ssh, "pacman -Sy --noconfirm python-pipx python-pip python-virtualenv || true", sudo_pw, timeout=600)
        rc, _, _ = ssh_exec(ssh, "command -v pipx || false", timeout=5)
        if rc == 0: return "pipx"
    elif mgr == "zypper":
        _ssh_run_logged(ssh, "zypper -n install pipx python3-pip python3-virtualenv || true", sudo_pw, timeout=600)
        rc, _, _ = ssh_exec(ssh, "command -v pipx || false", timeout=5)
        if rc == 0: return "pipx"
    _log_append("[stderr]\nFailed to install pipx via package manager.")
    return None

def _ensure_glances_web_via_pipx(ssh, pipx_cmd: str) -> str | None:
    _ssh_run_user(ssh, 'export PATH="$HOME/.local/bin:$PATH"; echo $PATH', timeout=5)
    _ssh_run_user(ssh, f'{pipx_cmd} install --force "glances[web]" 2>&1 || true', timeout=1800)
    rc, out, _ = ssh_exec(ssh, "bash -lc 'readlink -f \"$(command -v glances)\" || true'", timeout=10)
    glances_bin = (out or "").strip()
    if not glances_bin:
        rc1, _, _ = ssh_exec(ssh, "test -x ~/.local/share/pipx/venvs/glances/bin/glances || false", timeout=5)
        if rc1 == 0: return "~/.local/share/pipx/venvs/glances/bin/glances"
        rc2, _, _ = ssh_exec(ssh, "test -x ~/.local/pipx/venvs/glances/bin/glances || false", timeout=5)
        if rc2 == 0: return "~/.local/pipx/venvs/glances/bin/glances"
        return None
    rc, _, _ = ssh_exec(ssh, f"test -x '{glances_bin}' || false", timeout=5)
    return glances_bin if rc == 0 else None

# --------------------- systemd unit (full file) ---------------------

def _write_base_service_unit(ssh, sudo_pw: str | None, user: str, glances_bin: str):
    unit_path = "/etc/systemd/system/glances.service"
    home = _remote_home(ssh, user)
    unit = (
        "[Unit]\\n"
        "Description=Glances (pipx web)\\n"
        "After=network-online.target\\n"
        "Wants=network-online.target\\n"
        "\\n"
        "[Service]\\n"
        "Type=simple\\n"
        f"User={user}\\n"
        f"Environment=PATH={home}/.local/bin:/usr/bin:/bin\\n"
        f"ExecStart={glances_bin} -w -B 0.0.0.0\\n"
        "Restart=on-failure\\n"
        "RestartSec=3\\n"
        "\\n"
        "[Install]\\n"
        "WantedBy=multi-user.target\\n"
    )
    _log_append("[*] Writing full /etc/systemd/system/glances.service …")
    _ssh_run_logged(ssh, f"bash -lc \"printf '{unit}' | tee {unit_path} > /dev/null\"", sudo_pw, timeout=20)

# --------------------- optional firewall ---------------------

def _open_firewall_if_needed(ssh, sudo_pw: str | None):
    _ssh_run_logged(
        ssh,
        "(command -v ufw >/dev/null 2>&1 && sudo ufw status | grep -q active && sudo ufw allow 61208/tcp) || true",
        sudo_pw,
        timeout=60
    )

# --------------------- STATUS / LOG endpoints ---------------------

@glances_bp.get("/glances/status")
def glances_status():
    try:
        s = _active_ssh()
        ssh = ssh_connect(
            host=s["pi_host"], user=s["pi_user"],
            auth=s.get("auth_method","key"),
            key_path=s.get("ssh_key_path",""),
            password=s.get("password",""), timeout=20
        )
        user = s["pi_user"]

        rc, which_out, _ = ssh_exec(ssh, f"sudo -u {user} -H bash -lc 'command -v glances || true'", timeout=8)
        which = (which_out.strip() or "")

        rc_v, _, _ = ssh_exec(ssh, f"test -x /home/{user}/.local/share/pipx/venvs/glances/bin/glances || false", timeout=5)
        is_pipx = ("/.local/bin/glances" in which) or (rc_v == 0)

        rc_r, _, _ = ssh_exec(ssh, "systemctl is-active --quiet glances || false", timeout=8)
        running = (rc_r == 0)

        rc_p, out_p, _ = ssh_exec(ssh, "ss -ltn | grep ':61208 ' || true", timeout=8)
        web_port_open = (rc_p == 0 and bool(out_p.strip()))

        _, vout, _ = ssh_exec(ssh, "glances --version 2>/dev/null | head -n1", timeout=8)
        version = (vout or "").strip()

        try: ssh.close()
        except: pass

        return jsonify({
            "ok": True,
            "installed": bool(which),
            "running": running,
            "which": which or "?",
            "is_pipx": is_pipx,
            "web_port_open": web_port_open,
            "version": version
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@glances_bp.post("/glances/clear-log")
def glances_clear_log():
    _log_reset()
    return jsonify({"ok": True})

@glances_bp.get("/glances/log")
def glances_log():
    try:
        p = _glances_log_path()
        txt = ""
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                txt = f.read()
        resp = make_response(txt, 200)
        resp.headers["Content-Type"] = "text/plain; charset=utf-8"
        resp.headers["Cache-Control"] = "no-store"
        return resp
    except Exception:
        resp = make_response("", 200)
        resp.headers["Content-Type"] = "text/plain; charset=utf-8"
        resp.headers["Cache-Control"] = "no-store"
        return resp

@glances_bp.get("/glances/log/tail")
def glances_log_tail():
    try:
        n = max(1, min(int(request.args.get("n", 400)), 5000))
    except Exception:
        n = 400
    p = _glances_log_path()
    lines = []
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            dq = deque(f, maxlen=n)
            lines = list(dq)
    resp = make_response("".join(lines), 200)
    resp.headers["Content-Type"] = "text/plain; charset=utf-8"
    resp.headers["Cache-Control"] = "no-store"
    return resp

# --------------------- INSTALL ---------------------

@glances_bp.post("/glances/install")
def glances_install():
    try:
        data = request.get_json(silent=True) or {}
        sudo_pw = data.get("sudo_pw") or None

        _log_reset()
        _log_append("== Glances install/start (WEB mode via pipx) ==")

        s = _active_ssh()
        ssh = ssh_connect(
            host=s["pi_host"], user=s["pi_user"],
            auth=s.get("auth_method","key"),
            key_path=s.get("ssh_key_path",""),
            password=s.get("password",""), timeout=30
        )
        user = s["pi_user"]

        # sudo check
        _log_append("[*] Sudo check…")
        rc_nv, _, _ = ssh_exec(ssh, "sudo -n true || false", timeout=8)
        if rc_nv != 0 and not sudo_pw:
            _log_append("[stderr]\nSudo requires a password (NOPASSWD not set).")
            try: ssh.close()
            except: pass
            return jsonify({"ok": False, "error": "Sudo needs password. Provide sudo_pw or configure NOPASSWD."}), 400
        if rc_nv != 0 and sudo_pw:
            rc_pw, _, _ = ssh_exec(ssh, f'echo "{sudo_pw}" | sudo -S -k true || false', timeout=10)
            if rc_pw != 0:
                _log_append("[stderr]\nProvided sudo password failed.")
                try: ssh.close()
                except: pass
                return jsonify({"ok": False, "error": "Invalid sudo password."}), 400

        pipx_cmd = _ensure_pipx_cmd(ssh, sudo_pw, user)
        if not pipx_cmd:
            try: ssh.close()
            except: pass
            return jsonify({"ok": False, "error": "pipx not available and could not be installed"}), 500

        glances_bin = _ensure_glances_web_via_pipx(ssh, pipx_cmd)
        if not glances_bin:
            try: ssh.close()
            except: pass
            _log_append("[stderr]\nCould not find glances binary after pipx install.")
            return jsonify({"ok": False, "error": "glances not found after pipx install"}), 500

        _write_base_service_unit(ssh, sudo_pw, user, glances_bin)
        _ssh_run_logged(ssh, "systemctl daemon-reload", sudo_pw, timeout=60)
        _ssh_run_logged(ssh, "systemctl enable glances", sudo_pw, timeout=60)
        _ssh_run_logged(ssh, "systemctl restart glances", sudo_pw, timeout=120)

        _open_firewall_if_needed(ssh, sudo_pw)

        _ssh_run_logged(
            ssh,
            "(command -v ss >/dev/null 2>&1 && ss -ltn 'sport = :61208' | tail -n +2) || "
            "(command -v nc >/dev/null 2>&1 && nc -z 127.0.0.1 61208 && echo 'nc: port open') || "
            "echo 'No listener detected yet'",
            sudo_pw,
            timeout=20
        )

        try: ssh.close()
        except Exception: pass
        _log_append("Done.")
        return jsonify({"ok": True, "output": "Glances installed/started (pipx web + systemd)"}), 200

    except Exception as e:
        _log_append(f"Install error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

# --------------------- UNINSTALL (improved) ---------------------

def _pipx_uninstall_or_manual(ssh):
    """Try pipx uninstall; if pipx missing, remove venvs and shim manually."""
    # Prefer system pipx, then user pipx, then module
    candidates = [
        "/usr/bin/pipx",
        "~/.local/bin/pipx",
        "pipx",
        "python3 -m pipx",
    ]
    for cmd in candidates:
        rc, _, _ = ssh_exec(ssh, f"bash -lc 'command -v {cmd.split()[0]} >/dev/null 2>&1'", timeout=5)
        if rc == 0:
            _ssh_run_user(ssh, f"{cmd} uninstall glances || true", timeout=180)
            break
    # Always ensure shim/venvs are gone
    _ssh_run_user(ssh, 'rm -f "$HOME/.local/bin/glances" || true', timeout=20)
    _ssh_run_user(ssh, 'rm -rf "$HOME/.local/share/pipx/venvs/glances" "$HOME/.local/pipx/venvs/glances" || true', timeout=20)

@glances_bp.post("/glances/uninstall")
def glances_uninstall():
    try:
        data = request.get_json(silent=True) or {}
        sudo_pw = data.get("sudo_pw") or None

        _log_reset()
        _log_append("== Glances uninstall ==")

        s = _active_ssh()
        ssh = ssh_connect(
            host=s["pi_host"], user=s["pi_user"],
            auth=s.get("auth_method","key"),
            key_path=s.get("ssh_key_path",""),
            password=s.get("password",""), timeout=25
        )

        # Stop/disable service and remove units (file or drop-in)
        _ssh_run_logged(ssh, "systemctl disable --now glances || true", sudo_pw, timeout=120)
        _ssh_run_logged(ssh, "rm -rf /etc/systemd/system/glances.service.d || true", sudo_pw, timeout=30)
        _ssh_run_logged(ssh, "rm -f /etc/systemd/system/glances.service || true", sudo_pw, timeout=30)
        _ssh_run_logged(ssh, "systemctl daemon-reload || true", sudo_pw, timeout=30)

        # Kill any leftover web process (manual runs etc.)
        _ssh_run_user(ssh, 'pkill -f "glances -w" || true', timeout=10)
        _ssh_run_user(ssh, 'pkill -f "uvicorn.*glances" || true', timeout=10)

        # pipx uninstall (or manual cleanup)
        _pipx_uninstall_or_manual(ssh)

        try: ssh.close()
        except: pass
        _log_append("Done.")
        return jsonify({"ok": True})
    except Exception as e:
        _log_append(f"Uninstall error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

# Back-compat alias (frontend kan kalde dette navn)
@glances_bp.post("/glances/uninstall-glances")
def glances_uninstall_compat():
    return glances_uninstall()
