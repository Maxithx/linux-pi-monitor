# utils/ssh_utils.py
import os, paramiko
from typing import List, Tuple, Optional
import re

def _expand_user_home(path: str) -> str:
    # Gør "~" og %USERPROFILE%/HOME portable
    return os.path.expandvars(os.path.expanduser(path))

def _detect_key_type_from_file(path: str) -> Optional[str]:
    """Læs første linjer og gæt nøgletype (rsa/ed25519/ecdsa)."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            head = f.read(2048)
    except Exception:
        return None
    if "BEGIN OPENSSH PRIVATE KEY" in head:
        return "openssh"
    if "BEGIN RSA PRIVATE KEY" in head:
        return "rsa"
    if "BEGIN EC PRIVATE KEY" in head or "BEGIN ECDSA PRIVATE KEY" in head:
        return "ecdsa"
    return "openssh"

def _load_private_key(path: str):
    """Prøv at indlæse privatnøglen uanset type (RSA/Ed25519/ECDSA)."""
    err = None
    try:
        return paramiko.RSAKey.from_private_key_file(path)
    except Exception as e:
        err = e
    try:
        return paramiko.Ed25519Key.from_private_key_file(path)
    except Exception as e:
        err = e
    try:
        return paramiko.ECDSAKey.from_private_key_file(path)
    except Exception as e:
        err = e
    raise err or RuntimeError(f"Unsupported key type: {err}")

def get_key_candidates() -> List[Tuple[str, str, float]]:
    """
    Find kandidatnøgler i ~/.ssh med prioritet:
    id_ed25519, id_rsa, id_ecdsa, ellers andre 'id_*' filer.
    Returnerer liste af (path, type, mtime).
    """
    home_ssh = os.path.join(_expand_user_home("~"), ".ssh")
    if not os.path.isdir(home_ssh):
        return []
    entries = []
    try:
        for name in os.listdir(home_ssh):
            path = os.path.join(home_ssh, name)
            if not os.path.isfile(path):
                continue
            if path.endswith(".pub"):
                continue
            if name in ("config", "known_hosts"):
                continue
            if not os.path.exists(path + ".pub"):
                continue
            ktype = _detect_key_type_from_file(path) or "unknown"
            mtime = 0.0
            try:
                mtime = os.path.getmtime(path)
            except Exception:
                pass
            entries.append((path, ktype, mtime))
    except Exception:
        return []

    def _prio(item):
        p, _, _ = item
        base = os.path.basename(p)
        if base == "id_ed25519":
            return (0, base)
        if base == "id_rsa":
            return (1, base)
        if base == "id_ecdsa":
            return (2, base)
        return (3, base)
    entries.sort(key=_prio)
    return entries

def ssh_connect(host: str, user: str, auth: str, key_path: str, password: str, prefer_password=False, timeout=10) -> paramiko.SSHClient:
    """
    Opret en SSH-forbindelse. Hvis prefer_password=True forsøges password først (til bootstrap-scenarier).
    """
    if not host or not user:
        raise RuntimeError("Host and user required")
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    def _connect_with_pw():
        if not password:
            raise RuntimeError("Password required")
        cli.connect(hostname=host, username=user, password=password, timeout=timeout)
    def _connect_with_key():
        if not key_path or not os.path.exists(key_path):
            raise RuntimeError("Key path missing")
        key = _load_private_key(key_path)
        cli.connect(hostname=host, username=user, pkey=key, timeout=timeout)

    primary = _connect_with_pw if (prefer_password or auth == "password") else _connect_with_key
    fallback = _connect_with_key if primary is _connect_with_pw else _connect_with_pw

    try:
        primary()
    except Exception as e1:
        try:
            fallback()
        except Exception as e2:
            raise RuntimeError(f"Login failed: {e1}; fallback: {e2}")

    try:
        tr = cli.get_transport()
        if tr:
            tr.set_keepalive(10)
    except Exception:
        pass
    return cli

def ssh_exec(ssh: paramiko.SSHClient, cmd: str, timeout=20) -> Tuple[int, str, str]:
    """Kør kommando og returner (rc, stdout, stderr)."""
    try:
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
        try:
            stdout.channel.settimeout(timeout)
            stderr.channel.settimeout(timeout)
        except Exception:
            pass
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        rc = stdout.channel.recv_exit_status()
        return rc, out, err
    except Exception as e:
        return 255, "", f"{e}"

def generate_ssh_keypair(key_path: str, overwrite: bool = False):
    priv_path = _expand_user_home(key_path)
    pub_path = priv_path + ".pub"
    
    if not overwrite and (os.path.exists(priv_path) or os.path.exists(pub_path)):
        raise FileExistsError("Key already exists – pass overwrite=true to replace")

    os.makedirs(os.path.dirname(priv_path), exist_ok=True)
    key = paramiko.RSAKey.generate(2048)
    key.write_private_key_file(priv_path)
    pub_line = f"{key.get_name()} {key.get_base64()}\n"
    with open(pub_path, "w", encoding="utf-8") as f:
        f.write(pub_line)
    return {"private_key": priv_path, "public_key": pub_path}