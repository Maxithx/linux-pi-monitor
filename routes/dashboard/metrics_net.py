from __future__ import annotations

from typing import Tuple
import time
from .ssh_client import ssh_run


_last_stats = {"rx": None, "tx": None, "time": None}


def parse_net_speed() -> Tuple[float, float, float, str]:
    """Return (total_kBps, rx_kBps, tx_kBps, best_iface).

    Scans /proc/net/dev for the busiest interface and computes deltas since the
    last call, matching the previous app behavior.
    """
    txt = ssh_run("cat /proc/net/dev") or ""
    best_iface, rx, tx, best_total = None, 0, 0, 0
    for line in txt.splitlines():
        if ':' in line:
            iface, rest = line.split(':', 1)
            parts = rest.split()
            if len(parts) >= 9:
                curr_rx = int(parts[0])
                curr_tx = int(parts[8])
                total = curr_rx + curr_tx
                if total > best_total:
                    best_iface, rx, tx, best_total = iface.strip(), curr_rx, curr_tx, total

    now = time.time()
    if _last_stats["rx"] is None:
        _last_stats.update({"rx": rx, "tx": tx, "time": now})
        return 0.0, 0.0, 0.0, best_iface or "?"

    dt = now - (_last_stats["time"] or now)
    drx = (rx - (_last_stats["rx"] or 0)) / dt if dt > 0 else 0
    dtx = (tx - (_last_stats["tx"] or 0)) / dt if dt > 0 else 0
    _last_stats.update({"rx": rx, "tx": tx, "time": now})
    total_kBps = round((drx + dtx) / 1024.0, 1)
    rx_kBps = round(drx / 1024.0, 1)
    tx_kBps = round(dtx / 1024.0, 1)
    return total_kBps, rx_kBps, tx_kBps, best_iface or "?"

