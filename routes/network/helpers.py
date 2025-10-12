import re
from shlex import quote

from routes.common.ssh_utils import ssh_connect, ssh_exec
from routes.settings import _get_active_ssh_settings, _is_configured


# ---- Intern helpers ---------------------------------------------------------

def _active():
    s = _get_active_ssh_settings()
    if not _is_configured(s):
        raise RuntimeError("SSH not configured")
    return s


def _ssh():
    s = _active()
    return ssh_connect(
        host=s["pi_host"],
        user=s["pi_user"],
        auth=s.get("auth_method", "key"),
        key_path=s.get("ssh_key_path", ""),
        password=s.get("password", ""),
        timeout=20,
    )


def _has_nmcli(ssh) -> bool:
    rc, _, _ = ssh_exec(ssh, "command -v nmcli >/dev/null 2>&1", timeout=3)
    return rc == 0


def _iface_detect(ssh) -> str:
    """
    Find første Wi-Fi interface ved at tjekke `iw dev` (bedst) eller `ls /sys/class/net`.
    Dette tager højde for moderne navne som wlp3s0.
    """
    # 1. Prøv med iw dev (standard og bedst)
    rc, out, _ = ssh_exec(
        ssh, "iw dev | awk '$1==\"Interface\"{print $2; exit}'", timeout=5
    )
    cand = (out or "").strip()
    if cand:
        return cand

    # 2. Prøv med /sys/class/net for almindelige Wi-Fi-navne
    rc, devs, _ = ssh_exec(ssh, "ls -1 /sys/class/net | tr -d '\r'", timeout=5)
    devices = [d.strip() for d in (devs or "").splitlines() if d.strip()]

    # Prioriterer navne, der ligner Wi-Fi interfaces (f.eks. wlan0, wlp3s0, wlo1)
    for d in devices:
        if d.startswith(("wlan", "wlp", "wlo")):
            return d

    # 3. Sidste fallback (hvis ingen Wi-Fi interface blev fundet)
    return "wlan0"


def _which_bin(ssh, names) -> str:
    """Find første eksekverbare binar blandt 'names' (navn eller fuld sti)."""
    for n in names:
        rc, out, _ = ssh_exec(ssh, f"command -v {quote(n)} 2>/dev/null", timeout=3)
        path = (out or "").strip()
        if rc == 0 and path:
            return path
        rc, _, _ = ssh_exec(ssh, f"[ -x {quote(n)} ]", timeout=3)
        if rc == 0:
            return n
    return ""


def _nmcli_bin_path(ssh) -> str:
    """Finder den fulde sti til nmcli for at undgå PATH-problemer i sudo."""
    return _which_bin(ssh, ["nmcli", "/usr/bin/nmcli", "/bin/nmcli"])


def _active_bss(ssh) -> tuple[str, str]:
    """Finder aktivt BSSID og SSID via wpa_cli eller iw link."""
    iface = _iface_detect(ssh)
    iface_q = quote(iface)

    # 1. wpa_cli status (bedst)
    wpa_bin = _which_bin(ssh, ["wpa_cli", "/sbin/wpa_cli", "/usr/sbin/wpa_cli", "/usr/bin/wpa_cli"])
    if wpa_bin:
        # Prøv uden sudo først
        _, out, _ = ssh_exec(ssh, f"{wpa_bin} -i {iface_q} status 2>/dev/null || true", timeout=4)
        if out:
            bssid = ssid = ""
            for ln in out.splitlines():
                if ln.startswith("bssid="):
                    bssid = ln.split("=", 1)[1].strip().lower()
                elif ln.startswith("ssid="):
                    ssid = ln.split("=", 1)[1].strip()
            if bssid or ssid:
                return (bssid, ssid)

    # 2. fallback: iw link
    _, link, _ = ssh_exec(ssh, f"iw dev {iface_q} link 2>/dev/null || true", timeout=4)
    bssid = ssid = ""
    if link:
        m = re.search(r"Connected to\s+([0-9a-f:]{17})", link, re.I)
        if m:
            bssid = m.group(1).lower()
        m = re.search(r"SSID:\s*(.+)", link)
        if m:
            ssid = m.group(1).strip()
    return (bssid, ssid)


def _sudo_cmd(sudo_pw: str | None, inner: str) -> str:
    """Wrap en kommando med sudo (med password hvis givet)."""
    quoted = inner.replace('"', r"\"")
    # Brug sh -lc for at sikre at PATH og miljøvariabler er korrekte, selv med -S
    if sudo_pw:
        # -S: read pw from stdin, -p "": no prompt text -> keeps logs clean
        return f'echo "{sudo_pw}" | sudo -S -p "" sh -lc "{quoted}"'
    # Bruger sudo -n for at køre uden password (skal virke med visse sudo-regler)
    return f'sudo -n sh -lc "{quoted}"'


def _nm_radio_on(ssh, iface: str, sudo_pw: str | None):
    """Sørg for at radio er tændt og interface er up (tåler at blive kørt flere gange)."""
    iface_q = quote(iface)

    nmcli_bin = _nmcli_bin_path(ssh)  # Find nmcli path
    nmcli_cmd = nmcli_bin or "nmcli"  # Brug path, fallback til navn

    # Tjek og tænd for nmcli radio
    ssh_exec(
        ssh, _sudo_cmd(sudo_pw, f"{nmcli_cmd} radio wifi on || true"), timeout=6
    )
    # Fjern rfkill (hardware/software kill switch)
    ssh_exec(
        ssh, _sudo_cmd(sudo_pw, "rfkill unblock wifi || true"), timeout=4
    )
    # Sæt iface up (kan være nede pga. rfkill)
    ssh_exec(
        ssh, _sudo_cmd(sudo_pw, f"ip link set {iface_q} up || true"), timeout=4
    )
