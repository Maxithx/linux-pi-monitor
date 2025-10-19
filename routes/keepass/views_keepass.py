from __future__ import annotations
import os
import threading
import time
import shlex
from datetime import datetime, timezone
from typing import Dict, Any

from flask import request, jsonify, render_template

from . import keepass_bp
from routes.settings import _get_active_ssh_settings, _is_configured
from routes.common.ssh_utils import ssh_connect
from paramiko.ssh_exception import AuthenticationException


# --- Simple runs state for KeePass setup ---
_RUNS: Dict[str, Dict[str, Any]] = {}


def _logs_dir() -> str:
    base = os.path.join('var', 'log', 'linux-pi-monitor', 'keepass')
    os.makedirs(base, exist_ok=True)
    return base


def _log_path(run_id: str) -> str:
    safe = ''.join(c for c in (run_id or '') if c.isalnum() or c in ('-', '_', 'T', 'Z', '.'))
    return os.path.join(_logs_dir(), f"{safe}.log")


def _append_log(run_id: str, text: str) -> None:
    path = _log_path(run_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(text)


def _read_log(run_id: str) -> str:
    with open(_log_path(run_id), 'r', encoding='utf-8', errors='replace') as f:
        return f.read()


def _new_run(phase: str) -> str:
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H-%M-%SZ')
    run_id = f"{ts}_{phase}"
    _RUNS[run_id] = {
        'phase': phase,
        'started_ts': time.time(),
        'finished': False,
        'exit_code': None,
        'error': None,
    }
    _append_log(run_id, f"=== KeePass setup {phase} started {datetime.utcnow().isoformat()}Z ===\n")
    return run_id


_PHASE_TO_SCRIPT = {
    'phase1': 'kp_phase1_deps.sh',
    'phase2': 'kp_phase2_samba.sh',
    'phase3': 'kp_phase3_firewall.sh',
    'phase4': 'kp_phase4_verify.sh',
    'rollback': 'kp_rollback.sh',
}


def _upload_scripts(ssh) -> str:
    # Upload scripts to ~/kp-setup, ensure +x
    sftp = ssh.open_sftp()
    try:
        # Resolve home
        stdin, stdout, _ = ssh.exec_command('printf %s "$HOME"')
        home = stdout.read().decode(errors='replace').strip() or '/home/pi'
        remote_dir = f"{home}/kp-setup"
        try:
            sftp.stat(remote_dir)
        except IOError:
            ssh.exec_command(f"mkdir -p {shlex.quote(remote_dir)}")

        local_dir = os.path.join('scripts', 'keepass-vault')
        for name in _PHASE_TO_SCRIPT.values():
            local_path = os.path.join(local_dir, name)
            remote_path = f"{remote_dir}/{name}"
            with open(local_path, 'rb') as lf:
                with sftp.file(remote_path, 'wb') as rf:
                    rf.write(lf.read())
            ssh.exec_command(f"chmod +x {shlex.quote(remote_path)}")
        return remote_dir
    finally:
        try:
            sftp.close()
        except Exception:
            pass


def _run_phase_bg(run_id: str, env: Dict[str, str] | None, settings: Dict[str, Any]):
    state = _RUNS.get(run_id) or {}
    s = (settings or {}).copy()
    if not _is_configured(s):
        state['finished'] = True
        state['exit_code'] = 255
        state['error'] = 'SSH not configured'
        _append_log(run_id, "[error] SSH not configured\n")
        return

    try:
        _append_log(run_id, f"[ssh] Connecting to {s.get('pi_user','?')}@{s.get('pi_host','?')} (auth={s.get('auth_method','key')})...\n")
        ssh = ssh_connect(
            host=s["pi_host"], user=s["pi_user"],
            auth=s.get("auth_method", "key"),
            key_path=s.get("ssh_key_path", ""),
            password=s.get("password", ""), timeout=30
        )
        _append_log(run_id, "[ssh] Connected.\n")
    except AuthenticationException as e:
        state['finished'] = True
        state['exit_code'] = 255
        state['error'] = 'auth_failed'
        _append_log(run_id, "[ssh] Authentication failed (wrong key/password).\n")
        return
    except Exception as e:
        state['finished'] = True
        state['exit_code'] = 255
        state['error'] = str(e)
        _append_log(run_id, f"[error] SSH connect failed: {e}\n")
        return

    try:
        remote_dir = _upload_scripts(ssh)
        phase = state.get('phase')
        script = _PHASE_TO_SCRIPT.get(phase or '')
        if not script:
            state['finished'] = True
            state['exit_code'] = 255
            state['error'] = f"unknown phase: {phase}"
            _append_log(run_id, f"[error] unknown phase: {phase}\n")
            return

        # Build env prefix
        env = env or {}
        env_parts = []
        for k, v in env.items():
            if v is None:
                continue
            env_parts.append(f"{k}={shlex.quote(str(v))}")
        env_prefix = (" ".join(env_parts) + " ") if env_parts else ""

        # Execute with streaming (chunk-based) and optional sudo password feed
        script_path = shlex.quote(remote_dir + '/' + script)
        sudo_pass = env.get('SUDO_PASS') or ''

        # Preflight: if sudo password not provided and phase likely needs sudo, check if passwordless sudo is available.
        # This prevents hanging when remote prompts for a sudo password.
        try:
            if not sudo_pass and (phase in ('phase1', 'phase2', 'phase3', 'rollback')):
                _append_log(run_id, "[dbg] preflight: checking 'sudo -n' availability...\n")
                stdin2, stdout2, stderr2 = ssh.exec_command("bash -lc 'sudo -n true 2>/dev/null || echo NEED_SUDO_PASS'", timeout=10)
                pre = (stdout2.read() or b'').decode(errors='replace')
                if 'NEED_SUDO_PASS' in pre:
                    state['finished'] = True
                    state['exit_code'] = 255
                    state['error'] = 'sudo_requires_password'
                    _append_log(run_id, "[error] sudo requires a password. Provide SUDO_PASS or configure passwordless sudo (NOPASSWD).\n")
                    return
        except Exception:
            # If preflight fails, continue; scripts may still succeed without sudo.
            pass
        if sudo_pass:
            # Export SUDO_PASS and function override for child bash. Use exec to keep PID/simple exit.
            run_body = (
                "export DEBIAN_FRONTEND=noninteractive; "
                f"export SUDO_PASS={shlex.quote(sudo_pass)}; "
                # Prepend SUDO_PASS to stdin if data is piped; otherwise just feed password.
                "sudo() { if [ -t 0 ]; then printf -- %s\\n \"$SUDO_PASS\" | command sudo -S -p '' \"$@\"; "
                "else { printf -- %s\\n \"$SUDO_PASS\"; cat; } | command sudo -S -p '' \"$@\"; fi; }; "
                "export -f sudo; "
                f"{env_prefix} exec bash {script_path}"
            )
            run_str = run_body
        else:
            run_str = f"export DEBIAN_FRONTEND=noninteractive; {env_prefix} exec bash {script_path}"
        cmd = f"bash -lc {shlex.quote(run_str)}"

        # Prepare masking for any secrets that might appear in debug lines
        secret = env.get('SMB_PASS') or ''
        secret2 = sudo_pass
        def _mask(s: str) -> str:
            """Mask secrets even when quoted/escaped inside shell snippets."""
            import re
            if not s:
                return s
            out = s
            # Direct raw occurrences
            if secret:
                out = out.replace(secret, '******')
            if secret2:
                out = out.replace(secret2, '******')
            # Common KEY=... patterns (handles quotes, shlex.quote, and "'"'" sequences)
            patterns = [
                r"(SMB_PASS=)([^\s;]+)",
                r"(SUDO_PASS=)([^\s;]+)",
                r"(export\s+SUDO_PASS=)([^\s;]+)",
            ]
            for pat in patterns:
                out = re.sub(pat, r"\1******", out)
            return out

        _append_log(run_id, _mask(f"[dbg] remote_dir={remote_dir}\n"))
        _append_log(run_id, _mask(f"[dbg] sudo_pass={'yes' if bool(sudo_pass) else 'no'}\n"))
        _append_log(run_id, _mask(f"[dbg] shell=bash\n"))
        _append_log(run_id, _mask(f"[dbg] cmd={cmd}\n"))

        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=3600, get_pty=True)

        ch_out = stdout.channel
        ch_err = stderr.channel
        exit_code = None
        last_activity = time.time()
        last_heartbeat = time.time()
        while True:
            did = False
            if ch_out.recv_ready():
                try:
                    chunk = ch_out.recv(4096).decode(errors='replace')
                    if chunk:
                        _append_log(run_id, _mask(chunk))
                        did = True
                except Exception:
                    pass
            if ch_err.recv_ready():
                try:
                    chunk = ch_err.recv(4096).decode(errors='replace')
                    if chunk:
                        _append_log(run_id, _mask(chunk))
                        did = True
                except Exception:
                    pass

            now = time.time()
            if not did and (now - last_heartbeat) >= 5:
                _append_log(run_id, "[dbg] still running...\n")
                last_heartbeat = now

            if ch_out.exit_status_ready():
                exit_code = ch_out.recv_exit_status()
                # Drain remaining
                try:
                    while ch_out.recv_ready():
                        _append_log(run_id, _mask(ch_out.recv(4096).decode(errors='replace')))
                except Exception:
                    pass
                try:
                    while ch_err.recv_ready():
                        _append_log(run_id, _mask(ch_err.recv(4096).decode(errors='replace')))
                except Exception:
                    pass
                break

            if not did:
                time.sleep(0.1)
        state['exit_code'] = int(exit_code or 0)
        state['finished'] = True
        _append_log(run_id, f"\n=== KeePass setup {phase} completed (rc={state['exit_code']}) ===\n")
    except Exception as e:
        state['exit_code'] = 255
        state['finished'] = True
        state['error'] = str(e)
        _append_log(run_id, f"[error] exec failed: {e}\n")
    finally:
        try:
            ssh.close()
        except Exception:
            pass


def _start_phase(phase: str, env: Dict[str, str] | None, settings: Dict[str, Any]):
    run_id = _new_run(phase)
    threading.Thread(target=_run_phase_bg, args=(run_id, env, settings), daemon=True).start()
    return run_id


@keepass_bp.post('/api/keepass/setup/phase1')
def kp_phase1():
    data = request.get_json(silent=True) or {}
    env = (data.get('env') or {})
    s = _get_active_ssh_settings()
    run_id = _start_phase('phase1', env, s)
    return jsonify({'run_id': run_id})


@keepass_bp.post('/api/keepass/setup/phase2')
def kp_phase2():
    data = request.get_json(silent=True) or {}
    env = (data.get('env') or {})
    # Require SMB_PASS for phase2 to avoid interactive hang in smbpasswd
    smb_pass = (env.get('SMB_PASS') or '').strip()
    if not smb_pass:
        return jsonify({'error': 'SMB_PASS is required for phase2'}), 400
    # Sanity checks: enforce reasonable length and disallow control characters
    if len(smb_pass) < 8 or len(smb_pass) > 64:
        return jsonify({'error': 'SMB_PASS must be 8-64 characters'}), 400
    if any(c in smb_pass for c in ('\n', '\r', '\x00')):
        return jsonify({'error': 'SMB_PASS contains invalid control characters'}), 400
    s = _get_active_ssh_settings()
    run_id = _start_phase('phase2', env, s)
    return jsonify({'run_id': run_id})


@keepass_bp.post('/api/keepass/setup/phase3')
def kp_phase3():
    data = request.get_json(silent=True) or {}
    env = (data.get('env') or {})
    s = _get_active_ssh_settings()
    run_id = _start_phase('phase3', env, s)
    return jsonify({'run_id': run_id})


@keepass_bp.post('/api/keepass/setup/phase4')
def kp_phase4():
    data = request.get_json(silent=True) or {}
    env = (data.get('env') or {})
    s = _get_active_ssh_settings()
    run_id = _start_phase('phase4', env, s)
    return jsonify({'run_id': run_id})


@keepass_bp.post('/api/keepass/setup/rollback')
def kp_rollback():
    data = request.get_json(silent=True) or {}
    env = (data.get('env') or {})
    s = _get_active_ssh_settings()
    run_id = _start_phase('rollback', env, s)
    return jsonify({'run_id': run_id})


@keepass_bp.get('/api/keepass/setup/progress/<run_id>')
def kp_progress(run_id: str):
    st = _RUNS.get(run_id)
    if not st:
        # If log exists, return as finished
        try:
            txt = _read_log(run_id)
            return jsonify({'log': txt, 'finished': True, 'exit_code': 0, 'error': None})
        except Exception:
            return jsonify({'error': 'unknown run_id'}), 404
    txt = ''
    try:
        txt = _read_log(run_id)
    except Exception:
        txt = ''
    return jsonify({'log': txt, 'finished': bool(st.get('finished')), 'exit_code': st.get('exit_code'), 'error': st.get('error')})
@keepass_bp.get('/keepass')
def keepass_page():
    return render_template('keepass.html')
