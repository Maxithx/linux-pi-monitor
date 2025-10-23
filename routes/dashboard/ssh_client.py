from __future__ import annotations

from typing import Optional
import logging


def ssh_run(cmd: str) -> str:
    """Run a command on the active host using the app's SSH manager.

    This delegates to utils.ssh_run to keep one connection pool in the app.
    Always returns a string (may be empty on error).
    """
    try:
        from utils import ssh_run as _ssh_run  # lazy import avoids cycles
    except Exception:  # pragma: no cover
        logging.getLogger(__name__).warning("utils.ssh_run not available")
        return ""
    try:
        out = _ssh_run(cmd)
        return out or ""
    except Exception as e:  # pragma: no cover
        logging.getLogger(__name__).warning("ssh_run error: %s", e)
        return ""

