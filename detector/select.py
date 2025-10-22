from typing import Optional

from routes.common.ssh_utils import ssh_exec
from distro.debian_like import DebianLikeOps
from firewall.ufw import UfwManager
from firewall.firewalld import FirewalldManager
from detector.os_release import read_os_release


def select_distro_ops(ssh):
    info = read_os_release(ssh)
    id_like = (info.get('ID_LIKE','') + ' ' + info.get('ID','')).lower()
    # For now we only need Debian-like ops for Mint/Ubuntu/Raspbian
    return DebianLikeOps(ssh)


def select_firewall(ssh, distro_ops) -> Optional[object]:
    # Prefer firewalld if service is active
    try:
        _, out, _ = ssh_exec(ssh, "systemctl is-active firewalld 2>/dev/null || true", timeout=3)
        if (out or '').strip() == 'active':
            return FirewalldManager(ssh, distro_ops)
    except Exception:
        pass

    # Else UFW if installed
    try:
        rc, _, _ = ssh_exec(ssh, "command -v ufw >/dev/null 2>&1", timeout=3)
        if rc == 0:
            return UfwManager(ssh, distro_ops)
    except Exception:
        pass
    return None

