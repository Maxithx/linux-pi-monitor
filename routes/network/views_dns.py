from flask import jsonify, request

from . import network_bp
from .helpers import _ssh, _active
from .dns_helpers import _dns_status, _set_dns_nm, _set_dns_resolvectl


@network_bp.get("/network/dns_status")
def dns_status():
    try:
        ssh = _ssh()
        info = _dns_status(ssh)
        try:
            ssh.close()
        except Exception:
            pass
        return jsonify(info)
    except Exception as e:
        return jsonify({"error": str(e)}), 200


@network_bp.post("/network/dns/set")
def dns_set():
    try:
        data = request.get_json(force=True) or {}
        mode = (data.get("mode") or "auto").lower()
        servers = data.get("servers") or []
        # sudo password: fra UI eller fra aktiv profil
        sudo_pw = data.get("sudo_pw") or _active().get("password")

        ssh = _ssh()
        info = _dns_status(ssh)
        iface = info.get("iface", "")
        conn = info.get("connection", "")

        auto = (mode == "auto")
        logs = []
        rc_total = 0

        if conn:  # NetworkManager path
            rc, out, err = _set_dns_nm(ssh, sudo_pw, iface, conn, servers, auto)
            rc_total = rc_total or rc
            if out:
                logs.append(out)
            if err:
                logs.append(err)
        else:
            # Fallback to resolvectl (systemd-resolved)
            rc, out, err = _set_dns_resolvectl(ssh, sudo_pw, iface, servers, auto)
            rc_total = rc_total or rc
            if out:
                logs.append(out)
            if err:
                logs.append(err)

        # Return new status
        new_info = _dns_status(ssh)
        try:
            ssh.close()
        except Exception:
            pass

        return jsonify({
            "ok": rc_total == 0,
            "log": "\n".join(l for l in logs if l).strip(),
            "status": new_info,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 200

