from typing import Any, Dict, List, Optional
from shlex import quote
from routes.common.ssh_utils import ssh_exec, ssh_exec_shell


class FirewalldManager:
    def __init__(self, ssh, distro_ops):
        self.ssh = ssh
        self.distro = distro_ops

    def _run(self, cmd: str, sudo_pw: Optional[str] = None):
        inner_q = cmd.replace('"', '\\"')
        if sudo_pw:
            full = f'echo "{sudo_pw}" | sudo -S -p "" sh -lc "{inner_q}"'
        else:
            full = f'sudo -n sh -lc "{inner_q}"'
        rc, out, err = ssh_exec(self.ssh, full, timeout=40)
        return {"ok": rc == 0, "rc": rc, "stdout": out, "stderr": err}

    def status(self) -> Dict[str, Any]:
        installed = self._installed()
        service_active = self.distro.service_is_active('firewalld') if installed else False
        enabled = False
        zones = []
        if installed:
            _, state, _ = ssh_exec_shell(self.ssh, "firewall-cmd --state 2>/dev/null || true", timeout=3)
            enabled = (state or '').strip() == 'running'
            # zones (simple)
            _, z, _ = ssh_exec_shell(self.ssh, "firewall-cmd --get-active-zones 2>/dev/null || true", timeout=4)
            if z:
                lines = z.splitlines()
                i=0
                while i < len(lines):
                    name = lines[i].strip()
                    if not name:
                        i += 1; continue
                    if i+1 < len(lines) and lines[i+1].strip().startswith('interfaces:'):
                        ifs = lines[i+1].split(':',1)[1].strip().split()
                        zones.append({"zone": name, "interfaces": ifs, "services": [], "ports": []})
                        i += 2
                    else:
                        zones.append({"zone": name, "interfaces": [], "services": [], "ports": []})
                        i += 1
        return {
            "framework": "firewalld",
            "installed": installed,
            "service_active": service_active,
            "enabled": enabled,
            "zones": zones,
            "ssh_allowed": True,  # assume; refine later by parsing --list-all
            "policies": {},
            "rules_numbered": [],
        }

    def _installed(self) -> bool:
        rc, _, _ = ssh_exec(self.ssh, "command -v firewall-cmd >/dev/null 2>&1", timeout=3)
        return rc == 0

    def apply_preset(self, app_port: int, extras: Dict[str, List[str]], sudo_pw: Optional[str]):
        log = []
        log.append(self._run("firewall-cmd --set-default-zone=public", sudo_pw))
        log.append(self._run("firewall-cmd --add-service=ssh --permanent", sudo_pw))
        if app_port:
            log.append(self._run(f"firewall-cmd --add-port={int(app_port)}/tcp --permanent", sudo_pw))
        for p in (extras.get('ports') or []):
            log.append(self._run(f"firewall-cmd --add-port={quote(p)} --permanent", sudo_pw))
        for svc in (extras.get('services') or []):
            log.append(self._run(f"firewall-cmd --add-service={quote(svc)} --permanent", sudo_pw))
        log.append(self._run("firewall-cmd --reload", sudo_pw))
        return {"ok": True, "log": "\n".join([str(x) for x in log])}

    def enable(self, sudo_pw: Optional[str]):
        return self.distro.service_enable_now('firewalld', sudo_pw)

    def disable(self, sudo_pw: Optional[str]):
        return self.distro.service_disable_stop('firewalld', sudo_pw)

    def allow_port(self, port: int, proto: str = 'tcp', sudo_pw: Optional[str] = None):
        return self._run(f"firewall-cmd --add-port={int(port)}/{quote(proto)} --permanent && firewall-cmd --reload", sudo_pw)

    def allow_service(self, name: str, sudo_pw: Optional[str] = None):
        return self._run(f"firewall-cmd --add-service={quote(name)} --permanent && firewall-cmd --reload", sudo_pw)

    def delete_rule(self, selector: Dict[str, Any], sudo_pw: Optional[str] = None):
        # Accept port like "8080/tcp" or a service name
        if selector.get('port'):
            return self._run(f"firewall-cmd --remove-port={quote(selector['port'])} --permanent && firewall-cmd --reload", sudo_pw)
        if selector.get('service'):
            return self._run(f"firewall-cmd --remove-service={quote(selector['service'])} --permanent && firewall-cmd --reload", sudo_pw)
        return {"ok": False, "error": "port or service required"}
