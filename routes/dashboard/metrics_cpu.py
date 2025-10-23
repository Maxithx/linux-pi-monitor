from __future__ import annotations

from typing import Optional, Tuple, Dict
import json

from .ssh_client import ssh_run

# Sticky last-good CPU value to avoid 0% spikes on transient sampling errors
_LAST_GOOD_CPU = 0.1


# ---- CPU model / freq -------------------------------------------------------

def _clean_cpu_name(raw: str) -> str:
    import re
    if not raw:
        return ""
    name = re.sub(r"\s*@\s*[\d\.]+\s*([GM]Hz)?\s*$", "", raw.strip())
    return re.sub(r"\s+", " ", name).strip()


def parse_cpu_info() -> Tuple[str, str, str]:
    """Return (name, cores, freq_line) using remote lscpu when possible."""
    js = ssh_run("LC_ALL=C lscpu -J 2>/dev/null")
    try:
        if js:
            obj = json.loads(js)
            fields = {e.get("field", "").strip(): e.get("data", "").strip() for e in obj.get("lscpu", [])}
            name = _clean_cpu_name(fields.get("Model name:") or fields.get("Model name") or "") or "Unknown CPU"
            cores = (fields.get("CPU(s):") or "").strip()
            cur_mhz = (fields.get("CPU MHz:") or "").strip()
            max_mhz = (fields.get("CPU max MHz:") or fields.get("CPU max MHz") or "").strip()
            min_mhz = (fields.get("CPU min MHz:") or fields.get("CPU min MHz") or "").strip()
            try:
                cur = float(str(cur_mhz).strip())
                freq_line = f"{int(round(cur))} MHz"
            except Exception:
                try:
                    mx = float(str(max_mhz).strip())
                    freq_line = f"{int(round(mx))} MHz"
                except Exception:
                    freq_line = ""
            return name, cores, freq_line
    except Exception:
        pass

    # Fallbacks via plain lscpu/grep
    name = _clean_cpu_name(ssh_run("LC_ALL=C lscpu | grep -m1 'Model name' | cut -d: -f2- | awk '{$1=$1}1'")) or "Unknown CPU"
    cores = ssh_run("nproc").strip()
    freq_line = ssh_run("LC_ALL=C lscpu | grep -m1 'CPU max MHz' | awk -F: '{print $2}'").strip()
    try:
        mx = float(freq_line)
        freq_line = f"{int(round(mx))} MHz"
    except Exception:
        pass
    return name, cores, freq_line


def get_cpu_freq_info() -> Dict:
    """Return dynamic CPU frequency info: current MHz, max MHz, per-core list."""
    try:
        from utils import get_cpu_freq_info as _g
        return _g()
    except Exception:
        return {"current_mhz": 0, "max_mhz": 0, "per_core": []}


# ---- CPU usage (Glances parity) --------------------------------------------

def _cpu_usage_via_mpstat(sample_seconds: float = 1.0) -> Optional[float]:
    txt = ssh_run(f"LC_ALL=C mpstat {max(1,int(round(sample_seconds)))} 1 2>/dev/null")
    if not txt:
        return None
    avg = None
    for line in txt.splitlines():
        if line.strip().startswith("Average:"):
            avg = line
    if not avg:
        return None
    parts = avg.split()
    try:
        idle = float(parts[-1].replace(",", "."))
        return round(max(0.0, min(100.0, 100.0 - idle)), 1)
    except Exception:
        return None


def _cpu_usage_via_procstat(sample_seconds: float = 0.5) -> Optional[float]:
    # Use single command: cat; sleep; cat
    txt = ssh_run(f"cat /proc/stat; sleep {sample_seconds}; cat /proc/stat")
    if not txt:
        return None
    lines = [ln for ln in txt.splitlines() if ln.startswith('cpu ')]
    if len(lines) < 2:
        return None
    def parse(line: str):
        parts = line.split()
        nums = [int(x) for x in parts[1:11] if x.isdigit() or x.strip("-").isdigit()]
        return nums + [0]* (10 - len(nums))
    a = parse(lines[0])
    b = parse(lines[1])
    tot0, tot1 = sum(a), sum(b)
    if tot1 <= tot0:
        return None
    idle0 = a[3] + a[4]
    idle1 = b[3] + b[4]
    u = (1.0 - (idle1 - idle0) / (tot1 - tot0)) * 100.0
    return round(max(0.0, min(100.0, u)), 1)


def _cpu_usage_via_top() -> Optional[float]:
    line = ssh_run("LC_ALL=C top -bn1 | grep -m1 'Cpu(s)'")
    if not line:
        return None
    import re
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*%?\s*id", line)
    if not m:
        return None
    try:
        idle = float(m.group(1).replace(",", "."))
        return round(max(0.0, min(100.0, 100.0 - idle)), 1)
    except Exception:
        return None


def get_cpu_usage() -> float:
    global _LAST_GOOD_CPU
    # Prefer mpstat (1s) for accuracy; then faster /proc/stat (~0.25s); then top
    for fn, arg in ((
        (_cpu_usage_via_mpstat, 1.0),
        (_cpu_usage_via_procstat, 0.25),
        (_cpu_usage_via_top, None),
    )):
        try:
            v = fn(arg) if arg is not None else fn()  # type: ignore[arg-type]
        except TypeError:
            v = fn()  # type: ignore[misc]
        if v is not None:
            # store and floor to avoid showing an exact 0% during idle
            v = max(0.1, min(100.0, float(v)))
            _LAST_GOOD_CPU = v
            return v
    # All failed: return last good (or small floor)
    return max(0.1, float(_LAST_GOOD_CPU or 0.1))
