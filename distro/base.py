from typing import Dict, Any


class IDistroOps:
    def __init__(self, ssh):
        self.ssh = ssh

    def is_installed(self, pkg: str) -> bool:
        raise NotImplementedError

    def service_is_active(self, name: str) -> bool:
        raise NotImplementedError

    def service_enable_now(self, name: str, sudo_pw: str | None = None) -> Dict[str, Any]:
        raise NotImplementedError

    def service_disable_stop(self, name: str, sudo_pw: str | None = None) -> Dict[str, Any]:
        raise NotImplementedError

