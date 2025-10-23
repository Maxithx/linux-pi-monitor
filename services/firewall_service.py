from typing import Any, Dict, List, Optional

from routes.common.ssh_utils import ssh_exec
from routes.network.helpers import _ssh as _connect_ssh
from detector.select import select_distro_ops, select_firewall


def _normalize_status(d: Dict[str, Any]) -> Dict[str, Any]:
    # Ensure all keys exist for the frontend
    out = {
        "framework": d.get("framework", "none"),
        "installed": bool(d.get("installed", False)),
        "service_active": bool(d.get("service_active", False)),
        "enabled": bool(d.get("enabled", False)),
        "policies": d.get("policies") or {},
        "ssh_allowed": bool(d.get("ssh_allowed", False)),
        "rules_numbered": d.get("rules_numbered") or [],
        "rules_table": d.get("rules_table") or [],
        "zones": d.get("zones") or [],
        # Hints about privilege requirements
        "needs_sudo_for_status": bool(d.get("needs_sudo_for_status", False)),
        "needs_sudo_for_rules": bool(d.get("needs_sudo_for_rules", False)),
    }
    return out


def get_status():
    try:
        ssh = _connect_ssh()
    except Exception:
        # No SSH configured; return safe payload
        return {"ok": True, **_normalize_status({})}

    try:
        distro = select_distro_ops(ssh)
        fw = select_firewall(ssh, distro)
        if fw is None:
            return {"ok": True, **_normalize_status({})}
        st = fw.status()
        return {"ok": True, **_normalize_status(st)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        try:
            ssh.close()
        except Exception:
            pass


def apply_preset(app_port: int, extras: Optional[Dict[str, List[str]]] = None, sudo_pw: Optional[str] = None):
    try:
        ssh = _connect_ssh()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    try:
        distro = select_distro_ops(ssh)
        fw = select_firewall(ssh, distro)
        if fw is None:
            return {"ok": False, "error": "No supported firewall (UFW/firewalld)"}
        res = fw.apply_preset(app_port=app_port, extras=extras or {}, sudo_pw=sudo_pw)
        st = fw.status()
        return {"ok": res.get("ok", True), "log": res.get("log", ""), "status": _normalize_status(st)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        try:
            ssh.close()
        except Exception:
            pass


def get_status_elevated(sudo_pw: Optional[str] = None):
    try:
        ssh = _connect_ssh()
    except Exception as e:
        return {"ok": False, "error": str(e)}

    try:
        distro = select_distro_ops(ssh)
        fw = select_firewall(ssh, distro)
        if fw is None:
            return {"ok": False, "error": "No supported firewall (UFW/firewalld)"}

        # Prefer manager-specific elevated status when available
        st = None
        if hasattr(fw, 'status_elevated'):
            try:
                st = fw.status_elevated(sudo_pw)
            except Exception as _:
                st = None
        if not st:
            # Fallback to normal status (may still lack rules)
            st = fw.status()
        return {"ok": True, **_normalize_status(st)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        try:
            ssh.close()
        except Exception:
            pass


def enable(sudo_pw: Optional[str] = None):
    try:
        ssh = _connect_ssh()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    try:
        distro = select_distro_ops(ssh)
        fw = select_firewall(ssh, distro)
        if fw is None:
            return {"ok": False, "error": "No supported firewall (UFW/firewalld)"}

        st = fw.status()
        # Safety: do not enable if SSH is not allowed and we are remote
        # Try to determine if we connect remotely (not perfect but useful)
        from routes.common.ssh_utils import ssh_exec_shell as _sh
        rc, who, _ = _sh(ssh, "who -m 2>/dev/null | awk '{print $NF}' | tr -d '()'", timeout=3)
        remote_hint = (who or "").strip()
        if not st.get("ssh_allowed") and remote_hint and remote_hint not in ("127.0.0.1", "::1"):
            return {"ok": False, "error": "SSH rule required to avoid lock-out"}

        res = fw.enable(sudo_pw=sudo_pw)
        st = fw.status()
        return {"ok": res.get("ok", True), "log": res.get("log", ""), "status": _normalize_status(st)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        try:
            ssh.close()
        except Exception:
            pass


def disable(sudo_pw: Optional[str] = None):
    try:
        ssh = _connect_ssh()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    try:
        distro = select_distro_ops(ssh)
        fw = select_firewall(ssh, distro)
        if fw is None:
            return {"ok": False, "error": "No supported firewall (UFW/firewalld)"}
        res = fw.disable(sudo_pw=sudo_pw)
        st = fw.status()
        return {"ok": res.get("ok", True), "log": res.get("log", ""), "status": _normalize_status(st)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        try:
            ssh.close()
        except Exception:
            pass


def delete_rule(payload: Dict[str, Any], sudo_pw: Optional[str] = None):
    try:
        ssh = _connect_ssh()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    try:
        distro = select_distro_ops(ssh)
        fw = select_firewall(ssh, distro)
        if fw is None:
            return {"ok": False, "error": "No supported firewall (UFW/firewalld)"}
        res = fw.delete_rule(payload, sudo_pw=sudo_pw)
        st = fw.status()
        return {"ok": res.get("ok", True), "log": res.get("log", ""), "status": _normalize_status(st)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        try:
            ssh.close()
        except Exception:
            pass
