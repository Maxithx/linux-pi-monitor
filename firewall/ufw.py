from typing import Any, Dict, List, Optional
from shlex import quote
from routes.common.ssh_utils import ssh_exec


class UfwManager:
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
        enabled = False
        service_active = self.distro.service_is_active('ufw') if installed else False
        policies = {}
        ssh_allowed = False
        rules = []
        if installed:
            _, stat, _ = ssh_exec(self.ssh, "ufw status verbose 2>/dev/null || true", timeout=6)
            if stat:
                enabled = ('Status: active' in stat)
                # Defaults
                for ln in stat.splitlines():
                    if ln.lower().startswith('default:'):
                        try:
                            parts = ln.split(':',1)[1]
                            segs = [s.strip() for s in parts.split(',')]
                            if len(segs) >= 2:
                                policies = {"incoming": segs[0].split(' ')[0], "outgoing": segs[1].split(' ')[0]}
                        except Exception:
                            pass
            # rules
            _, rules_txt, _ = ssh_exec(self.ssh, "ufw status numbered 2>/dev/null || true", timeout=6)
            if rules_txt:
                import re as _re
                for ln in rules_txt.splitlines():
                    ln = ln.strip()
                    m = _re.match(r"\[(\d+)\]\s+(.*)", ln)
                    if m:
                        num = int(m.group(1))
                        rest = m.group(2)
                        rules.append({"number": num, "rule": rest})
                        if 'openssh' in rest.lower() or '22/tcp' in rest.lower():
                            if 'allow' in rest.lower():
                                ssh_allowed = True

        return {
            "framework": "ufw",
            "installed": installed,
            "service_active": service_active,
            "enabled": enabled,
            "policies": policies,
            "ssh_allowed": ssh_allowed,
            "rules_numbered": rules,
        }

    def _installed(self) -> bool:
        rc, _, _ = ssh_exec(self.ssh, "command -v ufw >/dev/null 2>&1", timeout=3)
        return rc == 0

    def _has_rule(self, text: str) -> bool:
        _, rules_txt, _ = ssh_exec(self.ssh, "ufw status numbered 2>/dev/null || true", timeout=6)
        return (text.lower() in (rules_txt or '').lower())

    def apply_preset(self, app_port: int, extras: Dict[str, List[str]], sudo_pw: Optional[str]):
        log = []
        # defaults
        log.append(self._run("ufw default deny incoming", sudo_pw))
        log.append(self._run("ufw default allow outgoing", sudo_pw))
        # ensure OpenSSH
        if not self._has_rule('openssh') and not self._has_rule('22/tcp'):
            log.append(self._run("ufw allow OpenSSH", sudo_pw))
        # app port
        if app_port:
            rule = f"{int(app_port)}/tcp"
            if not self._has_rule(rule):
                log.append(self._run(f"ufw allow {rule}", sudo_pw))
        # extras
        for p in (extras.get('ports') or []):
            if not self._has_rule(p):
                log.append(self._run(f"ufw allow {p}", sudo_pw))
        for svc in (extras.get('services') or []):
            if not self._has_rule(svc):
                log.append(self._run(f"ufw allow {svc}", sudo_pw))
        return {"ok": True, "log": "\n".join([str(x) for x in log])}

    def enable(self, sudo_pw: Optional[str]):
        return self._run("ufw --force enable", sudo_pw)

    def disable(self, sudo_pw: Optional[str]):
        return self._run("ufw disable", sudo_pw)

    def allow_port(self, port: int, proto: str = 'tcp', sudo_pw: Optional[str] = None):
        return self._run(f"ufw allow {int(port)}/{quote(proto)}", sudo_pw)

    def allow_service(self, name: str, sudo_pw: Optional[str] = None):
        return self._run(f"ufw allow {quote(name)}", sudo_pw)

    def delete_rule(self, selector: Dict[str, Any], sudo_pw: Optional[str] = None):
        # UFW expects numbered delete
        num = selector.get('number')
        if not num:
            return {"ok": False, "error": "number required"}
        return self._run(f"yes | ufw delete {int(num)}", sudo_pw)

