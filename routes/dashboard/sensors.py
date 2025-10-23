from __future__ import annotations

from .ssh_client import ssh_run


def get_cpu_temp() -> str:
    """Return CPU temperature in Celsius as a string, or "N/A".

    Tries lm-sensors JSON; falls back to Raspberry Pi thermal zone path.
    """
    # Try Raspberry Pi path first (fast)
    try:
        v = ssh_run("cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null")
        if v:
            return str(round(int(v.strip()) / 1000.0, 1))
    except Exception:
        pass
    # Fallback: sensors -j
    try:
        import json
        raw = ssh_run("sensors -j 2>/dev/null")
        if raw:
            obj = json.loads(raw)
            best = None
            for chip, data in obj.items():
                if not isinstance(data, dict):
                    continue
                for k, v in data.items():
                    if not isinstance(v, dict):
                        continue
                    for kk, vv in v.items():
                        if not kk.endswith("_input"):
                            continue
                        tag = f"{chip} {k}".lower()
                        if any(t in tag for t in ("core", "package", "cpu", "tdie", "tctl")):
                            try:
                                val = float(vv)
                                best = max(best, val) if best is not None else val
                            except Exception:
                                pass
            if best is not None:
                return str(round(best, 1))
    except Exception:
        pass
    return "N/A"

