from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import re
import time

import requests
from flask import current_app

try:
    from .profiles import get_active_profile
except Exception:  # pragma: no cover
    get_active_profile = None  # type: ignore

_API_PREFIX: Optional[str] = None
_API_CANDIDATES = ('/api/4', '/api/3')
_NUMERIC_RE = re.compile(r'[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?')
_NET_COUNTERS: Dict[str, Dict[str, float]] = {}
_PREFIX_FACTORS = {
    '': 1.0,
    'k': 1024.0,
    'm': 1024.0 ** 2,
    'g': 1024.0 ** 3,
    't': 1024.0 ** 4,
    'ki': 1024.0,
    'mi': 1024.0 ** 2,
    'gi': 1024.0 ** 3,
    'ti': 1024.0 ** 4,
}


def glances_base_url() -> Optional[str]:
    """Return http://host:61208 base URL for the active profile."""
    host = ''
    try:
        settings = (current_app.config.get("SSH_SETTINGS") or {}).copy()
    except Exception:
        settings = {}
    host = (settings.get("pi_host") or '').strip()
    if not host and callable(get_active_profile):
        try:
            prof = get_active_profile() or {}
            host = (prof.get("pi_host") or '').strip()
        except Exception:
            host = ''
    return f"http://{host}:61208" if host else None


def _candidate_prefixes() -> Tuple[str, ...]:
    prefixes = []
    if _API_PREFIX:
        prefixes.append(_API_PREFIX)
    prefixes.extend(p for p in _API_CANDIDATES if p != _API_PREFIX)
    return tuple(prefixes)


def fetch_glances_json(endpoint: str, timeout: float = 1.5) -> Optional[Any]:
    """Fetch JSON from Glances, trying multiple API versions."""
    base = glances_base_url()
    if not base:
        return None
    path = endpoint.strip('/')
    last_error = None
    for prefix in _candidate_prefixes():
        url = f"{base.rstrip('/')}{prefix}/{path}"
        try:
            res = requests.get(url, timeout=timeout)
            if res.status_code == 404:
                continue  # wrong API version, try next
            if res.status_code != 200:
                last_error = f"HTTP {res.status_code}"
                continue
            data = res.json()
            global _API_PREFIX
            _API_PREFIX = prefix
            return data
        except Exception as exc:  # pragma: no cover
            last_error = str(exc)
            try:
                current_app.logger.debug("Glances fetch failed for %s: %s", url, exc)
            except Exception:
                pass
    if last_error:
        try:
            current_app.logger.debug("Glances endpoint %s failed: %s", endpoint, last_error)
        except Exception:
            pass
    return None


def _bytes_to_mb(value: Optional[float]) -> int:
    try:
        return int(round(float(value or 0) / (1024 * 1024)))
    except Exception:
        return 0


def _human_bytes(value: Optional[float]) -> str:
    try:
        num = float(value)
    except Exception:
        return '?'
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    idx = 0
    while num >= 1024 and idx < len(units) - 1:
        num /= 1024.0
        idx += 1
    return f"{num:.0f} {units[idx]}" if idx <= 1 else f"{num:.1f} {units[idx]}"


def _coerce_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return None
    text = str(value).strip().replace(',', '.')
    if not text:
        return None
    match = _NUMERIC_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except Exception:
        return None


def _unit_hint(raw: Any) -> Tuple[str, bool]:
    """Return (prefix, is_bit) inferred from the raw textual value."""
    if not isinstance(raw, str):
        return '', False
    match = re.search(r'([kKmMgGtT]?i?)([bB])', raw)
    if not match:
        return '', False
    prefix = (match.group(1) or '').lower()
    is_bit = match.group(2).islower()
    return prefix, is_bit


def _to_kbytes_per_sec(value: float, raw: Any) -> float:
    prefix, is_bit = _unit_hint(raw)
    factor = _PREFIX_FACTORS.get(prefix, 1.0)
    bytes_per_sec = value * factor
    if is_bit:
        bytes_per_sec /= 8.0
    return bytes_per_sec / 1024.0


def _direct_rate_kbps(sample: Dict[str, Any], direction: str) -> Optional[float]:
    keys = (
        direction,
        f"{direction}_rate",
        f"{direction}_per_sec",
        f"{direction}_per_second",
        f"{direction}ps",
        f"{direction}_ps",
    )
    for key in keys:
        raw = sample.get(key)
        val = _coerce_float(raw)
        if val is not None:
            return _to_kbytes_per_sec(val, raw)
    return None


def _counter_rate_kbps(sample: Dict[str, Any], direction: str, iface: str) -> Optional[float]:
    counter_keys = (
        'bytes_recv' if direction == 'rx' else 'bytes_sent',
        f"{direction}_total",
        f"{direction}_cum",
        f"total_{direction}",
    )
    now = time.time()
    store = _NET_COUNTERS.setdefault(iface, {})
    ts_key = f"{direction}_ts"
    val_key = f"{direction}_value"
    value = None
    for key in counter_keys:
        value = _coerce_float(sample.get(key))
        if value is not None:
            break
    if value is None:
        return None
    prev_val = store.get(val_key)
    prev_ts = store.get(ts_key)
    store[val_key] = value
    store[ts_key] = now
    if prev_val is None or prev_ts is None:
        return None
    dt = max(now - prev_ts, 1e-6)
    diff = value - prev_val
    if diff < 0:
        diff = 0.0
    return diff / dt / 1024.0


def _network_rate_kbps(sample: Dict[str, Any], direction: str) -> Optional[float]:
    iface = sample.get('interface_name') or sample.get('name') or '?'
    direct = _direct_rate_kbps(sample, direction)
    history = _counter_rate_kbps(sample, direction, iface)
    if direct is None:
        return history
    if direct <= 0 and history not in (None, 0.0):
        return history
    return direct


def fetch_glances_metrics() -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Return a best-effort snapshot for CPU/MEM/Disk/Network from Glances."""
    if not glances_base_url():
        return None, "No Glances host configured"

    snapshot: Dict[str, Any] = {}
    last_error: Optional[str] = None

    cpu = fetch_glances_json('cpu')
    if isinstance(cpu, dict):
        try:
            if 'total' in cpu:
                snapshot['cpu'] = round(float(cpu['total']), 1)
        except Exception:
            pass
    elif cpu is None:
        last_error = "Glances CPU API unreachable"

    mem = fetch_glances_json('mem')
    if isinstance(mem, dict):
        try:
            snapshot['ram'] = round(float(mem.get('percent', 0.0)), 1)
        except Exception:
            snapshot['ram'] = None
        snapshot['ram_total_mb'] = _bytes_to_mb(mem.get('total'))
        snapshot['ram_free_mb'] = _bytes_to_mb(mem.get('free'))
    elif mem is None and last_error is None:
        last_error = "Glances memory API unreachable"

    fs_list = fetch_glances_json('fs')
    if isinstance(fs_list, list):
        root = next((item for item in fs_list if item.get('mnt_point') == '/'), None)
        if not root and fs_list:
            root = fs_list[0]
        if isinstance(root, dict):
            try:
                snapshot['disk'] = round(float(root.get('percent', 0.0)), 1)
            except Exception:
                snapshot['disk'] = None
            snapshot['disk_total'] = _human_bytes(root.get('size'))
            snapshot['disk_used'] = _human_bytes(root.get('used'))
            snapshot['disk_free'] = _human_bytes(root.get('free'))
    elif fs_list is None and last_error is None:
        last_error = "Glances filesystem API unreachable"

    net_list = fetch_glances_json('network')
    if isinstance(net_list, list):
        best_iface = None
        best_rx = best_tx = 0.0
        best_total = -1.0
        for sample in net_list:
            if not isinstance(sample, dict):
                continue
            iface = (sample.get('interface_name') or sample.get('name') or '').strip()
            if not iface or iface == 'lo':
                continue
            rx = _network_rate_kbps(sample, 'rx')
            tx = _network_rate_kbps(sample, 'tx')
            if rx is None and tx is None:
                continue
            rx = rx or 0.0
            tx = tx or 0.0
            ttl = rx + tx
            if ttl > best_total:
                best_total = ttl
                best_iface = iface
                best_rx = rx
                best_tx = tx
        if best_iface is not None:
            snapshot['network'] = round(best_rx + best_tx, 1)
            snapshot['net_rx'] = round(best_rx, 1)
            snapshot['net_tx'] = round(best_tx, 1)
            snapshot['net_iface'] = best_iface
    elif net_list is None and last_error is None:
        last_error = "Glances network API unreachable"

    if not snapshot:
        return None, last_error or "Glances API unreachable"
    return snapshot, None

