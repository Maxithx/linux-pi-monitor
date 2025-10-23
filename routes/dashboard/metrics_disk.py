from __future__ import annotations

from typing import Tuple
import re
from .ssh_client import ssh_run


def parse_disk_df() -> Tuple[float, str, str, str]:
    """Return (used_percent, total, used, free) using df -h / output."""
    txt = ssh_run("df -h /") or ""
    for line in txt.splitlines():
        if "/" in line and "%" in line:
            parts = line.split()
            if len(parts) >= 5:
                try:
                    used_pct = int(parts[4].replace('%', ''))
                except Exception:
                    used_pct = 0
                return float(used_pct), parts[1], parts[2], parts[3]
    return 0.0, "?", "?", "?"


def get_disk_hardware_info() -> Tuple[str, str, str]:
    """Return (model, device, temperature_str) with safe fallbacks.

    Reads the root mount source, resolves block device, and attempts SMART temp.
    If smartctl is missing or access is denied, returns "N/A".
    """
    # Where is root mounted from?
    src = (ssh_run("findmnt -no SOURCE /") or '').strip()
    if not src:
        return "?", "?", "N/A"
    # Resolve parent device name (e.g., sda from sda1)
    pkname = (ssh_run(f"lsblk -no PKNAME {src} 2>/dev/null") or '').strip()
    if not pkname:
        import os
        base = os.path.basename(src)
        if base.startswith("nvme") and "p" in base:
            pkname = base.split("p")[0]
        else:
            pkname = re.sub(r"\d+$", "", base)
    model = (ssh_run(f"lsblk -dno MODEL /dev/{pkname} 2>/dev/null") or '').strip() or "?"

    # SMART temperature (best-effort)
    smart = "/usr/sbin/smartctl"
    has = (ssh_run(f"test -x {smart} && echo yes || echo no") or '').strip() == 'yes'
    temp = "N/A"
    if has:
        out = ssh_run(f"sudo -n {smart} -A /dev/{pkname} 2>/dev/null || {smart} -A /dev/{pkname} 2>/dev/null")
        if out:
            m = re.search(r"(?:Temperature|Composite):\s*([0-9]+)\s*C", out)
            if m:
                temp = m.group(1)
            else:
                # Try ATA attribute parsing
                m2 = re.search(r"^\s*\d+\s+Temperature_Celsius\b.*?(\d+)\s*(?:\(|$)", out, re.MULTILINE)
                if m2:
                    temp = m2.group(1)

    return model or "?", pkname or "?", temp

