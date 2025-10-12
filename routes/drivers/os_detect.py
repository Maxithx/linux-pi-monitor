# routes/drivers/os_detect.py
from __future__ import annotations
import re
from typing import Tuple, Dict

from routes.common.ssh_utils import ssh_connect, ssh_exec
from routes.settings import _get_active_ssh_settings, _is_configured


def _active_settings() -> dict:
    s = _get_active_ssh_settings()
    if not _is_configured(s):
        raise RuntimeError("SSH not configured")
    return s


def _read_os_release_text() -> str:
    s = _active_settings()
    ssh = ssh_connect(
        host=s["pi_host"], user=s["pi_user"],
        auth=s.get("auth_method", "key"),
        key_path=s.get("ssh_key_path", ""),
        password=s.get("password", ""), timeout=20
    )
    rc, out, _ = ssh_exec(ssh, 'sh -lc "cat /etc/os-release 2>/dev/null"', timeout=10)
    try:
        ssh.close()
    except Exception:
        pass
    return out or ""


def fetch_os_release() -> Tuple[str, str, str, str]:
    data = _read_os_release_text()

    def _get(key: str) -> str:
        m = re.search(rf"^{key}=(.+)$", data, re.MULTILINE)
        if not m:
            return ""
        raw = m.group(1).strip().strip('"').strip("'")
        return raw

    return _get("ID"), _get("ID_LIKE"), _get("NAME"), _get("VERSION_CODENAME")


def fetch_os_info() -> Dict[str, str]:
    data = _read_os_release_text()

    def _get(key: str) -> str:
        m = re.search(rf"^{key}=(.+)$", data, re.MULTILINE)
        if not m:
            return ""
        raw = m.group(1).strip().strip('"').strip("'")
        return raw

    info = {
        "id": _get("ID"),
        "id_like": _get("ID_LIKE"),
        "name": _get("NAME"),
        "version": _get("VERSION"),
        "codename": _get("VERSION_CODENAME"),
        "pretty": _get("PRETTY_NAME") or "",
    }

    if not info["pretty"]:
        pieces = [p for p in [info["name"], info["version"]] if p]
        if info["codename"]:
            pieces.append(f"({info['codename']})")
        info["pretty"] = " ".join(pieces)

    return info


def choose_driver_name() -> str:
    os_id, id_like, name, codename = fetch_os_release()
    low_all = " ".join([os_id, id_like, name, codename]).lower()

    if "raspbian" in low_all or "debian" in low_all:
        return "debian"
    if "linuxmint" in low_all or "mint" in low_all:
        return "mint"
    if "ubuntu" in low_all:
        return "debian"
    return "debian"

