# routes/updates.py
# Main updates blueprint using OS-specific drivers.

from __future__ import annotations
import json
import shlex
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Any
from flask import render_template, request, jsonify, Response, stream_with_context, send_file, make_response

from routes.settings import _get_active_ssh_settings, _is_configured, test_ssh_connection
from routes.common.ssh_utils import ssh_connect, ssh_exec
from routes.common.fs import append_log, make_log_path, list_logs, read_log, delete_log

# Drivers now live under routes/drivers
from routes.drivers.os_debian import DebianDriver  # type: ignore
from routes.drivers.os_mint import MintDriver      # type: ignore
from routes.drivers.os_detect import choose_driver_name, fetch_os_info  # type: ignore

from . import updates_bp

# ---------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------
@updates_bp.route("/updates", endpoint="updates")
def updates():
    connection_status = "connected" if test_ssh_connection() else "disconnected"
    return render_template("update.html", connection_status=connection_status)


# ---------------------------------------------------------------------
# Helper: get driver instance based on remote OS
# ---------------------------------------------------------------------
def _get_driver():
    key = choose_driver_name()
    if key == "mint":
        return MintDriver()
    # default / debian family
    return DebianDriver()


# ---------------------------------------------------------------------
# Actions (APT/Flatpak/Snap)
# ---------------------------------------------------------------------
_ACTIONS = {
    "apt_update":        "sudo apt update",
    "apt_list":          "apt list --upgradable",
    "apt_dry_full":      "sudo apt-get -s dist-upgrade",
    "apt_upgrade":       "sudo apt upgrade -y",
    "apt_full_upgrade":  "sudo apt full-upgrade -y",
    "reboot_required":   'if [ -f /run/reboot-required ]; then echo "REBOOT_REQUIRED"; else echo "NO_REBOOT"; fi',
    "flatpak_dry":       "flatpak update --appstream && flatpak update --assumeyes --dry-run",
    "flatpak_apply":     "flatpak update -y",
    "snap_list":         "sudo snap refresh --list",
    "snap_refresh":      "sudo snap refresh",
    "docker_ps":         'docker ps --format "{{.Names}}\t{{.Image}}\t{{.Status}}" || true',
    "full_noob_update": (
        "sudo DEBIAN_FRONTEND=noninteractive apt update && "
        "sudo DEBIAN_FRONTEND=noninteractive apt full-upgrade -y && "
        "sudo apt autoremove --purge -y && "
        "sudo apt autoclean && "
        "( command -v flatpak >/dev/null 2>&1 && flatpak update -y || true ) && "
        "( command -v snap >/dev/null 2>&1 && sudo snap refresh || true ) && "
        '( test -f /run/reboot-required && echo \"REBOOT_REQUIRED\" || echo \"NO_REBOOT\" )'
    ),
}

# Handlinger hvor sudo oftest kræves
_NEED_SUDO = {"apt_update", "apt_upgrade", "apt_full_upgrade", "snap_refresh", "full_noob_update"}


def _force_english(cmd: str) -> str:
    """Prefix kommandokæden så al output bliver engelsk (ensartet UI)."""
    return f"export LANG=C LC_ALL=C; {cmd}"


def _inject_sudo_flags(cmd: str) -> str:
    """
    Tilføj ' -S -p ''' til alle 'sudo ' forekomster, så sudo læser fra stdin
    uden prompt-tekst. Simpelt string-replace er tilstrækkeligt til vores kommandoer.
    """
    return cmd.replace("sudo ", "sudo -S -p '' ")


def _wrap_with_password(cmd: str, sudo_password: str) -> str:
    """
    Giv password til HELE kommandokæden ved at pipe til en sh-wrapper.
    Det sikrer at alle sudo-kald i kæden kan læse fra stdin, og at første sudo
    populater sudo-timestamp for de næste.
    """
    # Sørg for engelske tekster og sudo -S på alle kald
    cmd = _force_english(_inject_sudo_flags(cmd))
    # /bin/sh -c '...': stdin for hele kæden er pipet fra printf
    # printf -- '%s\n' 'password'
    wrapper = f"/bin/sh -c {shlex.quote(cmd)}"
    return f"printf -- %s\\\\n {shlex.quote(sudo_password)} | {wrapper}"


@updates_bp.post("/updates/run_sync")
def updates_run():
    try:
        data = request.get_json(force=True) or {}
        action = (data.get("action") or "").strip()
        sudo_password = data.get("sudo_password") or ""
        base_cmd = _ACTIONS.get(action)
        if not base_cmd:
            return jsonify({"ok": False, "error": f"Unknown action: {action}"}), 400

        s = _get_active_ssh_settings()
        if not _is_configured(s):
            return jsonify({"ok": False, "error": "SSH not configured"}), 400

        # Build final command
        if action in _NEED_SUDO and sudo_password:
            cmd = _wrap_with_password(base_cmd, sudo_password)
        else:
            # Ingen password medsendt -> kør som normalt (eller fejler med klar stderr)
            cmd = _force_english(base_cmd)

        ssh = ssh_connect(
            host=s["pi_host"], user=s["pi_user"],
            auth=s.get("auth_method", "key"),
            key_path=s.get("ssh_key_path", ""),
            password=s.get("password", ""), timeout=20
        )
        rc, out, err = ssh_exec(ssh, cmd, timeout=180)
        try:
            ssh.close()
        except Exception:
            pass

        # Mask password i output hvis det af en eller anden grund dukkede op
        if sudo_password:
            if out: out = out.replace(sudo_password, "******")
            if err: err = err.replace(sudo_password, "******")

        return jsonify({"ok": True, "rc": rc, "stdout": out, "stderr": err})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ---------------------------------------------------------------------
# OS info for UI ("Connected user@host — OS")
# ---------------------------------------------------------------------
@updates_bp.get("/updates/os")
def updates_os_info():
    try:
        info = fetch_os_info()
        return jsonify({"ok": True, **info})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------
# Non-stream list (compat)
# ---------------------------------------------------------------------
@updates_bp.get("/updates/list")
def updates_list():
    try:
        drv = _get_driver()
        updates = []
        total = 0
        for evt, payload in drv.stream_scan():
            if evt == "pkg":
                updates.append({
                    "name": payload.get("name", ""),
                    "current": "",
                    "candidate": payload.get("candidate", ""),
                    "repo": "",
                    "security": False,
                    "summary": "",
                    "cves": [],
                    "links": {"changelog": ""}
                })
            elif evt == "done":
                total = payload.get("count", len(updates))
        return jsonify({"ok": True, "count": total, "updates": updates})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------
# Streaming scan (SSE)
# ---------------------------------------------------------------------
def _sse_event(name: str, obj) -> str:
    return f"event: {name}\ndata: {json.dumps(obj, ensure_ascii=False)}\n\n"


@updates_bp.get("/updates/scan/stream")
def updates_scan_stream():
    def _gen():
        try:
            drv = _get_driver()
            for evt, payload in drv.stream_scan():
                yield _sse_event(evt, payload)
        except Exception as e:
            yield _sse_event("error", {"message": str(e)})

    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return Response(stream_with_context(_gen()), headers=headers)


# ---------------------------------------------------------------------
# Per-package details
# ---------------------------------------------------------------------
@updates_bp.get("/updates/pkg/<name>")
def updates_pkg_detail(name: str):
    try:
        drv = _get_driver()
        data = drv.pkg_detail(name)
        status = 200 if data.get("ok") else 500
        return jsonify(data), status
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------
# Update runs: state, progress, logs (async)
# ---------------------------------------------------------------------
_RUNS: Dict[str, Dict[str, Any]] = {}

_RX_DOWNLOAD = re.compile(r"^Get:\d+\s+.*\s([a-z0-9\-\+\.]+)\s.*\[(\d+(?:\.\d+)?\s*(?:kB|MB))\]", re.IGNORECASE)
_RX_UNPACK = re.compile(r"^Unpacking\s+([a-z0-9\-\+\.]+)\s", re.IGNORECASE)
_RX_SETUP = re.compile(r"^Setting up\s+([a-z0-9\-\+\.]+)\s", re.IGNORECASE)
_RX_TRIGGERS = re.compile(r"^Processing triggers for\s+([a-z0-9\-\+\.]+)\s", re.IGNORECASE)

PHASE_WEIGHTS = {
    'Download': 25,
    'Unpacking': 35,
    'Setting up': 35,
    'Triggers': 5,
}


def _new_run() -> str:
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H-%M-%SZ')
    short = hex(int(time.time()*1000))[-6:]
    run_id = f"{ts}_{short}"
    _RUNS[run_id] = {
        'started_ts': time.time(),
        'ended_ts': None,
        'overall': {'percent': 0, 'phase': 'Starting'},
        'packages': {},
        'active_iface': '',
        'requires_reboot': False,
        'done': False,
        'exit_code': None,
        'error': None,
        'action': None,
    }
    append_log(run_id, f"=== Update run {run_id} started {datetime.utcnow().isoformat()}Z ===\n")
    return run_id


def _pkg_progress_entry(name: str) -> Dict[str, Any]:
    return {'name': name, 'version': '', 'phase': 'Queued', 'percent': 0}


def _recompute_overall(state: Dict[str, Any]) -> None:
    pkgs = list(state['packages'].values())
    if not pkgs:
        state['overall'] = {'percent': state['overall'].get('percent', 0), 'phase': state['overall'].get('phase', 'Idle')}
        return
    p = sum(max(0, min(100, x.get('percent', 0))) for x in pkgs) / max(1, len(pkgs))
    phase = 'Done' if p >= 100 else (state['overall'].get('phase') or 'Installing')
    state['overall'] = {'percent': int(p), 'phase': phase}


def _apply_line_to_state(state: Dict[str, Any], line: str) -> None:
    line = (line or '').rstrip('\n')
    if not line:
        return
    m = _RX_DOWNLOAD.search(line)
    if m:
        name = m.group(1)
        pkg = state['packages'].setdefault(name, _pkg_progress_entry(name))
        pkg['phase'] = 'Downloading'
        pkg['percent'] = max(int(pkg.get('percent', 0)), PHASE_WEIGHTS['Download'])
        _recompute_overall(state)
        return
    m = _RX_UNPACK.search(line)
    if m:
        name = m.group(1)
        pkg = state['packages'].setdefault(name, _pkg_progress_entry(name))
        pkg['phase'] = 'Unpacking'
        base = PHASE_WEIGHTS['Download']
        pkg['percent'] = max(int(pkg.get('percent', 0)), base + PHASE_WEIGHTS['Unpacking'])
        _recompute_overall(state)
        return
    m = _RX_SETUP.search(line)
    if m:
        name = m.group(1)
        pkg = state['packages'].setdefault(name, _pkg_progress_entry(name))
        pkg['phase'] = 'Setting up'
        base = PHASE_WEIGHTS['Download'] + PHASE_WEIGHTS['Unpacking']
        pkg['percent'] = max(int(pkg.get('percent', 0)), base + PHASE_WEIGHTS['Setting up'])
        _recompute_overall(state)
        return
    m = _RX_TRIGGERS.search(line)
    if m:
        name = m.group(1)
        pkg = state['packages'].setdefault(name, _pkg_progress_entry(name))
        pkg['phase'] = 'Triggers'
        base = PHASE_WEIGHTS['Download'] + PHASE_WEIGHTS['Unpacking'] + PHASE_WEIGHTS['Setting up']
        pkg['percent'] = max(int(pkg.get('percent', 0)), min(100, base + PHASE_WEIGHTS['Triggers']))
        _recompute_overall(state)
        return


def _finish_state(state: Dict[str, Any], exit_code: int) -> None:
    if int(exit_code or 0) == 0:
        for pkg in state['packages'].values():
            pkg['percent'] = 100
            pkg['phase'] = 'Done'
        state['overall'] = {'percent': 100, 'phase': 'Done'}
    else:
        state['overall'] = {'percent': int(state['overall'].get('percent', 0)), 'phase': 'Failed'}
    state['done'] = True
    state['exit_code'] = int(exit_code or 0)
    state['ended_ts'] = time.time()


def _run_streaming(ssh, cmd: str, run_id: str, state: Dict[str, Any]) -> int:
    try:
        run_cmd = f"sh -lc {shlex.quote(cmd)}"
        stdin, stdout, stderr = ssh.exec_command(run_cmd, timeout=3600, get_pty=False)
        exit_code = None
        while True:
            line = stdout.readline()
            if line:
                append_log(run_id, line)
                _apply_line_to_state(state, line)
            else:
                if stdout.channel.exit_status_ready():
                    exit_code = stdout.channel.recv_exit_status()
                    break
                if stderr.channel.recv_ready():
                    try:
                        err_chunk = stderr.read(4096).decode(errors='replace')
                        if err_chunk:
                            append_log(run_id, err_chunk)
                    except Exception:
                        pass
                time.sleep(0.1)
        try:
            rem = stderr.read().decode(errors='replace')
            if rem:
                append_log(run_id, rem)
        except Exception:
            pass
        state['exit_code'] = exit_code
        return int(exit_code or 0)
    except Exception as e:
        state['error'] = str(e)
        append_log(run_id, f"[error] exec failed: {e}\n")
        state['exit_code'] = 255
        return 255


@updates_bp.post("/updates/run")
def updates_run_async():
    """Start an update run asynchronously and return a run_id."""
    try:
        data = request.get_json(force=True) or {}
        action = (data.get("action") or "").strip()
        sudo_password = data.get("sudo_password") or ""
        base_cmd = _ACTIONS.get(action)
        if not base_cmd:
            return jsonify({"ok": False, "error": f"Unknown action: {action}"}), 400

        s = _get_active_ssh_settings()
        if not _is_configured(s):
            return jsonify({"ok": False, "error": "SSH not configured"}), 400

        # Fast-path for lightweight checks to preserve legacy contract
        if action == 'reboot_required':
            ssh = ssh_connect(
                host=s["pi_host"], user=s["pi_user"],
                auth=s.get("auth_method", "key"),
                key_path=s.get("ssh_key_path", ""),
                password=s.get("password", ""), timeout=20
            )
            rc, out, err = ssh_exec(ssh, _force_english(base_cmd), timeout=20, shell=True)
            try:
                ssh.close()
            except Exception:
                pass
            return jsonify({"ok": True, "rc": rc, "stdout": out, "stderr": err})

        run_id = _new_run()
        _RUNS[run_id]['action'] = action

        def _bg():
            state = _RUNS.get(run_id) or {}
            append_log(run_id, f"Action: {action}\n")
            try:
                ssh = ssh_connect(
                    host=s["pi_host"], user=s["pi_user"],
                    auth=s.get("auth_method", "key"),
                    key_path=s.get("ssh_key_path", ""),
                    password=s.get("password", ""), timeout=20
                )
            except Exception as e:
                state['error'] = str(e)
                append_log(run_id, f"[error] SSH connect failed: {e}\n")
                _finish_state(state, 255)
                return

            try:
                if action == 'full_noob_update':
                    apt_cmd = (
                        "sudo -S -p '' DEBIAN_FRONTEND=noninteractive apt-get -y "
                        "-o Dpkg::Use-Pty=0 -o Dpkg::Progress-Fancy=0 --with-new-pkgs full-upgrade"
                    )
                    if sudo_password:
                        apt_cmd = _wrap_with_password(apt_cmd, sudo_password)
                    else:
                        apt_cmd = _force_english(apt_cmd)
                    _run_streaming(ssh, apt_cmd, run_id, state)

                    chain = (
                        "sudo apt autoremove --purge -y && "
                        "sudo apt autoclean && "
                        "( command -v flatpak >/dev/null 2>&1 && flatpak update -y || true ) && "
                        "( command -v snap >/dev/null 2>&1 && sudo snap refresh || true )"
                    )
                    if sudo_password:
                        chain = _wrap_with_password(chain, sudo_password)
                    else:
                        chain = _force_english(chain)
                    rc2, out2, err2 = ssh_exec(ssh, chain, timeout=180, shell=True)
                    if out2:
                        append_log(run_id, out2 if not sudo_password else out2.replace(sudo_password, '******'))
                    if err2:
                        append_log(run_id, err2 if not sudo_password else err2.replace(sudo_password, '******'))
                    exit_code = 0 if (_RUNS.get(run_id, {}).get('exit_code') in (None, 0) and rc2 == 0) else (_RUNS.get(run_id, {}).get('exit_code') or 0)
                else:
                    cmd = _wrap_with_password(base_cmd, sudo_password) if (action in _NEED_SUDO and sudo_password) else _force_english(base_cmd)
                    exit_code = _run_streaming(ssh, cmd, run_id, state)

                try:
                    rc3, out3, _ = ssh_exec(ssh, 'test -f /run/reboot-required && echo REBOOT_REQUIRED || echo NO_REBOOT', timeout=15, shell=True)
                    state['requires_reboot'] = 'REBOOT_REQUIRED' in (out3 or '')
                except Exception:
                    pass

                _finish_state(state, exit_code if isinstance(exit_code, int) else (state.get('exit_code') or 0))
                append_log(run_id, f"\n=== Update run completed (rc={state.get('exit_code')}) ===\n")
            finally:
                try:
                    ssh.close()
                except Exception:
                    pass

        threading.Thread(target=_bg, name=f"upd-{run_id}", daemon=True).start()
        return jsonify({"ok": True, "run_id": run_id})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@updates_bp.get('/updates/progress/<run_id>')
def updates_progress(run_id: str):
    state = _RUNS.get(run_id)
    if not state:
        items = list_logs()
        if any(x.get('id') == run_id for x in items):
            txt = read_log(run_id)
            return jsonify({
                'overall': {'percent': 100, 'phase': 'Done'},
                'packages': [],
                'active_iface': '',
                'requires_reboot': False,
                'done': True,
                'size': len(txt),
            })
        return jsonify({'error': 'unknown run_id'}), 404
    pkgs = [
        {'name': k, 'version': v.get('version', ''), 'phase': v.get('phase', ''), 'percent': int(v.get('percent', 0))}
        for k, v in state.get('packages', {}).items()
    ]
    return jsonify({
        'overall': state.get('overall', {'percent': 0, 'phase': 'Idle'}),
        'packages': pkgs,
        'active_iface': state.get('active_iface', ''),
        'requires_reboot': bool(state.get('requires_reboot')),
        'done': bool(state.get('done')),
        'exit_code': state.get('exit_code'),
        'error': state.get('error'),
    })


@updates_bp.get('/updates/logs')
def updates_logs_list():
    items = list_logs()
    for it in items:
        st = _RUNS.get(it['id'])
        if st and st.get('started_ts'):
            end = st.get('ended_ts') or time.time()
            it['duration'] = int(max(0, end - st['started_ts']))
    return jsonify({'items': items})


@updates_bp.get('/updates/logs/<run_id>')
def updates_log_read(run_id: str):
    try:
        text = read_log(run_id)
    except FileNotFoundError:
        return jsonify({'error': 'not found'}), 404
    if request.args.get('download'):
        path = make_log_path(run_id)
        return send_file(path, as_attachment=True, download_name=f'{run_id}.log')
    resp = make_response(text)
    resp.headers['Content-Type'] = 'text/plain; charset=utf-8'
    return resp


@updates_bp.delete('/updates/logs/<run_id>')
def updates_log_delete(run_id: str):
    ok = delete_log(run_id)
    return jsonify({'ok': bool(ok)})

@updates_bp.post("/updates/install_package")
def updates_install_package():
    """Install a single package by name and stream progress like other runs.
    Body: {"name": "pkg-name"}
    """
    try:
        data = request.get_json(force=True) or {}
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"ok": False, "error": "Missing package name"}), 400

        run_id = _new_run()
        _RUNS[run_id]['action'] = 'install_package'
        append_log(run_id, f"Action: install_package {name}\n")

        def _bg():
            state = _RUNS.get(run_id)
            try:
                s = _get_active_ssh_settings()
                ssh = ssh_connect(
                    host=s["pi_host"], user=s["pi_user"],
                    auth=s.get("auth_method", "key"), key_path=s.get("ssh_key_path", ""),
                    password=s.get("password", ""), timeout=20,
                )
            except Exception as e:
                state['error'] = str(e)
                append_log(run_id, f"[error] SSH connect failed: {e}\n")
                _finish_state(state, 255)
                return

            try:
                # Use apt-get install; keep it simple and noninteractive
                pkg = shlex.quote(name)
                cmd = f"sudo -n DEBIAN_FRONTEND=noninteractive apt-get install -y -- {pkg}"
                exit_code = _run_streaming(ssh, cmd, run_id, state)

                try:
                    rc3, out3, _ = ssh_exec(ssh, 'test -f /run/reboot-required && echo REBOOT_REQUIRED || echo NO_REBOOT', timeout=15, shell=True)
                    state['requires_reboot'] = 'REBOOT_REQUIRED' in (out3 or '')
                except Exception:
                    pass

                _finish_state(state, exit_code if isinstance(exit_code, int) else (state.get('exit_code') or 0))
                append_log(run_id, f"\n=== Update run completed (rc={state.get('exit_code')}) ===\n")
            finally:
                try: ssh.close()
                except Exception: pass

        threading.Thread(target=_bg, name=f"upd-inst-{run_id}", daemon=True).start()
        return jsonify({"ok": True, "run_id": run_id})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
