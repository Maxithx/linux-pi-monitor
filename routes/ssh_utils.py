# routes/ssh_utils.py
# Robust SSH helpers til Linux/Pi Monitor

import os
import paramiko
from typing import List, Tuple, Optional


# -------------------------
# Path & key utils
# -------------------------
def _expand_user_home(path: str) -> str:
    """Gør '~' og env-variabler portable på tværs af platforme."""
    return os.path.expandvars(os.path.expanduser(path or ""))

def _detect_key_type_from_file(path: str) -> Optional[str]:
    """Læs et par KB af filen og gæt nøgletype (rsa/ed25519/ecdsa)."""
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
    """Prøv at indlæse privatnøglen uanset format (RSA/Ed25519/ECDSA)."""
    last_err: Optional[Exception] = None
    try:
        return paramiko.RSAKey.from_private_key_file(path)
    except Exception as e:
        last_err = e
    try:
        return paramiko.Ed25519Key.from_private_key_file(path)
    except Exception as e:
        last_err = e
    try:
        return paramiko.ECDSAKey.from_private_key_file(path)
    except Exception as e:
        last_err = e
    raise last_err or RuntimeError("Unsupported SSH key type")

def get_key_candidates() -> List[Tuple[str, str, float]]:
    """
    Find kandidatnøgler i ~/.ssh med prioritet:
    id_ed25519, id_rsa, id_ecdsa, derefter andre 'id_*' filer.
    Returnerer liste af (path, type, mtime).
    """
    home_ssh = os.path.join(_expand_user_home("~"), ".ssh")
    if not os.path.isdir(home_ssh):
        return []
    entries: List[Tuple[str, str, float]] = []
    try:
        for name in os.listdir(home_ssh):
            path = os.path.join(home_ssh, name)
            if (not os.path.isfile(path)) or name.endswith(".pub"):
                continue
            if name in ("config", "known_hosts"):
                continue
            if not os.path.exists(path + ".pub"):
                # kræv at der findes en .pub ved siden af
                continue
            ktype = _detect_key_type_from_file(path) or "unknown"
            try:
                mtime = os.path.getmtime(path)
            except Exception:
                mtime = 0.0
            entries.append((path, ktype, mtime))
    except Exception:
        return []

    def _prio(item: Tuple[str, str, float]):
        base = os.path.basename(item[0])
        if base == "id_ed25519":
            return (0, base)
        if base == "id_rsa":
            return (1, base)
        if base == "id_ecdsa":
            return (2, base)
        return (3, base)

    entries.sort(key=_prio)
    return entries


# -------------------------
# SSH connect / exec
# -------------------------
def ssh_connect(
    host: str,
    user: str,
    auth: str,
    key_path: str,
    password: str,
    prefer_password: bool = False,
    timeout: int = 10,
) -> paramiko.SSHClient:
    """
    Opret en SSH-forbindelse. Hvis prefer_password=True forsøges password først
    (praktisk i bootstrap-scenarier). Vi slår agent-søgning fra for at undgå
    lange timeouts og “hænger”.
    """
    if not host or not user:
        raise RuntimeError("Host and user required")

    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # Brug deterministiske parametre så vi ikke hænger på agent/keys
    common_kw = dict(
        hostname=host,
        username=user,
        timeout=timeout,
        banner_timeout=timeout,
        auth_timeout=timeout,
        allow_agent=False,
        look_for_keys=False,
    )

    def _connect_with_pw():
        if not password:
            raise RuntimeError("Password required")
        cli.connect(password=password, **common_kw)

    def _connect_with_key():
        kp = _expand_user_home(key_path)
        if not kp or not os.path.exists(kp):
            raise RuntimeError(f"Key path missing or not found: {kp}")
        pkey = _load_private_key(kp)
        cli.connect(pkey=pkey, **common_kw)

    primary = _connect_with_pw if (prefer_password or (auth or "").lower() == "password") else _connect_with_key
    fallback = _connect_with_key if primary is _connect_with_pw else _connect_with_pw

    try:
        primary()
    except Exception as e1:
        try:
            fallback()
        except Exception as e2:
            raise RuntimeError(f"Login failed. primary={type(e1).__name__}: {e1}; fallback={type(e2).__name__}: {e2}")

    try:
        tr = cli.get_transport()
        if tr:
            tr.set_keepalive(10)
    except Exception:
        pass

    return cli


def _quote_sh(cmd: str) -> str:
    """Quote til sh -lc ..."""
    return (cmd or "").replace('"', r'\"')


def ssh_exec(
    ssh: paramiko.SSHClient,
    cmd: str,
    timeout: int = 20,
    shell: bool = False,
    get_pty: bool = False,
) -> Tuple[int, str, str]:
    """
    Kør kommando og returner (rc, stdout, stderr).

    - shell=True => kør via 'sh -lc "<cmd>"' så pipes/&&/|| virker.
    - get_pty=True kan tvinges for programmer der gerne vil have TTY.
    """
    try:
        run_cmd = f'sh -lc "{_quote_sh(cmd)}"' if shell else cmd
        stdin, stdout, stderr = ssh.exec_command(run_cmd, timeout=timeout, get_pty=get_pty)
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
        return 255, "", f"exec_error({cmd}): {e}"


def ssh_exec_shell(ssh: paramiko.SSHClient, cmd: str, timeout: int = 20) -> Tuple[int, str, str]:
    """Convenience: kør altid via sh -lc."""
    return ssh_exec(ssh, cmd, timeout=timeout, shell=True)


# -------------------------
# Key generation
# -------------------------
def generate_ssh_keypair(key_path: str, overwrite: bool = False, algo: str = "rsa"):
    """
    Generér en nøgle. Default 'rsa' for bred kompatibilitet. Brug algo='ed25519'
    hvis libs/paramiko understøtter det i dit miljø.
    """
    priv_path = _expand_user_home(key_path)
    pub_path = priv_path + ".pub"

    if not overwrite and (os.path.exists(priv_path) or os.path.exists(pub_path)):
        raise FileExistsError("Key already exists – pass overwrite=True to replace")

    os.makedirs(os.path.dirname(priv_path), exist_ok=True)

    key = None
    if algo.lower() == "ed25519":
        try:
            key = paramiko.Ed25519Key.generate()
        except Exception:
            # fallback hvis miljøet ikke kan generere ed25519
            key = paramiko.RSAKey.generate(2048)
    else:
        key = paramiko.RSAKey.generate(2048)

    key.write_private_key_file(priv_path)
    pub_line = f"{key.get_name()} {key.get_base64()}\n"
    with open(pub_path, "w", encoding="utf-8") as f:
        f.write(pub_line)

    return {"private_key": priv_path, "public_key": pub_path, "algo": key.get_name()}
