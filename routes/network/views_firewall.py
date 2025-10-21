from flask import jsonify

from . import network_bp
from .helpers import _ssh
from routes.common.ssh_utils import ssh_exec


def _detect_framework(ssh):
    # Prefer firewalld when running; otherwise use UFW if present
    try:
        rc, out, _ = ssh_exec(ssh, "systemctl is-active firewalld 2>/dev/null || true", timeout=3)
        if (out or "").strip() == "active":
            return "firewalld"
    except Exception:
        pass
    try:
        rc, out, _ = ssh_exec(ssh, "command -v ufw >/dev/null 2>&1 && systemctl is-active ufw 2>/dev/null || true", timeout=3)
        # Some systems report 'active' only when enabled
        if (out or "").strip() in ("active", "activating"):
            return "ufw"
        # If ufw binary exists but service not active, still choose ufw
        rc2, _, _ = ssh_exec(ssh, "command -v ufw >/dev/null 2>&1", timeout=3)
        if rc2 == 0:
            return "ufw"
    except Exception:
        pass
    # Fallback: check for firewalld binary even if service inactive
    try:
        rc3, _, _ = ssh_exec(ssh, "command -v firewall-cmd >/dev/null 2>&1", timeout=3)
        if rc3 == 0:
            return "firewalld"
    except Exception:
        pass
    return "none"


def _status_firewalld(ssh):
    # Enabled state
    _, state, _ = ssh_exec(ssh, "firewall-cmd --state 2>/dev/null || true", timeout=3)
    enabled = (state or "").strip() == "running"
    # Active zones
    zones = []
    _, zones_out, _ = ssh_exec(ssh, "firewall-cmd --get-active-zones 2>/dev/null || true", timeout=4)
    # The format is blocks like: zoneName\n  interfaces: eth0 ...
    cur = None
    for ln in (zones_out or "").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if ln.endswith(":"):
            # interfaces: line
            if cur is not None and ln.startswith("interfaces:"):
                ifaces = ln.split(":", 1)[1].strip().split()
                cur["interfaces"] = ifaces
            continue
        if "interfaces:" in ln:
            # Some variants print on same line
            parts = ln.split()
            # ignore here; will be captured below
        else:
            # Zone name line
            if cur:
                zones.append(cur)
            cur = {"zone": ln.strip(), "interfaces": [], "services": [], "ports": []}
    if cur:
        zones.append(cur)

    # If we got no active zones, still show 'public' data if available
    if not zones:
        zones = [{"zone": "public", "interfaces": [], "services": [], "ports": []}]

    # Fill services/ports per zone
    out_zones = []
    for z in zones:
        name = z.get("zone", "public")
        _, all_txt, _ = ssh_exec(ssh, f"firewall-cmd --zone={name} --list-all 2>/dev/null || true", timeout=4)
        services = []
        ports = []
        if all_txt:
            for ln in all_txt.splitlines():
                ln = ln.strip()
                if ln.startswith("services:"):
                    services = [s for s in ln.split(":",1)[1].strip().split() if s]
                elif ln.startswith("ports:"):
                    ptxt = ln.split(":",1)[1].strip()
                    if ptxt and ptxt != "(none)":
                        for p in ptxt.split():
                            if "/" in p:
                                prt, proto = p.split("/",1)
                                ports.append({"port": prt, "proto": proto})
        out_zones.append({
            "zone": name,
            "interfaces": z.get("interfaces", []),
            "services": services,
            "ports": ports,
        })
    return {"framework": "firewalld", "enabled": enabled, "zones": out_zones}


def _status_ufw(ssh):
    # Enabled?
    _, stat, _ = ssh_exec(ssh, "ufw status verbose 2>/dev/null || true", timeout=4)
    enabled = ("Status: active" in (stat or ""))
    # Rules numbered
    _, rules_txt, _ = ssh_exec(ssh, "ufw status numbered 2>/dev/null || true", timeout=4)
    rules = []
    if rules_txt:
        import re as _re
        for ln in rules_txt.splitlines():
            ln = ln.strip()
            m = _re.match(r"\[(\d+)\]\s+(.*)", ln)
            if m:
                num = int(m.group(1))
                rest = m.group(2)
                rules.append({"number": num, "rule": rest})
    # Defaults
    defaults = {"incoming": None, "outgoing": None}
    if stat:
        for ln in stat.splitlines():
            if "Default:" in ln:
                # Example: Default: deny (incoming), allow (outgoing), disabled (routed)
                try:
                    parts = ln.split(":",1)[1].strip()
                    segs = [s.strip() for s in parts.split(",")]
                    if len(segs) >= 2:
                        defaults["incoming"] = segs[0].split(" ")[0]
                        defaults["outgoing"] = segs[1].split(" ")[0]
                except Exception:
                    pass
    return {"framework": "ufw", "enabled": enabled, "rules": rules, "defaults": defaults}


@network_bp.get("/network/firewall/status")
def firewall_status():
    try:
        ssh = _ssh()
        fw = _detect_framework(ssh)
        data = {"framework": fw, "enabled": False}
        if fw == "firewalld":
            data = _status_firewalld(ssh)
        elif fw == "ufw":
            data = _status_ufw(ssh)
        try:
            ssh.close()
        except Exception:
            pass
        return jsonify({"ok": True, **data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

