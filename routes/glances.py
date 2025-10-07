# routes/glances.py
from __future__ import annotations

import os
import shlex
import threading
import time
from typing import Optional, Tuple, Any

from flask import (
    Blueprint,
    jsonify,
    current_app,
    request,
    stream_with_context,
    Response,
    session,
)

from . import profiles_data, ssh_utils
import requests
import json

glances_bp = Blueprint("glances_bp", __name__, url_prefix="/glances")

LOG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "glances_install.log"))

_install_lock = threading.RLock()
_install_thread: threading.Thread | None = None


# --------------------------- Logging ---------------------------
def _append_log(line: str) -> None:
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line.rstrip() + "\n")
    except Exception as e:
        current_app.logger.error("glances.log write error: %s", e)


def _reset_log() -> None:
    try:
        if os.path.exists(LOG_PATH):
            os.remove(LOG_PATH)
    except Exception:
        pass


# --------------------------- Profil helpers ---------------------------
def _profile_id_from_request() -> Optional[str]:
    pid = (request.args.get("profile_id") or "").strip()
    if pid:
        return pid
    body = request.get_json(silent=True) or {}
    pid = (body.get("profile_id") or "").strip()
    if pid:
        return pid
    return None


def _resolve_profile(store_session: bool = True) -> Tuple[Optional[dict], Optional[str], Optional[dict]]:
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


def _require_host() -> Optional[str]:
    _, host, _ = _resolve_profile(store_session=True)
    return host


# --------------------------- SSH helpers ---------------------------
def _ssh_run(cmd: str, host: str | None = None, timeout: int = 20) -> str:
    prof, resolved_host, _ = _resolve_profile(store_session=True)
    host = host or resolved_host
    if not host or not prof:
        return ""
    user = (prof.get("pi_user") or "").strip()
    auth = (prof.get("auth_method") or "key").strip()
    keyp = (prof.get("ssh_key_path") or "").strip()
    pw = prof.get("password") or ""
    ssh = ssh_utils.ssh_connect(host, user, auth, keyp, pw, prefer_password=False, timeout=10)
    rc, out, err = ssh_utils.ssh_exec(ssh, cmd, timeout=timeout)
    try:
        ssh.close()
    except Exception:
        pass
    return out


# --------------------------- Fjern-kommando helpers ---------------------------
def _remote_has(cmd_check: str, host: Optional[str] = None) -> bool:
    host = host or session.get("profile_host") or _require_host()
    if not host:
        return False
    out = _ssh_run(f"sh -lc '{cmd_check} >/dev/null 2>&1 && echo yes || echo no'", host=host).strip()
    return out == "yes"


def _listening_on_61208(host: Optional[str] = None) -> bool:
    host = host or session.get("profile_host") or _require_host()
    if not host:
        return False
    chk = _ssh_run(
        "ss -tlnp 2>/dev/null | grep -E 'LISTEN.+:61208\\b' "
        "|| netstat -tlnp 2>/dev/null | grep ':61208\\b'",
        host=host,
    )
    return bool(chk.strip())


def _curl_ok_localhost(host: Optional[str] = None) -> bool:
    host = host or session.get("profile_host") or _require_host()
    if not host:
        return False
    out = _ssh_run("curl -fsS --max-time 2 http://127.0.0.1:61208/ | head -n1", host=host)
    low = out.lower()
    return "<!doctype html>" in low or "<html" in low


def _pipx_cmd(host: Optional[str] = None) -> Optional[str]:
    host = host or session.get("profile_host") or _require_host()
    if not host:
        return None
    for candidate in ["pipx", "python3 -m pipx", "~/.local/bin/pipx"]:
        head = candidate.split()[0]
        if _remote_has(f"command -v {head}", host=host):
            return candidate
    return None


def _glances_bin(host: Optional[str] = None) -> Optional[str]:
    host = host or session.get("profile_host") or _require_host()
    if not host:
        return None
    for candidate in ["~/.local/bin/glances", "glances"]:
        if _remote_has(f"command -v {candidate}", host=host):
            return candidate
    return None


def _which_glances(host: Optional[str] = None) -> str:
    host = host or session.get("profile_host") or _require_host()
    if not host:
        return "?"
    return (
        _ssh_run("command -v ~/.local/bin/glances 2>/dev/null || command -v glances 2>/dev/null", host=host).strip()
        or "?"
    )


def _sudo_run(cmd: str, sudo_pw: Optional[str], host: Optional[str] = None) -> str:
    host = host or session.get("profile_host") or _require_host()
    if not host:
        return "No host selected"
    if sudo_pw:
        safe_pw = shlex.quote(sudo_pw)
        return _ssh_run(f"printf %s\\n {safe_pw} | sudo -S sh -lc {shlex.quote(cmd)} 2>&1", host=host)
    else:
        return _ssh_run(f"sudo -n sh -lc {shlex.quote(cmd)} 2>&1", host=host)


def _start_glances_background(bind: str = "0.0.0.0", port: int = 61208, host: Optional[str] = None) -> None:
    host = host or session.get("profile_host") or _require_host()
    if not host:
        _append_log("[-] Intet host valgt.")
    else:
        chosen = _glances_bin(host)
        if not chosen:
            _append_log("[-] Kunne ikke finde glances-bin efter installation.")
            return
        real = _ssh_run(f"readlink -f {shlex.quote(chosen)} 2>/dev/null || echo {chosen}", host=host).strip()
        _append_log(f"[+] Starter Glances web: {real} -w --bind {bind} --port {port}")
        _ssh_run(f"nohup {chosen} -w --bind {bind} --port {port} >/dev/null 2>&1 & echo $!", host=host)


def _pipx_repair_and_install(pipx: str, host: Optional[str] = None) -> None:
    host = host or session.get("profile_host") or _require_host()
    if not host:
        return
    out = _ssh_run(f"{pipx} install --force 'glances[web]' 2>&1", host=host)
    if out.strip():
        _append_log(out.strip())

    broken = ("Traceback (most recent call last)" in out) or (
        "No such file or directory" in out and "/pipx/venvs/glances/bin/python" in out
    )
    if broken:
        _append_log("[!] Opdagede korrupt pipx-venv for glances – rydder op og prøver igen...")
        cleanup = (
            f"{pipx} uninstall glances 2>/dev/null || true; "
            "rm -rf ~/.local/share/pipx/venvs/glances ~/.local/share/pipx/apps/glances "
            "~/.local/bin/glances 2>/dev/null || true"
        )
        _append_log(_ssh_run(cleanup, host=host) or "")
        out2 = _ssh_run(f"{pipx} install 'glances[web]' 2>&1", host=host)
        if out2.strip():
            _append_log(out2.strip())

    _ssh_run("~/.local/bin/pipx ensurepath >/dev/null 2>&1 || true", host=host)


def _install_glances_worker(sudo_pw: Optional[str] = None) -> None:
    _reset_log()
    _append_log("[*] Starter Glances-installation...")

    _, host, _ = _resolve_profile(store_session=True)
    if not host:
        _append_log("[-] Intet host valgt.")
        return

    _append_log("[*] Forsøger systempakker via apt...]")
    upd = _sudo_run("DEBIAN_FRONTEND=noninteractive apt-get update || true", sudo_pw, host)
    if upd.strip():
        _append_log(upd.strip())
    inst = _sudo_run(
        "DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "
        "python3-psutil python3-pip pipx lm-sensors python3-bottle glances || true",
        sudo_pw,
        host,
    )
    if inst.strip():
        _append_log(inst.strip())

    _append_log("[*] Sikrer pipx/pip findes (user install)...")
    pipx = _pipx_cmd(host)
    if not pipx:
        _append_log("[i] pipx ikke fundet – forsøger at installere til bruger...")
        _append_log(_ssh_run("python3 -m pip install --user -U pipx 2>&1", host=host) or "")
        pipx = _pipx_cmd(host)

    if pipx:
        _append_log("[*] Installerer Glances via pipx (glances[web])...")
        _pipx_repair_and_install(pipx, host)
    else:
        _append_log("[-] pipx stadig ikke tilgængelig – falder tilbage til pip --user.")
        _append_log(_ssh_run("python3 -m pip install --user -U 'glances[web]' 2>&1", host=host) or "")

    ver = _ssh_run("~/.local/bin/glances --version 2>/dev/null || glances --version 2>/dev/null", host=host).strip()
    if ver:
        _append_log("[+] Glances installeret: " + ver)
    else:
        _append_log("[-] Kunne ikke bekræfte glances-version.")
    _append_log("Binary: " + _which_glances(host))

    _start_glances_background(bind="0.0.0.0", port=61208, host=host)

    for _ in range(10):
        time.sleep(0.5)
        if _listening_on_61208(host) and _curl_ok_localhost(host):
            break

    if not _listening_on_61208(host) or not _curl_ok_localhost(host):
        _append_log("[-] Port 61208 lytter ikke med komplet web UI.")
        _append_log("    Tjek at ~/.local/bin/glances kører (ikke /usr/bin/glances).")
    else:
        _append_log("[+] Glances web lytter og svarer på 127.0.0.1:61208/")

    ufw_state = _sudo_run("ufw status 2>/dev/null | grep -i active || true", sudo_pw, host)
    if ufw_state.strip():
        opened = _sudo_run("ufw allow 61208/tcp && ufw reload || true", sudo_pw, host)
        _append_log(opened.strip() or "[UFW: rule added/reloaded]")
    else:
        _append_log("[i] UFW ikke aktiv eller ikke tilgængelig. Hvis Glances ikke kan nås, kør: sudo ufw allow 61208/tcp")

    _append_log("[✓] Færdig. Åbn 'Live System (Glances)' eller http://<host>:61208/")


# --------------------------- API ---------------------------
@glances_bp.route("/install", methods=["POST"])
def install_glances():
    global _install_thread
    sudo_pw = (request.get_json(silent=True) or {}).get("sudo_pw")
    _resolve_profile(store_session=True)
    with _install_lock:
        if _install_thread and _install_thread.is_alive():
            return jsonify(ok=True, already_running=True)
        _install_thread = threading.Thread(target=_install_glances_worker, kwargs={"sudo_pw": sudo_pw}, daemon=True)
        _install_thread.start()
    return jsonify(ok=True, started=True)


@glances_bp.route("/status", methods=["GET"])
def status():
    _, host, _ = _resolve_profile(store_session=True)
    if not host:
        return jsonify(ok=True, installed=False, running=False, which="?")
    installed = (_remote_has("command -v ~/.local/bin/glances", host) or _remote_has("command -v glances", host))
    running = _listening_on_61208(host)
    which = _which_glances(host)
    return jsonify(ok=True, installed=installed, running=running, which=which)


@glances_bp.route("/log", methods=["GET"])
def view_log():
    try:
        if os.path.exists(LOG_PATH):
            with open(LOG_PATH, "r", encoding="utf-8") as f:
                return current_app.response_class(f.read(), mimetype="text/plain; charset=utf-8")
        return current_app.response_class("", mimetype="text/plain; charset=utf-8")
    except Exception as e:
        return current_app.response_class(f"[log read error] {e}", mimetype="text/plain; charset=utf-8")


@glances_bp.route("/clear-log", methods=["POST"])
def clear_log():
    _reset_log()
    return jsonify(ok=True)


# --------------------------- Reverse proxy (+ JSON sanitizer) ---------------------------
_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-encoding",
    "content-length",
}

def _filtered_headers(src_headers) -> dict:
    return {k: v for k, v in src_headers.items() if k.lower() not in _HOP_BY_HOP}


_FORCE_LIST_KEYS = {"stats", "containers", "views"}

def _sanitize_json(obj: Any) -> Any:
    """
    Rekursiv sanitizer:
    - Tvinger værdier for nøgler i _FORCE_LIST_KEYS til at være lister ( [] hvis ikke-liste ).
    - Bevarer alt andet urørt (rekursivt).
    """
    if isinstance(obj, dict):
        new = {}
        for k, v in obj.items():
            lk = k.lower()
            if lk in _FORCE_LIST_KEYS:
                if isinstance(v, list):
                    new[k] = [_sanitize_json(x) for x in v]
                else:
                    # Når upstream sender et objekt eller null her, giv UI en tom liste
                    new[k] = []
            else:
                new[k] = _sanitize_json(v)
        return new
    if isinstance(obj, list):
        return [_sanitize_json(x) for x in obj]
    return obj


@glances_bp.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
@glances_bp.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
def glances_proxy(path: str):
    _, glances_host, _ = _resolve_profile(store_session=True)
    if not glances_host:
        return "No host selected. Please choose a profile.", 400

    glances_port = 61208
    low = (path or "").lower().lstrip("/")
    is_api_json = low.startswith("api/3/")

    # 🔧 Mikropatch: alle containere-endpoints -> tom liste
    if is_api_json and (low.startswith("api/3/containers") or low.startswith("api/3/docker")):
        return Response("[]", mimetype="application/json", status=200)

    full_url = f"http://{glances_host}:{glances_port}/{path}"
    try:
        req_resp = requests.request(
            request.method,
            full_url,
            stream=not is_api_json,  # for JSON læser vi hele svaret for at kunne sanitere
            data=(request.get_data() if request.method in ("POST", "PUT", "PATCH") else None),
            headers=_filtered_headers(request.headers),
            params=request.args,
            timeout=10,
        )

        # JSON: parse -> sanitize -> return
        if is_api_json and req_resp.status_code == 200:
            try:
                payload = req_resp.json()
            except Exception:
                payload = None

            if payload is not None:
                fixed = _sanitize_json(payload)
                resp = Response(json.dumps(fixed), mimetype="application/json", status=200)
                resp.headers["Cache-Control"] = "no-store"
                return resp

        # Fallback: stream “as is”
        headers = [(k, v) for k, v in req_resp.headers.items() if k.lower() not in _HOP_BY_HOP]
        resp = Response(
            stream_with_context(req_resp.iter_content(chunk_size=1024)),
            headers=headers,
            status=req_resp.status_code,
            content_type=req_resp.headers.get("Content-Type"),
        )
        if "html" in (req_resp.headers.get("Content-Type") or "").lower():
            resp.headers["Cache-Control"] = "no-store"
        return resp

    except requests.exceptions.RequestException as e:
        return f"Error: Could not connect to Glances web server at {glances_host}:{glances_port}. {e}", 503
