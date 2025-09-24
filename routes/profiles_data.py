# data/profiles_data.py
import os, re, json, uuid, time
from typing import Optional, List, Tuple
from flask import current_app

def _profiles_path() -> str:
    path = current_app.config.get("PROFILES_PATH")
    if not path:
        raise RuntimeError("PROFILES_PATH not set on app.config")
    return path

def _ensure_store() -> dict:
    """Hent eller initier json-strukturen på disken."""
    path = _profiles_path()
    if not os.path.exists(path):
        data = {"profiles": [], "active_profile_id": None, "default_profile_id": None}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return data
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _write_store(data: dict) -> None:
    with open(_profiles_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def _find(data: dict, pid: str) -> Optional[dict]:
    for p in data.get("profiles", []):
        if p.get("id") == pid:
            return p
    return None

def _active_profile(data: dict) -> Optional[dict]:
    pid = data.get("active_profile_id")
    return _find(data, pid) if pid else None

def _sync_active_into_legacy_config(prof: dict | None) -> None:
    """Hold bagudkompatible kodeveje i live (læser SSH_SETTINGS fra aktiv profil)."""
    if not prof:
        current_app.config["SSH_SETTINGS"] = {}
        return
    current_app.config["SSH_SETTINGS"] = {
        "pi_host": prof.get("pi_host", ""),
        "pi_user": prof.get("pi_user", ""),
        "auth_method": prof.get("auth_method", "key"),
        "ssh_key_path": prof.get("ssh_key_path", ""),
        "password": prof.get("password", "")
    }

def _expand_user_home(path: str) -> str:
    # Gør "~" og %USERPROFILE%/HOME portable
    return os.path.expandvars(os.path.expanduser(path))

def _default_key_path_for_profile(prof: dict) -> str:
    """Standardsti til ny nøgle: ~/.ssh/id_rsa_<profil-id8> (stabilt og sikkert filnavn)."""
    home_ssh = os.path.join(_expand_user_home("~"), ".ssh")
    os.makedirs(home_ssh, exist_ok=True)
    stem = f"id_rsa_{prof.get('id','')[:8] or 'profile'}"
    return os.path.join(home_ssh, stem)

def _safe_stem_from_profile(prof: dict) -> str:
    """Brug profilens navn, ellers id8, og lav en sikker fil-stem."""
    name = (prof.get("name") or "").strip()
    if name:
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    else:
        stem = f"profile_{(prof.get('id','')[:8] or '00000000')}"
    return stem

def _profile_from_request_or_active(request) -> Tuple[dict, dict]:
    """Return (data, profile) – profil kan være aktiv hvis ikke angivet i body."""
    data = _ensure_store()
    body = request.get_json(silent=True) or {}
    pid = (body.get("id") or "").strip()
    prof = _find(data, pid) if pid else _active_profile(data)
    if not prof:
        raise RuntimeError("Profile not found")
    return data, prof

def create_new_profile(name: str) -> dict:
    data = _ensure_store()
    pid = str(uuid.uuid4())
    prof = {
        "id": pid,
        "name": name,
        "pi_host": "",
        "pi_user": "",
        "auth_method": "key",
        "ssh_key_path": "",
        "password": ""
    }
    data.setdefault("profiles", []).append(prof)
    if not data.get("active_profile_id"):
        data["active_profile_id"] = pid
    if not data.get("default_profile_id"):
        data["default_profile_id"] = pid
    _write_store(data)
    if data.get("active_profile_id") == pid:
        _sync_active_into_legacy_config(prof)
        current_app.config["UPDATER_RELOAD_HINT"] = time.time()
    return prof

def save_existing_profile(pid: str, body: dict) -> Optional[dict]:
    data = _ensure_store()
    prof = _find(data, pid)
    if not prof:
        return None

    def _maybe_set(key, transform=lambda x: x):
        if key in body:
            val = body.get(key)
            if key == "name":
                val = (val or "").strip()
                if not val:
                    raise ValueError("Name cannot be empty")
            prof[key] = transform(val)

    try:
        _maybe_set("name")
        _maybe_set("pi_host", lambda v: (v or "").strip())
        _maybe_set("pi_user", lambda v: (v or "").strip())
        _maybe_set("auth_method", lambda v: (v or "key").strip())
        _maybe_set("ssh_key_path", lambda v: _expand_user_home((v or "").strip()))
        _maybe_set("password", lambda v: v or "")
    except ValueError as e:
        return e

    if body.get("make_active") is True:
        data["active_profile_id"] = pid
    _write_store(data)

    if data.get("active_profile_id") == pid:
        _sync_active_into_legacy_config(prof)
        current_app.config["UPDATER_RELOAD_HINT"] = time.time()
    return prof

def delete_profile_by_id(pid: str) -> bool:
    data = _ensure_store()
    profs = data.get("profiles", [])
    profs_before = len(profs)
    profs = [p for p in profs if p.get("id") != pid]
    profs_after = len(profs)
    if profs_before == profs_after:
        return False
    
    data["profiles"] = profs
    changed_active = False
    if data.get("active_profile_id") == pid:
        data["active_profile_id"] = profs[0]["id"] if profs else None
        changed_active = True
    if data.get("default_profile_id") == pid:
        data["default_profile_id"] = profs[0]["id"] if profs else None

    _write_store(data)

    new_active = _find(data, data.get("active_profile_id"))
    _sync_active_into_legacy_config(new_active)

    if changed_active:
        current_app.config["UPDATER_RELOAD_HINT"] = time.time()
    return True

def set_active_profile(pid: str) -> Optional[dict]:
    data = _ensure_store()
    prof = _find(data, pid)
    if not prof:
        return None
    data["active_profile_id"] = pid
    _write_store(data)
    _sync_active_into_legacy_config(prof)
    current_app.config["UPDATER_RELOAD_HINT"] = time.time()
    return prof

def set_default_profile(pid: str) -> bool:
    data = _ensure_store()
    if not _find(data, pid):
        return False
    data["default_profile_id"] = pid
    _write_store(data)
    return True

def get_all_profiles() -> dict:
    data = _ensure_store()
    return {
        "profiles": data.get("profiles", []),
        "active_profile_id": data.get("active_profile_id"),
        "default_profile_id": data.get("default_profile_id"),
    }