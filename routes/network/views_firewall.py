from flask import jsonify

from . import network_bp
from .helpers import _ssh
from routes.common.ssh_utils import ssh_exec


def _detect_framework(ssh):
    """Detect firewall framework with safe, minimal logic.
    - firewalld only when service is active
    - else UFW if binary exists (service may be inactive)
    - else none
    """
    try:
        _, out, _ = ssh_exec(ssh, "systemctl is-active firewalld 2>/dev/null || true", timeout=3)
        if (out or "").strip() == "active":
            return "firewalld"
    except Exception:
        pass
    try:
        rc, _, _ = ssh_exec(ssh, "command -v ufw >/dev/null 2>&1", timeout=3)
        if rc == 0:
            return "ufw"
    except Exception:
        pass
    return "none"


def _status_firewalld(ssh):
    # Enabled state
    _, state, _ = ssh_exec(ssh, "firewall-cmd --state 2>/dev/null || true", timeout=3)
    enabled = (state or "").strip() == "running"
    # Active zones (format: zone on one line, "  interfaces: ..." on the next line)
    zones = []
    _, zones_out, _ = ssh_exec(ssh, "firewall-cmd --get-active-zones 2>/dev/null || true", timeout=4)
    if zones_out:
        lines = zones_out.splitlines()
        i = 0
        while i < len(lines):
            name = lines[i].strip()
            if not name:
                i += 1; continue
            if i+1 < len(lines) and lines[i+1].strip().startswith('interfaces:'):
                ifaces = lines[i+1].split(':',1)[1].strip().split()
                zones.append({"zone": name, "interfaces": ifaces, "services": [], "ports": []})
                i += 2
            else:
                zones.append({"zone": name, "interfaces": [], "services": [], "ports": []})
                i += 1

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
    except Exception:
        # No SSH configured or unreachable – still return a friendly payload
        return jsonify({"ok": True, "framework": "none", "enabled": False})

    fw = "none"
    try:
        fw = _detect_framework(ssh)
    except Exception:
        fw = "none"

    data = {"framework": fw, "enabled": False}
    try:
        if fw == "firewalld":
            data = _status_firewalld(ssh)
        elif fw == "ufw":
            data = _status_ufw(ssh)
    except Exception:
        # keep default data
        data = {"framework": fw, "enabled": False}

    try:
        ssh.close()
    except Exception:
        pass

    return jsonify({"ok": True, **data})
