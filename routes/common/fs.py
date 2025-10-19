from __future__ import annotations
import os
from typing import List, Dict


LOG_SUBDIR = os.path.join('var', 'log', 'linux-pi-monitor', 'updates')
FALLBACK_SUBDIR = os.path.join('instance', 'update_logs')


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def get_logs_dir() -> str:
    """
    Return a writable directory for update logs.
    Prefer var/log/linux-pi-monitor/updates, fallback to instance/update_logs.
    """
    primary = LOG_SUBDIR
    try:
        _ensure_dir(primary)
        testfile = os.path.join(primary, '.w')
        with open(testfile, 'w', encoding='utf-8') as f:
            f.write('1')
        os.remove(testfile)
        return primary
    except Exception:
        fb = FALLBACK_SUBDIR
        _ensure_dir(fb)
        return fb


def make_log_path(run_id: str) -> str:
    base = get_logs_dir()
    safe = ''.join(c for c in (run_id or '') if c.isalnum() or c in ('-', '_', 'T', 'Z', '.'))
    return os.path.join(base, f"{safe}.log")


def list_logs() -> List[Dict]:
    base = get_logs_dir()
    items: List[Dict] = []
    try:
        for name in os.listdir(base):
            if not name.endswith('.log'):
                continue
            path = os.path.join(base, name)
            try:
                st = os.stat(path)
                run_id = name[:-4]
                # started is best-effort from name prefix like 2025-10-12T00-41-03Z_xxx
                started = ''
                if 'T' in run_id and 'Z' in run_id:
                    ts = run_id.split('_', 1)[0]
                    started = ts.replace('-', ':', 2).replace('T', 'T').replace('-', ':', 2).replace('::', ':')
                items.append({
                    'id': run_id,
                    'size': int(st.st_size),
                    'started': started,
                    'mtime': int(st.st_mtime),
                })
            except Exception:
                continue
    except Exception:
        pass
    items.sort(key=lambda x: x.get('mtime') or 0, reverse=True)
    return items


def read_log(run_id: str) -> str:
    path = make_log_path(run_id)
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        return f.read()


def delete_log(run_id: str) -> bool:
    path = make_log_path(run_id)
    try:
        os.remove(path)
        return True
    except Exception:
        return False


def append_log(run_id: str, text: str) -> None:
    path = make_log_path(run_id)
    _ensure_dir(os.path.dirname(path))
    with open(path, 'a', encoding='utf-8') as f:
        f.write(text)

