from typing import Any, Dict, List, Optional
from shlex import quote
from routes.common.ssh_utils import ssh_exec, ssh_exec_shell
import re


class UfwManager:
    def __init__(self, ssh, distro_ops):
        self.ssh = ssh
        self.distro = distro_ops

    # ---------------- helpers ----------------
    def _run(self, cmd: str, sudo_pw: Optional[str] = None):
        """Run with sudo if password provided, otherwise sudo -n (non-interactive)."""
        inner_q = cmd.replace('"', '\\"')
        if sudo_pw:
            full = f'echo "{sudo_pw}" | sudo -S -p "" sh -lc "{inner_q}"'
        else:
            # prefer non-interactive sudo first; command itself may not need sudo
            full = f'sudo -n sh -lc "{inner_q}" || sh -lc "{inner_q}"'
        rc, out, err = ssh_exec(self.ssh, full, timeout=40)
        return {"ok": rc == 0, "rc": rc, "stdout": out or "", "stderr": err or ""}

    def _sh(self, cmd: str):
        """Plain shell (no sudo). Returns (rc, out, err)."""
        rc, out, err = ssh_exec_shell(self.ssh, cmd, timeout=8)
        return rc, (out or ""), (err or "")

    def _installed(self) -> bool:
        # cover /usr/sbin/ufw and PATH-less environments
        rc, _, _ = self._sh(
            "command -v ufw >/dev/null 2>&1 || [ -x /usr/sbin/ufw ] || [ -x /sbin/ufw ] || ufw --version >/dev/null 2>&1 || /usr/sbin/ufw --version >/dev/null 2>&1"
        )
        return rc == 0

    def _has_rule(self, text: str) -> bool:
        _, rules_txt, _ = self._sh("LANG=C ufw status numbered 2>/dev/null || true")
        return (text.lower() in rules_txt.lower())

    @staticmethod
    def _parse_policies(text: str) -> Dict[str, str]:
        """
        From `ufw status verbose`:
          Default: deny (incoming), allow (outgoing), deny (routed)
        """
        m = re.search(
            r"Default:\s*([^,]+)\s*\(incoming\)\s*,\s*([^,]+)\s*\(outgoing\)\s*,\s*([^)]+)\s*\(routed\)",
            text, re.I)
        if not m:
            return {}
        return {
            "incoming": m.group(1).strip(),
            "outgoing": m.group(2).strip(),
            "routed":   m.group(3).strip(),
        }

    @staticmethod
    def _parse_rules_table(text: str) -> List[Dict[str, str]]:
        """
        Parse the human-readable table from `ufw status`.
        """
        rules: List[Dict[str, str]] = []
        lines = text.splitlines()
        in_tbl = False
        for raw in lines:
            s = raw.rstrip()
            if not in_tbl:
                if re.search(r"^\s*To\s+Action\s+From\s*$", s):
                    in_tbl = True
                continue
            if not s.strip():
                break
            if set(s.strip()) == {"-"}:
                # skip dashed separator lines
                continue
            m = re.match(r"^(.+?)\s{2,}(\S+)\s{2,}(.+)$", s)
            if m:
                to_v = m.group(1).strip()
                act_v = m.group(2).strip()
                frm_v = m.group(3).strip()
                rules.append({"to": to_v, "action": act_v, "from": frm_v})
        return rules

    @staticmethod
    def _from_numbered_to_table(lines: List[str]) -> List[Dict[str, str]]:
        """
        Build a table from `ufw status numbered` lines like:
          [ 1] 22/tcp ALLOW Anywhere
        """
        out: List[Dict[str, str]] = []
        for ln in lines:
            s = ln.strip()
            m = re.match(r"^\[\s*\d+\s*\]\s+(.+?)\s+([A-Z]+)\s+(.+)$", s)
            if m:
                out.append({"to": m.group(1), "action": m.group(2), "from": m.group(3)})
        return out

    # ---------------- public API ----------------
    def status(self) -> Dict[str, Any]:
        installed = self._installed()
        enabled = False
        service_active = self.distro.service_is_active('ufw') if installed else False
        policies: Dict[str, str] = {}
        ssh_allowed = False
        needs_sudo_for_status = False
        needs_sudo_for_rules = False

        rules_table: List[Dict[str, str]] = []
        rules_numbered: List[str] = []

        if not installed:
            return {
                "framework": "ufw",
                "installed": False,
                "service_active": False,
                "enabled": False,
                "policies": {},
                "ssh_allowed": False,
                "rules_numbered": [],
                "rules_table": [],
            }

        # 1) status verbose (policies + enabled)
        rc_v, out_v, _ = self._sh("LANG=C ufw status verbose 2>/dev/null || true")
        if out_v:
            enabled = bool(re.search(r"^Status:\s*active\b", out_v, re.I | re.M))
            policies = self._parse_policies(out_v)
        else:
            needs_sudo_for_status = (rc_v != 0)

        # fallback: ufw.conf if enabled missing
        if not enabled:
            _, conf_txt, _ = self._sh("cat /etc/ufw/ufw.conf 2>/dev/null || true")
            if conf_txt:
                for ln in conf_txt.splitlines():
                    if ln.startswith("ENABLED="):
                        val = ln.split("=", 1)[1].strip().strip('"').strip("'").lower()
                        enabled = val in ("yes", "true", "1")
                        break

        # fallback: /etc/default/ufw for policies
        if not policies:
            _, dflt_txt, _ = self._sh("cat /etc/default/ufw 2>/dev/null || true")
            if dflt_txt:
                def map_pol(v: str) -> str:
                    v = v.strip().strip('"').strip("'").upper()
                    return {"DROP": "deny", "REJECT": "deny", "ACCEPT": "allow"}.get(v, v.lower())
                inc = out = routed = None
                for ln in dflt_txt.splitlines():
                    ln = ln.strip()
                    if not ln or ln.startswith("#") or "=" not in ln:
                        continue
                    k, v = ln.split("=", 1)
                    k = k.strip().upper()
                    if k == "DEFAULT_INPUT_POLICY": inc = map_pol(v)
                    elif k == "DEFAULT_OUTPUT_POLICY": out = map_pol(v)
                    elif k == "DEFAULT_FORWARD_POLICY": routed = map_pol(v)
                policies = {k: v for k, v in {"incoming": inc, "outgoing": out, "routed": routed}.items() if v}

        # 2) human table
        rc_t, out_t, _ = self._sh("LANG=C ufw status 2>/dev/null || true")
        if out_t and "Status:" in out_t:
            rules_table = self._parse_rules_table(out_t)
        else:
            # try non-interactive sudo if needed
            rc_t2, out_t2, _ = self._sh("LANG=C sudo -n ufw status 2>/dev/null || true")
            if out_t2 and "Status:" in out_t2:
                rules_table = self._parse_rules_table(out_t2)
            else:
                needs_sudo_for_rules = True

        # 3) numbered (for delete + as backup to build table)
        rc_n, out_n, _ = self._sh("LANG=C ufw status numbered 2>/dev/null || true")
        if out_n:
            for ln in out_n.splitlines():
                if ln.strip().startswith("["):
                    rules_numbered.append(ln.rstrip())
                    rest = ln.lower()
                    if (("22/tcp" in rest) or ("openssh" in rest)) and ("allow" in rest):
                        ssh_allowed = True
        else:
            # try non-interactive sudo
            rc_n2, out_n2, _ = self._sh("LANG=C sudo -n ufw status numbered 2>/dev/null || true")
            if out_n2:
                for ln in out_n2.splitlines():
                    if ln.strip().startswith("["):
                        rules_numbered.append(ln.rstrip())
                        rest = ln.lower()
                        if (("22/tcp" in rest) or ("openssh" in rest)) and ("allow" in rest):
                            ssh_allowed = True
            else:
                needs_sudo_for_rules = True

        # Build table from numbered if human table empty
        if not rules_table and rules_numbered:
            rules_table = self._from_numbered_to_table(rules_numbered)

        return {
            "framework": "ufw",
            "installed": True,
            "service_active": service_active,
            "enabled": enabled,
            "policies": policies,
            "ssh_allowed": ssh_allowed,
            "rules_numbered": rules_numbered,
            "rules_table": rules_table,
            "needs_sudo_for_status": needs_sudo_for_status,
            "needs_sudo_for_rules": needs_sudo_for_rules,
        }

    def status_elevated(self, sudo_pw: Optional[str]) -> Dict[str, Any]:
        """Status using sudo (password provided). Parses policies, table and numbered.
        Does not expose the password; uses _run helper to execute.
        """
        installed = self._installed()
        service_active = self.distro.service_is_active('ufw') if installed else False
        enabled = False
        policies: Dict[str, str] = {}
        rules_table: List[Dict[str, str]] = []
        rules_numbered: List[str] = []
        ssh_allowed = False

        if installed:
            # status verbose
            res_v = self._run("LANG=C ufw status verbose || true", sudo_pw)
            out_v = (res_v or {}).get("stdout", "")
            if out_v:
                enabled = bool(re.search(r"^Status:\s*active\b", out_v, re.I | re.M))
                policies = self._parse_policies(out_v)
            # human table
            res_t = self._run("LANG=C ufw status || true", sudo_pw)
            out_t = (res_t or {}).get("stdout", "")
            if out_t:
                rules_table = self._parse_rules_table(out_t)
            # numbered
            res_n = self._run("LANG=C ufw status numbered || true", sudo_pw)
            out_n = (res_n or {}).get("stdout", "")
            if out_n:
                for ln in out_n.splitlines():
                    if ln.strip().startswith("["):
                        rules_numbered.append(ln.rstrip())
                        rest = ln.lower()
                        if (("22/tcp" in rest) or ("openssh" in rest)) and ("allow" in rest):
                            ssh_allowed = True
            # build table from numbered if empty
            if not rules_table and rules_numbered:
                rules_table = self._from_numbered_to_table(rules_numbered)

        return {
            "framework": "ufw",
            "installed": installed,
            "service_active": service_active,
            "enabled": enabled,
            "policies": policies,
            "ssh_allowed": ssh_allowed,
            "rules_numbered": rules_numbered,
            "rules_table": rules_table,
            "needs_sudo_for_status": False,
            "needs_sudo_for_rules": False,
        }

    # ---------------- actions ----------------
    def apply_preset(self, app_port: int, extras: Dict[str, List[str]], sudo_pw: Optional[str]):
        log = []
        # defaults
        log.append(self._run("ufw default deny incoming", sudo_pw))
        log.append(self._run("ufw default allow outgoing", sudo_pw))
        # ensure OpenSSH
        if not self._has_rule("openssh") and not self._has_rule("22/tcp"):
            log.append(self._run("ufw allow OpenSSH", sudo_pw))
        # app port
        if app_port:
            rule = f"{int(app_port)}/tcp"
            if not self._has_rule(rule):
                log.append(self._run(f"ufw allow {rule}", sudo_pw))
        # extras (not used pt.)
        for p in (extras.get("ports") or []):
            if not self._has_rule(p):
                log.append(self._run(f"ufw allow {p}", sudo_pw))
        for svc in (extras.get("services") or []):
            if not self._has_rule(svc):
                log.append(self._run(f"ufw allow {svc}", sudo_pw))
        return {"ok": True, "log": "\n".join([str(x) for x in log])}

    def enable(self, sudo_pw: Optional[str]):
        return self._run("ufw --force enable", sudo_pw)

    def disable(self, sudo_pw: Optional[str]):
        return self._run("ufw disable", sudo_pw)

    def allow_port(self, port: int, proto: str = "tcp", sudo_pw: Optional[str] = None):
        return self._run(f"ufw allow {int(port)}/{quote(proto)}", sudo_pw)

    def allow_service(self, name: str, sudo_pw: Optional[str] = None):
        return self._run(f"ufw allow {quote(name)}", sudo_pw)

    def delete_rule(self, selector: Dict[str, Any], sudo_pw: Optional[str] = None):
        num = selector.get("number")
        if not num:
            return {"ok": False, "error": "number required"}
        # auto-confirm deletion
        return self._run(f"yes | ufw delete {int(num)}", sudo_pw)
