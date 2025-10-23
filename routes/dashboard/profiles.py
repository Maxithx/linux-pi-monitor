from __future__ import annotations

import json
import os
from typing import Dict
from flask import current_app


def get_active_profile() -> Dict[str, str]:
    """Load the active SSH profile from app config's PROFILES_PATH JSON.

    Returns a dict with keys: pi_host, pi_user, auth_method, ssh_key_path, password.
    Missing values are returned as empty strings.
    """
    try:
        prof_path = current_app.config.get("PROFILES_PATH")
        if not prof_path or not os.path.exists(prof_path):
            return {}
        with open(prof_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        active_id = data.get("active_profile_id")
        if not active_id:
            return {}
        for p in data.get("profiles", []):
            if p.get("id") == active_id:
                return {
                    "pi_host": (p.get("pi_host") or "").strip(),
                    "pi_user": (p.get("pi_user") or "").strip(),
                    "auth_method": (p.get("auth_method") or "key").strip(),
                    "ssh_key_path": (p.get("ssh_key_path") or "").strip(),
                    "password": p.get("password") or "",
                }
    except Exception:
        pass
    return {}

