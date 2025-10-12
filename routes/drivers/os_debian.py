# routes/drivers/os_debian.py
from __future__ import annotations
import re
from typing import Dict, Any

from .os_base import BaseDriver

ANSI_RE = re.compile(r"\x1B\[[0-9;]*[A-Za-z]")


def strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s or "")


class DebianDriver(BaseDriver):
    """
    Works for Raspbian (Debian Bookworm), Debian, and Ubuntu/Mint as well.
    Uses `apt-get -s dist-upgrade` (dry-run) to list upgradable packages
    in a stable, locale-independent way (using LC_ALL=C).
    """

    def stream_scan(self):
        try:
            client = self._ssh_connect_paramiko()

            # Stage 1: refresh indexes (quiet)
            yield ("status", {"stage": "apt_update"})
            _stdin, stdout, _stderr = client.exec_command(
                'sh -lc "LC_ALL=C DEBIAN_FRONTEND=noninteractive apt-get update -yq || apt update -yq"',
                get_pty=False, timeout=600
            )
            try:
                stdout.channel.recv_exit_status()
            except Exception:
                pass

            # Stage 2: streaming scan using dry-run dist-upgrade
            yield ("status", {"stage": "list_upgradable"})
            cmd = (
                'sh -lc "LC_ALL=C DEBIAN_FRONTEND=noninteractive '
                'apt-get -s -o Debug::NoLocking=1 dist-upgrade"'
            )
            _stdin2, stdout2, _stderr2 = client.exec_command(cmd, get_pty=False, timeout=900)

            pat = re.compile(
                r"^Inst\s+([^\s:]+)(?::([^\s]+))?(?:\s+\[[^\]]+\])?\s+\(([^)\s]+).*?(?:\[(.*?)\])?",
                re.IGNORECASE
            )

            count = 0
            for raw in iter(stdout2.readline, ""):
                line = strip_ansi(raw.strip())
                if not line or not line.startswith("Inst "):
                    continue
                m = pat.match(line)
                if not m:
                    continue
                name = m.group(1)
                arch_a = m.group(2) or ""
                candidate = m.group(3) or ""
                arch_b = (m.group(4) or "").strip()
                arch = arch_b or arch_a or ""
                count += 1
                yield ("pkg", {"name": name, "candidate": candidate, "arch": arch})

            yield ("done", {"count": count})

            try:
                client.close()
            except Exception:
                pass

        except Exception as e:
            yield ("error", {"message": str(e)})

    def pkg_detail(self, name: str) -> Dict[str, Any]:
        name = (name or "").strip()
        if not name:
            return {"ok": False, "error": "missing name"}

        rc2, pol, _ = self._ssh_exec_simple(f'SH -lc "LC_ALL=C apt-cache policy {name}"', timeout=60)
        if rc2 != 0 or not pol:
            rc2, pol, _ = self._ssh_exec_simple(f'sh -lc "LC_ALL=C apt-cache policy {name}"', timeout=60)

        current = ""
        candidate = ""
        suite = ""
        repo = ""

        if rc2 == 0 and pol:
            m = re.search(r"Installed:\s*([^\s]+)", pol)
            if m: current = m.group(1).strip()
            m = re.search(r"Candidate:\s*([^\s]+)", pol)
            if m: candidate = m.group(1).strip()
            m = re.search(r"\s[a-z0-9-]+://[^\s]+\s+([a-z0-9-]+)\s", pol, re.I)
            if m: suite = m.group(1).strip()
            repo = suite

        summary = ""
        cl_link = ""
        cves = []
        urgency = ""
        rc3, chlog, _ = self._ssh_exec_simple(f'sh -lc "LC_ALL=C apt-get changelog -qq {name}"', timeout=120)
        if rc3 == 0 and chlog:
            for l in chlog.splitlines():
                t = l.strip()
                if t and not t.startswith("---"):
                    summary = t
                    break
            murl = re.search(r"(https?://\S+)", chlog)
            if murl: cl_link = murl.group(1)
            cves = re.findall(r"(CVE-\d{4}-\d+)", chlog or "")
            mu = re.search(r"urgency=([a-z]+)", chlog, re.I)
            if mu: urgency = mu.group(1).lower()

        return {
            "ok": True,
            "name": name,
            "current": current,
            "candidate": candidate,
            "repo": repo,
            "suite": suite,
            "arch": "",
            "security": bool(suite.endswith("-security")) if suite else False,
            "urgency": urgency,
            "summary": summary,
            "cves": cves[:10],
            "links": {"changelog": cl_link},
        }

    def run_action(self, action: str):
        return 0, "", ""

