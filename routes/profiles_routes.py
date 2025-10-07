# routes/profiles_routes.py
from flask import Blueprint, current_app, request, jsonify, Response, session
import os, time
from typing import List, Tuple, Optional

# Brug relative imports – filerne ligger i routes/
from . import profiles_data
from . import ssh_utils

profiles_bp = Blueprint("profiles_bp", __name__, url_prefix="/profiles")

@profiles_bp.get("/list")
def list_profiles():
    data = profiles_data._ensure_store()
    return jsonify({
        "ok": True,
        "profiles": data.get("profiles", []),
        "active_profile_id": data.get("active_profile_id"),
        "default_profile_id": data.get("default_profile_id"),
    })

@profiles_bp.post("/new")
def new_profile():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "New profile").strip()
    prof = profiles_data.create_new_profile(name)
    return jsonify({"ok": True, "profile": prof})

@profiles_bp.post("/save")
def save_profile():
    body = request.get_json(silent=True) or {}
    pid = (body.get("id") or "").strip()
    if not pid:
        return jsonify({"ok": False, "error": "Missing id"}), 400

    result = profiles_data.save_existing_profile(pid, body)
    if isinstance(result, ValueError):
        return jsonify({"ok": False, "error": str(result)}), 400
    if not result:
        return jsonify({"ok": False, "error": "Profile not found"}), 404

    return jsonify({"ok": True, "profile": result})

@profiles_bp.post("/delete")
def delete_profile():
    body = request.get_json(silent=True) or {}
    pid = body.get("id")
    if not pid:
        return jsonify({"ok": False, "error": "Missing id"}), 400

    if not profiles_data.delete_profile_by_id(pid):
        return jsonify({"ok": False, "error": "Profile not found"}), 404

    return jsonify({"ok": True})

@profiles_bp.post("/set-active")
def set_active():
    body = request.get_json(silent=True) or {}
    pid = body.get("id")
    if not pid:
        return jsonify({"ok": False, "error": "Missing id"}), 400

    prof = profiles_data.set_active_profile(pid)
    if not prof:
        return jsonify({"ok": False, "error": "Profile not found"}), 404

    # ✅ hold server-session i sync, så /glances/* rammer korrekt host
    session["active_profile_id"] = pid
    session["profile_host"] = (prof.get("pi_host") or "").strip()

    return jsonify({"ok": True})

@profiles_bp.post("/set-default")
def set_default():
    body = request.get_json(silent=True) or {}
    pid = body.get("id")
    if not pid:
        return jsonify({"ok": False, "error": "Missing id"}), 400
    if not profiles_data.set_default_profile(pid):
        return jsonify({"ok": False, "error": "Profile not found"}), 404
    return jsonify({"ok": True})

@profiles_bp.post("/test")
def test_profile():
    body = request.get_json(silent=True) or {}
    host = (body.get("pi_host") or "").strip()
    user = (body.get("pi_user") or "").strip()
    auth = (body.get("auth_method") or "key").strip()
    key_path = ssh_utils._expand_user_home((body.get("ssh_key_path") or "").strip())
    pw = body.get("password") or ""

    if not host or not user:
        return jsonify({"ok": False, "error": "Host and user required"}), 400
    try:
        ssh = ssh_utils.ssh_connect(host, user, auth, key_path, pw, timeout=6)
        ssh.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@profiles_bp.get("/suggest-key-path")
def suggest_key_path():
    data = profiles_data._ensure_store()
    pid = (request.args.get("id") or "").strip()
    prof = profiles_data._find(data, pid) if pid else None

    cands = ssh_utils.get_key_candidates()
    cand_json = []
    for p, k, m in cands:
        base = os.path.basename(p)
        if base == "id_ed25519": k = "ed25519"
        elif base == "id_rsa": k = "rsa"
        elif base == "id_ecdsa": k = "ecdsa"
        cand_json.append({"path": p, "type": k, "mtime": m})

    default = cand_json[0]["path"] if cand_json else None
    suggest_new = None
    if not default and prof:
        stem = profiles_data._safe_stem_from_profile(prof)
        suggest_new = os.path.join(ssh_utils._expand_user_home("~"), ".ssh", f"id_{stem}")

    return jsonify({"ok": True, "default": default, "candidates": cand_json, "suggest_new": suggest_new})

@profiles_bp.post("/gen-key")
def generate_keypair():
    body = request.get_json(silent=True) or {}
    pid = (body.get("id") or "").strip()
    if not pid:
        return jsonify({"ok": False, "error": "Missing id"}), 400
    data = profiles_data._ensure_store()
    prof = profiles_data._find(data, pid)
    if not prof:
        return jsonify({"ok": False, "error": "Profile not found"}), 404

    desired = (body.get("key_path") or prof.get("ssh_key_path") or profiles_data._default_key_path_for_profile(prof)).strip()
    overwrite = bool(body.get("overwrite"))

    try:
        ssh_utils.generate_ssh_keypair(desired, overwrite)
        prof["ssh_key_path"] = ssh_utils._expand_user_home(desired)
        profiles_data._write_store(data)
        if data.get("active_profile_id") == pid:
            profiles_data._sync_active_into_legacy_config(prof)
        return jsonify({"ok": True, "private_key": prof["ssh_key_path"], "public_key": prof["ssh_key_path"] + ".pub"})
    except Exception as e:
        return jsonify({"ok": False, "error": f"Generate failed: {e}"}), 500

@profiles_bp.post("/install-key")
def install_public_key_on_host():
    body = request.get_json(silent=True) or {}
    pid = (body.get("id") or "").strip()
    if not pid:
        return jsonify({"ok": False, "error": "Missing id"}), 400
    data = profiles_data._ensure_store()
    prof = profiles_data._find(data, pid)
    if not prof:
        return jsonify({"ok": False, "error": "Profile not found"}), 404

    host = (prof.get("pi_host") or "").strip()
    user = (prof.get("pi_user") or "").strip()
    key_path = ssh_utils._expand_user_home((prof.get("ssh_key_path") or "").strip())
    pw = body.get("password") or prof.get("password") or ""

    if not host or not user:
        return jsonify({"ok": False, "error": "Host and user required on profile"}), 400
    if not os.path.exists(key_path):
        return jsonify({"ok": False, "error": "Private key not found – generate first"}), 400
    if not os.path.exists(key_path + ".pub"):
        return jsonify({"ok": False, "error": "Public key not found – generate first"}), 400

    with open(key_path + ".pub", "r", encoding="utf-8") as f:
        pub_line = f.read().strip() + "\n"

    try:
        ssh = ssh_utils.ssh_connect(host, user, "password" if pw else "key", key_path, pw)
        _, stdout, _ = ssh_utils.ssh_exec(ssh, "echo $HOME")
        home_dir = stdout.read().decode().strip() or f"/home/{user}"
        ssh_dir = f"{home_dir}/.ssh"
        auth_keys = f"{ssh_dir}/authorized_keys"

        sftp = ssh.open_sftp()
        try:
            sftp.mkdir(ssh_dir)
        except IOError:
            pass
        sftp.chmod(ssh_dir, 0o700)
        try:
            with sftp.file(auth_keys, "a", -1) as f:
                f.write(pub_line)
        except IOError:
            with sftp.file(auth_keys, "w", -1) as f:
                f.write(pub_line)
        sftp.chmod(auth_keys, 0o600)
        sftp.close()
        ssh.close()
        return jsonify({"ok": True, "installed_to": auth_keys})
    except Exception as e:
        return jsonify({"ok": False, "error": f"Install failed: {e}"}), 500

@profiles_bp.get("/check-readiness")
def check_readiness():
    try:
        data, prof = profiles_data._profile_from_request_or_active(request)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    host = (prof.get("pi_host") or "").strip()
    user = (prof.get("pi_user") or "").strip()
    auth = (prof.get("auth_method") or "key").strip()
    keyp = ssh_utils._expand_user_home((prof.get("ssh_key_path") or "").strip())
    pw = prof.get("password") or ""

    result = {"ok": False, "checks": {}, "host": host, "user": user}
    try:
        ssh = ssh_utils.ssh_connect(host, user, auth, keyp, pw, prefer_password=False, timeout=10)
    except Exception as e:
        result["checks"]["ssh_login"] = {"ok": False, "msg": f"{e}"}
        return jsonify(result), 200

    def add(name, rc, out, err, ok_if=0):
        result["checks"][name] = {"ok": (rc == ok_if), "rc": rc, "out": out.strip(), "err": err.strip()}

    add("ssh_service", *ssh_utils.ssh_exec(ssh, "systemctl is-active ssh || systemctl is-active sshd || true"))
    add("port_22", *ssh_utils.ssh_exec(ssh, "ss -tln | grep -q ':22 ' || lsof -i -P -n | grep -q 'sshd.*LISTEN'"), ok_if=0)
    for tool in ("lscpu", "free", "df", "lsblk", "findmnt"):
        add(f"has_{tool}", *ssh_utils.ssh_exec(ssh, f"command -v {tool} >/dev/null 2>&1; echo $?"), ok_if=0)
    add("has_sensors", *ssh_utils.ssh_exec(ssh, "command -v sensors >/dev/null 2>&1; echo $?"), ok_if=0)
    add("has_smartctl", *ssh_utils.ssh_exec(ssh, "command -v smartctl >/dev/null 2>&1; echo $?"), ok_if=0)
    add("sensors_json", *ssh_utils.ssh_exec(ssh, "sensors -j >/dev/null 2>&1; echo $?"), ok_if=0)
    rc, out, err = ssh_utils.ssh_exec(ssh, "findmnt -no SOURCE /")
    root_src = out.strip()
    add("root_source", rc, out, err)
    rc2, out2, err2 = ssh_utils.ssh_exec(ssh, f"lsblk -no PKNAME {root_src} 2>/dev/null || true") if root_src else (1, "", "")
    base = out2.strip()
    result["checks"]["root_base"] = {"ok": bool(base), "rc": rc2, "out": base, "err": err2.strip()}
    if base:
        rc3, out3, err3 = ssh_utils.ssh_exec(ssh, f"sudo -n smartctl -A /dev/{base} >/dev/null 2>&1; echo $?")
        try_ok = "0" in out3.strip()
        result["checks"]["smartctl_nopasswd"] = {"ok": try_ok, "rc": 0 if try_ok else 1, "out": out3.strip(), "err": err3.strip()}
    else:
        result["checks"]["smartctl_nopasswd"] = {"ok": False, "rc": 1, "out": "", "err": "no base device"}

    ssh.close()

    essentials = ["ssh_service", "port_22", "has_lscpu", "has_free", "has_df", "has_lsblk", "has_findmnt"]
    result["ok"] = all(result["checks"].get(k, {}).get("ok") for k in essentials)
    return jsonify(result), 200

@profiles_bp.get("/bootstrap.sh")
def bootstrap_script():
    script = r"""#!/usr/bin/env bash
set -euo pipefail

if ! command -v sudo >/dev/null 2>&1; then
  echo "This script needs sudo. Please run on a Debian/Ubuntu-based system."
  exit 1
fi

sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server
sudo systemctl enable --now ssh
if grep -qE '^[#\s]*PasswordAuthentication' /etc/ssh/sshd_config; then
  sudo sed -i 's/^[#\s]*PasswordAuthentication .*/PasswordAuthentication yes/' /etc/ssh/sshd_config
else
  echo 'PasswordAuthentication yes' | sudo tee -a /etc/ssh/sshd_config >/dev/null
fi
if grep -qE '^[#\s]*PubkeyAuthentication' /etc/ssh/sshd_config; then
  sudo sed -i 's/^[#\s]*PubkeyAuthentication .*/PubkeyAuthentication yes/' /etc/ssh/sshd_config
else
  echo 'PubkeyAuthentication yes' | sudo tee -a /etc/ssh/sshd_config >/dev/null
fi
sudo systemctl restart ssh
echo
echo "✅ OpenSSH server installed and running."
echo "   You can now go back to the controller and press 'Install key on host'."
echo
"""
    return Response(script, mimetype="text/plain")
