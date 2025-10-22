from typing import Dict, Any
from shlex import quote
from routes.common.ssh_utils import ssh_exec


class DebianLikeOps:
    def __init__(self, ssh):
        self.ssh = ssh

    def is_installed(self, pkg: str) -> bool:
        rc, _, _ = ssh_exec(self.ssh, f"dpkg -s {quote(pkg)} >/dev/null 2>&1", timeout=4)
        return rc == 0

    def service_is_active(self, name: str) -> bool:
        _, out, _ = ssh_exec(self.ssh, f"systemctl is-active {quote(name)} 2>/dev/null || true", timeout=3)
        return (out or '').strip() == 'active'

    def service_enable_now(self, name: str, sudo_pw: str | None = None) -> Dict[str, Any]:
        cmd = f"systemctl enable --now {quote(name)}"
        return _sudo(self.ssh, cmd, sudo_pw)

    def service_disable_stop(self, name: str, sudo_pw: str | None = None) -> Dict[str, Any]:
        cmd = f"systemctl disable --now {quote(name)}"
        return _sudo(self.ssh, cmd, sudo_pw)


def _sudo(ssh, inner: str, sudo_pw: str | None):
    inner_q = inner.replace('"', '\\"')
    if sudo_pw:
        cmd = f'echo "{sudo_pw}" | sudo -S -p "" sh -lc "{inner_q}"'
    else:
        cmd = f'sudo -n sh -lc "{inner_q}"'
    rc, out, err = ssh_exec(ssh, cmd, timeout=30)
    return {"ok": rc == 0, "rc": rc, "stdout": out, "stderr": err}

