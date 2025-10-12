# routes/updates.py
# Main updates blueprint using OS-specific drivers.

from __future__ import annotations
import json
import shlex
from flask import Blueprint, render_template, request, jsonify, Response, stream_with_context

from .settings import _get_active_ssh_settings, _is_configured, test_ssh_connection
from .ssh_utils import ssh_connect, ssh_exec

# Import drivers direkte (robust mod package init issues)
from .updates_drivers.driver_debian import DebianDriver
from .updates_drivers.driver_mint import MintDriver
from .updates_drivers.os_detect import choose_driver_name, fetch_os_info


updates_bp = Blueprint("updates", __name__)

# ---------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------
@updates_bp.route("/updates", endpoint="updates")
def updates():
    connection_status = "connected" if test_ssh_connection() else "disconnected"
    return render_template("update.html", connection_status=connection_status)


# ---------------------------------------------------------------------
# Helper: get driver instance based on remote OS
# ---------------------------------------------------------------------
def _get_driver():
    key = choose_driver_name()
    if key == "mint":
        return MintDriver()
    # default / debian family
    return DebianDriver()


# ---------------------------------------------------------------------
# Actions (APT/Flatpak/Snap)
# ---------------------------------------------------------------------
_ACTIONS = {
    "apt_update":        "sudo apt update",
    "apt_list":          "apt list --upgradable",
    "apt_dry_full":      "sudo apt-get -s dist-upgrade",
    "apt_upgrade":       "sudo apt upgrade -y",
    "apt_full_upgrade":  "sudo apt full-upgrade -y",
    "reboot_required":   'if [ -f /run/reboot-required ]; then echo "REBOOT_REQUIRED"; else echo "NO_REBOOT"; fi',
    "flatpak_dry":       "flatpak update --appstream && flatpak update --assumeyes --dry-run",
    "flatpak_apply":     "flatpak update -y",
    "snap_list":         "sudo snap refresh --list",
    "snap_refresh":      "sudo snap refresh",
    "docker_ps":         'docker ps --format "{{.Names}}\t{{.Image}}\t{{.Status}}" || true',
    "full_noob_update": (
        "sudo DEBIAN_FRONTEND=noninteractive apt update && "
        "sudo DEBIAN_FRONTEND=noninteractive apt full-upgrade -y && "
        "sudo apt autoremove --purge -y && "
        "sudo apt autoclean && "
        "( command -v flatpak >/dev/null 2>&1 && flatpak update -y || true ) && "
        "( command -v snap >/dev/null 2>&1 && sudo snap refresh || true ) && "
        '( test -f /run/reboot-required && echo \"REBOOT_REQUIRED\" || echo \"NO_REBOOT\" )'
    ),
}

# Handlinger hvor sudo oftest kræves
_NEED_SUDO = {"apt_update", "apt_upgrade", "apt_full_upgrade", "snap_refresh", "full_noob_update"}


def _force_english(cmd: str) -> str:
    """Prefix kommandokæden så al output bliver engelsk (ensartet UI)."""
    return f"export LANG=C LC_ALL=C; {cmd}"


def _inject_sudo_flags(cmd: str) -> str:
    """
    Tilføj ' -S -p ''' til alle 'sudo ' forekomster, så sudo læser fra stdin
    uden prompt-tekst. Simpelt string-replace er tilstrækkeligt til vores kommandoer.
    """
    return cmd.replace("sudo ", "sudo -S -p '' ")


def _wrap_with_password(cmd: str, sudo_password: str) -> str:
    """
    Giv password til HELE kommandokæden ved at pipe til en sh-wrapper.
    Det sikrer at alle sudo-kald i kæden kan læse fra stdin, og at første sudo
    populater sudo-timestamp for de næste.
    """
    # Sørg for engelske tekster og sudo -S på alle kald
    cmd = _force_english(_inject_sudo_flags(cmd))
    # /bin/sh -c '...': stdin for hele kæden er pipet fra printf
    # printf -- '%s\n' 'password'
    wrapper = f"/bin/sh -c {shlex.quote(cmd)}"
    return f"printf -- %s\\\\n {shlex.quote(sudo_password)} | {wrapper}"


@updates_bp.post("/updates/run")
def updates_run():
    try:
        data = request.get_json(force=True) or {}
        action = (data.get("action") or "").strip()
        sudo_password = data.get("sudo_password") or ""
        base_cmd = _ACTIONS.get(action)
        if not base_cmd:
            return jsonify({"ok": False, "error": f"Unknown action: {action}"}), 400

        s = _get_active_ssh_settings()
        if not _is_configured(s):
            return jsonify({"ok": False, "error": "SSH not configured"}), 400

        # Build final command
        if action in _NEED_SUDO and sudo_password:
            cmd = _wrap_with_password(base_cmd, sudo_password)
        else:
            # Ingen password medsendt -> kør som normalt (eller fejler med klar stderr)
            cmd = _force_english(base_cmd)

        ssh = ssh_connect(
            host=s["pi_host"], user=s["pi_user"],
            auth=s.get("auth_method", "key"),
            key_path=s.get("ssh_key_path", ""),
            password=s.get("password", ""), timeout=20
        )
        rc, out, err = ssh_exec(ssh, cmd, timeout=180)
        try:
            ssh.close()
        except Exception:
            pass

        # Mask password i output hvis det af en eller anden grund dukkede op
        if sudo_password:
            if out: out = out.replace(sudo_password, "******")
            if err: err = err.replace(sudo_password, "******")

        return jsonify({"ok": True, "rc": rc, "stdout": out, "stderr": err})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ---------------------------------------------------------------------
# OS info for UI ("Connected user@host — OS")
# ---------------------------------------------------------------------
@updates_bp.get("/updates/os")
def updates_os_info():
    try:
        info = fetch_os_info()
        return jsonify({"ok": True, **info})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------
# Non-stream list (compat)
# ---------------------------------------------------------------------
@updates_bp.get("/updates/list")
def updates_list():
    try:
        drv = _get_driver()
        updates = []
        total = 0
        for evt, payload in drv.stream_scan():
            if evt == "pkg":
                updates.append({
                    "name": payload.get("name", ""),
                    "current": "",
                    "candidate": payload.get("candidate", ""),
                    "repo": "",
                    "security": False,
                    "summary": "",
                    "cves": [],
                    "links": {"changelog": ""}
                })
            elif evt == "done":
                total = payload.get("count", len(updates))
        return jsonify({"ok": True, "count": total, "updates": updates})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------
# Streaming scan (SSE)
# ---------------------------------------------------------------------
def _sse_event(name: str, obj) -> str:
    return f"event: {name}\ndata: {json.dumps(obj, ensure_ascii=False)}\n\n"


@updates_bp.get("/updates/scan/stream")
def updates_scan_stream():
    def _gen():
        try:
            drv = _get_driver()
            for evt, payload in drv.stream_scan():
                yield _sse_event(evt, payload)
        except Exception as e:
            yield _sse_event("error", {"message": str(e)})

    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return Response(stream_with_context(_gen()), headers=headers)


# ---------------------------------------------------------------------
# Per-package details
# ---------------------------------------------------------------------
@updates_bp.get("/updates/pkg/<name>")
def updates_pkg_detail(name: str):
    try:
        drv = _get_driver()
        data = drv.pkg_detail(name)
        status = 200 if data.get("ok") else 500
        return jsonify(data), status
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
