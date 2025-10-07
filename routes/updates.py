# routes/updates.py
import re
from flask import Blueprint, render_template, request, jsonify
from .ssh_utils import ssh_connect, ssh_exec
from .settings import _get_active_ssh_settings, _is_configured, test_ssh_connection

updates_bp = Blueprint("updates", __name__)

@updates_bp.route("/updates", endpoint="updates")
def updates():
    connection_status = "connected" if test_ssh_connection() else "disconnected"
    return render_template("update.html", connection_status=connection_status)

def _active_ssh():
    s = _get_active_ssh_settings()
    if not _is_configured(s):
        raise RuntimeError("SSH not configured")
    return s

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

@updates_bp.post("/updates/run")
def updates_run():
    try:
        data = request.get_json(force=True) or {}
        action = (data.get("action") or "").strip()
        cmd = _ACTIONS.get(action)
        if not cmd:
            return jsonify({"ok": False, "error": f"Unknown action: {action}"}), 400

        s = _active_ssh()
        ssh = ssh_connect(
            host=s["pi_host"], user=s["pi_user"],
            auth=s.get("auth_method","key"),
            key_path=s.get("ssh_key_path",""),
            password=s.get("password",""), timeout=20
        )
        rc, out, err = ssh_exec(ssh, cmd, timeout=180)
        try: ssh.close()
        except: pass

        return jsonify({"ok": True, "rc": rc, "stdout": out, "stderr": err})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@updates_bp.get("/updates/list")
def updates_list():
    try:
        s = _active_ssh()
        ssh = ssh_connect(
            host=s["pi_host"], user=s["pi_user"],
            auth=s.get("auth_method","key"),
            key_path=s.get("ssh_key_path",""),
            password=s.get("password",""), timeout=20
        )

        # 1) Fresh lists
        ssh_exec(ssh, "sudo apt update", timeout=180)

        # 2) Upgradable list
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
            name = line.split("/", 1)[0]
            parts = line.split()
            candidate = None
            for p in parts:
                if any(ch.isdigit() for ch in p) and not p.endswith(",now"):
                    candidate = p; break
            m = re.search(r"\[(?:.*?:|.*?fra:)\s*([^\]]+)\]", line)
            current = m.group(1).strip() if m else ""

            rc2, pol, _ = ssh_exec(ssh, f"apt-cache policy {name}", timeout=60)
            repo = ""
            if rc2 == 0 and pol:
                mcand = re.search(r"Candidate:\s*([^\s]+)", pol)
                if mcand: candidate = mcand.group(1).strip()
                mcurr = re.search(r"Installed:\s*([^\s]+)", pol)
                if mcurr and (not current or current == "(none)"):
                    current = mcurr.group(1).strip()
                msuite = re.search(r"\s[a-z0-9-]+://[^\s]+\s+([a-z0-9-]+)\s", pol, re.I)
                if msuite: repo = msuite.group(1).strip()

            security = repo.endswith("-security") if repo else False

            summary = ""; cl_link = ""; cves = []
            rc3, chlog, _ = ssh_exec(ssh, f"apt-get changelog -qq {name}", timeout=90)
            if rc3 == 0 and chlog:
                for l in chlog.splitlines():
                    t = l.strip()
                    if t and not t.startswith("---"):
                        summary = t; break
                murl = re.search(r"(https?://\S+)", chlog)
                if murl: cl_link = murl.group(1)
                cves = re.findall(r"(CVE-\d{4}-\d+)", chlog or "")

            pkgs.append({
                "name": name,
                "current": current,
                "candidate": candidate or "",
                "repo": repo,
                "security": bool(security),
                "summary": summary,
                "cves": cves[:6],
                "links": {"changelog": cl_link}
            })

        try: ssh.close()
        except: pass

        return jsonify({"ok": True, "updates": pkgs})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
