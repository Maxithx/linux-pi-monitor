from __future__ import annotations

from typing import Tuple
from .ssh_client import ssh_run


def parse_mem_free() -> Tuple[float, int, int]:
    """Return (used_percent, total_mb, free_mb) using `free -m` output.

    Mirrors existing project behavior.
    """
    txt = ssh_run("free -m") or ""
    for line in txt.splitlines():
        if line.lower().startswith("mem:"):
            parts = line.split()
            if len(parts) >= 7:
                total = int(parts[1])
                used = int(parts[2])
                free = int(parts[6])
                if total > 0:
                    return round(used/total*100.0, 1), total, free
    return 0.0, 0, 0

