# routes/glances.py — Compat shim (proxy fjernet; brug direkte iframe til Glances)
from __future__ import annotations

from typing import Optional, Tuple

from flask import (
    Blueprint,
    jsonify,
    redirect,
    request,
    session,
)

from . import profiles_data  # profile store helpers

# Vi beholder url_prefix, så gamle links ikke 404'er, men blueprint-navnet er nyt
glances_bp = Blueprint("glances_compat_bp", __name__, url_prefix="/glances-proxy")


# --------------------------- Profil helpers ---------------------------
def _profile_id_from_request() -> Optional[str]:
    pid = (request.args.get("profile_id") or "").strip()
    if pid:
        return pid
    body = request.get_json(silent=True) or {}
    pid = (body.get("profile_id") or "").strip()
    return pid or None


def _resolve_profile(store_session: bool = True) -> Tuple[Optional[dict], Optional[str], Optional[dict]]:
    """
    Returner (profile, host, store). Host er prof['pi_host'] trimmed eller None.
    """
    data = profiles_data._ensure_store()
    pid = (
        _profile_id_from_request()
        or (session.get("active_profile_id") or "")
        or (data.get("active_profile_id") or "")
        or (data.get("default_profile_id") or "")
    )
    prof = profiles_data._find(data, pid) if pid else None
    if not prof and data.get("default_profile_id"):
        prof = profiles_data._find(data, data["default_profile_id"])
    host = (prof.get("pi_host") or "").strip() if prof else None

    if store_session:
        if pid:
            session["active_profile_id"] = pid
        if host:
            session["profile_host"] = host
        else:
            session.pop("profile_host", None)

    return prof, host, data


def _glances_root_url() -> Tuple[Optional[str], Optional[str]]:
    """
    Byg direkte URL til Glances på det valgte host. Returner (url, host).
    """
    _, host, _ = _resolve_profile(store_session=True)
    if not host:
        return None, None
    return f"http://{host}:61208/", host


# --------------------------- Routes (compat) ---------------------------
@glances_bp.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
@glances_bp.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
def glances_compat(path: str):
    """
    Compat-endpoint. Proxyen er droppet.
    - For browser-navigation (HTML) laver vi 302 redirect til Glances' root.
    - For XHR/JSON svarer vi med en venlig fejl og giver den rigtige URL tilbage.
    """
    url, host = _glances_root_url()
    if not host:
        # Ingen profil / host valgt
        if _wants_json():
            return _json_error("No host selected. Open /settings and choose a profile."), 400
        return "No host selected. Please choose a profile in Settings.", 400

    # Hvis det ligner et script/css/json/fetch-kald, så forklar at proxy'en er fjernet
    if _wants_json() or _is_asset_request(path):
        return _json_error(
            "Glances proxy was removed. Load Glances directly in an iframe.",
            glances_url=url
        ), 410  # Gone

    # Ellers redirect (typisk hvis nogen manuelt besøger /glances-proxy/)
    resp = redirect(url, code=302)
    resp.headers["Cache-Control"] = "no-store"
    return resp


# --------------------------- Helpers ---------------------------
_ASSET_EXTS = (".js", ".css", ".map", ".woff", ".woff2", ".ttf", ".eot", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico")


def _is_asset_request(path: str) -> bool:
    low = (path or "").lower()
    return low.endswith(_ASSET_EXTS) or low.startswith("api/") or low.startswith("static/")


def _wants_json() -> bool:
    # Heuristik: XHR/fetch/JSON-accept
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True
    accept = (request.headers.get("Accept") or "").lower()
    if "application/json" in accept:
        return True
    # De fleste script/css-kald har */* eller text/*
    return False


def _json_error(msg: str, **extra):
    payload = {"ok": False, "error": msg}
    if extra:
        payload.update(extra)
    resp = jsonify(payload)
    resp.headers["Cache-Control"] = "no-store"
    return resp
