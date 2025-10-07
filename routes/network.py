# routes/network.py
import re
from shlex import quote
from flask import Blueprint, render_template, request, jsonify

from .ssh_utils import ssh_connect, ssh_exec
from .settings import _get_active_ssh_settings, _is_configured

network_bp = Blueprint("network", __name__)


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
        # Bruger echo "password" | sudo -S for at køre med password
        return f'echo "{sudo_pw}" | sudo -S sh -lc "{quoted}"'
    # Bruger sudo -n for at køre uden password (skal virke med visse sudo-regler)
    return f'sudo -n sh -lc "{quoted}"'


def _nm_radio_on(ssh, iface: str, sudo_pw: str | None):
    """Sørg for at radio er tændt og interface er up (tåler at blive kørt flere gange)."""
    iface_q = quote(iface)
    
    nmcli_bin = _nmcli_bin_path(ssh) # Find nmcli path
    nmcli_cmd = nmcli_bin or "nmcli" # Brug path, fallback til navn

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


# ---- Pages -------------------------------------------------------------------

@network_bp.route("/network", endpoint="network")
def page():
    return render_template("network.html")


# ---- API: summary ------------------------------------------------------------

@network_bp.get("/network/summary")
def summary():
    try:
        ssh = _ssh()
        nmcli_bin = _nmcli_bin_path(ssh) # Find nmcli path
        nmcli_cmd = nmcli_bin or "nmcli" # Brug path, fallback til navn

        # Liste over interfaces
        _, devs, _ = ssh_exec(ssh, "ls -1 /sys/class/net | tr -d '\r'", timeout=5)
        devices = [d.strip() for d in (devs or "").splitlines() if d.strip()]

        rows = []

        # Default route (gateway + device)
        _, rdef, _ = ssh_exec(
            ssh, "ip route | awk '/^default/{print $3\" \"$5; exit}'", timeout=4
        )
        gw, gwdev = ((rdef or "").strip().split(" ", 1) + [""])[:2]

        # DNS (comma separated)
        _, dns, _ = ssh_exec(
            ssh,
            r"grep -E '^nameserver ' /etc/resolv.conf | awk '{print $2}' | paste -sd',' -",
            timeout=4,
        )

        for dev in devices:
            dev_q = quote(dev)

            # Type via navn
            if dev.startswith(("wlan", "wlp", "wlo")):
                itype = "wifi"
            elif dev.startswith(("en", "eth")) or dev.startswith("br"):
                itype = "ethernet" if dev.startswith(("en", "eth")) else "other"
            else:
                itype = "other"

            # MAC
            _, mac, _ = ssh_exec(
                ssh, f"cat /sys/class/net/{dev_q}/address 2>/dev/null", timeout=3
            )

            # IPv4
            _, ip4, _ = ssh_exec(
                ssh,
                f"ip -o -4 addr show dev {dev_q} 2>/dev/null | "
                "awk '{print $4}' | cut -d'/' -f1 | paste -sd',' -",
                timeout=3,
            )

            # Link speed (best effort)
            _, spd, _ = ssh_exec(
                ssh,
                f"(command -v ethtool >/dev/null 2>&1 && "
                f" ethtool {dev_q} 2>/dev/null | awk -F': ' '/Speed:/{{print $2; exit}}') || true",
                timeout=3,
            )

            # Wi-Fi ekstra (SSID, signal, bitrate)
            ssid = signal = bitrate = ""
            if itype == "wifi":
                if _has_nmcli(ssh):
                    _, ssid, _ = ssh_exec(
                        ssh,
                        f"{nmcli_cmd} -t -f GENERAL.CONNECTION dev show {dev_q} 2>/dev/null | "
                        "sed 's/GENERAL.CONNECTION://'",
                        timeout=3,
                    )
                if not (ssid or "").strip():
                    _, ssid, _ = ssh_exec(
                        ssh, f"iwgetid -r {dev_q} 2>/dev/null", timeout=3
                    )

                _, link, _ = ssh_exec(ssh, f"iw dev {dev_q} link 2>/dev/null", timeout=3)
                if link:
                    m = re.search(r"signal:\s*(-?\d+)", link)
                    signal = (m.group(1) + " dBm") if m else ""
                    m = re.search(r"tx bitrate:\s*([0-9.]+ [^\s\n]+)", link)
                    bitrate = m.group(1) if m else ""

            rows.append(
                {
                    "iface": dev,
                    "type": itype,
                    "mac": (mac or "").strip(),
                    "ipv4": (ip4 or "").strip(),
                    "speed": (spd or "").strip(),
                    "ssid": (ssid or "").strip(),
                    "signal": (signal or "").strip(),
                    "bitrate": (bitrate or "").strip(),
                    "default_route": dev == (gwdev or "").strip(),
                }
            )

        try:
            ssh.close()
        except Exception:
            pass

        return jsonify(
            {
                "ok": True,
                "gateway": (gw or "").strip(),
                "dns": (dns or "").strip(),
                "interfaces": rows,
            }
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---- API: Wi-Fi scan/connect/forget -----------------------------------------

@network_bp.post("/network/scan")
def scan():
    try:
        ssh = _ssh()
        s = _active()
        data = request.get_json(silent=True) or {}
        # Henter sudo password fra UI (qc-sudo) eller SSH settings (password)
        sudo_pw = data.get("sudo_pw") or s.get("password") or None

        nmcli_bin = _nmcli_bin_path(ssh) # Find nmcli path (fx /usr/bin/nmcli)

        def _unescape_nm(sv: str) -> str:
            # nmcli -t -e yes escaper tegn
            return (sv or "").replace(r"\|", "|").replace(r"\:", ":").replace(r"\\", "\\")

        # ---------- aktiv forbindelse (BSSID/SSID) ----------
        active_bssid, active_ssid = _active_bss(ssh)

        # Sørg for radio ON & iface UP
        iface = _iface_detect(ssh)
        _nm_radio_on(ssh, iface, sudo_pw) # Sender sudo_pw med

        # ---------- nmcli (primær / bedst) ----------
        def _scan_nmcli() -> list:
            if not _has_nmcli(ssh) or not nmcli_bin:
                return []
            iface_q = quote(iface)

            # Tving rescan. KUN MED SUDO, og tjek for fejl.
            # Vi fjerner redirect og || true for at SE FEJLEN.
            rescan_cmd = _sudo_cmd(sudo_pw, f"{nmcli_bin} device wifi rescan ifname {iface_q}") 
            rc_r, out_r, err_r = ssh_exec(ssh, rescan_cmd, timeout=8)
            
            # Hvis rescan fejler, gemmer vi fejlen, men prøver stadig at liste fra cache.
            # Fejlen vil blive rapporteret i slutningen af scan(), hvis der ikke findes netværk.
            if rc_r != 0:
                 # Ignorer rescan fejl her, men brug listen som den er (kan stadig være tom)
                 # Fortsæt til list for at se om cachen er god nok
                 pass

            # Prøv at liste netværk UDEN sudo (NetworkManager cacher resultatet)
            cmds_try = [
                f"{nmcli_bin} -t --separator '|' -e yes -f IN-USE,BSSID,SSID,SIGNAL,SECURITY device wifi list ifname {iface_q} || true",
                f"{nmcli_bin} -t -e yes -f IN-USE,BSSID,SSID,SIGNAL,SECURITY device wifi list ifname {iface_q} || true",
            ]

            out_all = ""
            for cmd in cmds_try:
                _, out, _ = ssh_exec(ssh, cmd, timeout=15)
                out = (out or "").strip()
                # Tjekker om output ser gyldigt ud (starter med *, yes, no, 1, 0 eller BSSID)
                if out and re.match(r'^(\*|yes|no|[01]|([0-9a-fA-F]{2}:){5})', out.lower()):
                    out_all = out
                    break
            if not out_all:
                # Hvis ingen netværk blev fundet, og rescan returnerede en fejl, 
                # tilføj rescan fejlen til output for debug.
                if rc_r != 0 and err_r.strip():
                    raise RuntimeError(f"Scan returned 0 networks. Rescan command failed: {err_r.strip()}")
                return []

            nets = []
            for raw in out_all.splitlines():
                raw = raw.strip()
                if not raw:
                    continue

                parts = raw.split("|")
                if len(parts) >= 5: # Bruger custom separator
                    inuse_raw = (parts[0] or "").strip().lower()
                    bssid = _unescape_nm(parts[1]).strip().lower()
                    ssid = _unescape_nm(parts[2]).strip()
                    try:
                        sig = int((parts[3] or "").strip())
                    except Exception:
                        sig = 0
                    sec = _unescape_nm(parts[4]).strip() or "OPEN"
                    
                    if not ssid and bssid:
                        ssid = f"<Hidden/Unknown> ({bssid[:8]})"
                    elif not ssid:
                        continue
                        
                    nets.append({
                        "in_use": inuse_raw in ("yes", "true", "1", "*"),
                        "bssid": bssid,
                        "ssid": ssid,
                        "signal": sig,
                        "security": sec,
                    })
            return nets

        # ---------- wpa_cli (sekundær) ----------
        def _scan_wpa_cli() -> list:
            wpa_bin = _which_bin(ssh, ["wpa_cli", "/sbin/wpa_cli", "/usr/sbin/wpa_cli", "/usr/bin/wpa_cli"])
            if not wpa_bin:
                return []
            iface_q = quote(iface)

            # Sikrer at grænsefladen er UP igen lige før wpa_cli bruges
            ssh_exec(ssh, _sudo_cmd(sudo_pw, f"ip link set {iface_q} up || true"), timeout=4)

            # Rescan (med/uden sudo)
            for cmd in [
                _sudo_cmd(sudo_pw, f"{wpa_bin} -i {iface_q} scan >/dev/null 2>&1 || true"),
                f"{wpa_bin} -i {iface_q} scan >/dev/null 2>&1 || true",
            ]:
                ssh_exec(ssh, cmd, timeout=6)

            out_all = ""
            for cmd in [
                _sudo_cmd(sudo_pw, f"{wpa_bin} -i {iface_q} scan_results || true"),
                f"{wpa_bin} -i {iface_q} scan_results || true",
            ]:
                _, out, _ = ssh_exec(ssh, cmd, timeout=10)
                if (out or "").strip():
                    out_all = out.strip()
                    break
            if not out_all:
                return []

            # Parsing af wpa_cli output
            nets = []
            lines = [ln for ln in out_all.splitlines() if not ln.startswith("Selected interface") and ln.strip() != "OK"]
            if lines and lines[0].lower().startswith("bssid"):
                lines = lines[1:]
            for line in lines:
                c = line.split("\t")
                if len(c) < 5:
                    continue
                bssid = (c[0] or "").strip().lower()
                try:
                    sig = int(c[2])
                except Exception:
                    sig = 0
                flags = c[3]
                ssid_raw = (c[4] or "").strip()
                
                # NY FIX: Forsøg at afkode hex-SSID
                ssid = ssid_raw
                try:
                    if re.fullmatch(r"[0-9a-fA-F]+", ssid_raw) and len(ssid_raw) % 2 == 0 and len(ssid_raw) < 10:
                        decoded_ssid = bytes.fromhex(ssid_raw).decode('utf-8', 'ignore').strip()
                        if decoded_ssid and all(32 <= ord(ch) <= 126 or ord(ch) >= 160 for ch in decoded_ssid):
                            ssid = decoded_ssid
                        elif not decoded_ssid and bssid:
                            ssid = f"<Hidden/Unknown> ({bssid[:8]})"
                except ValueError:
                    pass
                except Exception:
                    if bssid and (not ssid or (re.fullmatch(r"[0-9a-fA-F]+", ssid) and len(ssid) < 10)):
                        ssid = f"<Hidden/Unknown> ({bssid[:8]})"
                
                if bssid and re.fullmatch(r"[0-9a-fA-F]+", ssid) and len(ssid) < 10:
                     ssid = f"<Hidden/Unknown> (Raw Hex: {ssid})"
                
                if not ssid:
                     continue

                sec = "OPEN"
                if "WPA" in flags and "RSN" in flags:
                    sec = "WPA/WPA2/WPA3"
                elif "WPA" in flags:
                    sec = "WPA"
                elif "RSN" in flags:
                    sec = "WPA2/WPA3"
                
                nets.append({
                    "in_use": False,
                    "bssid": bssid,
                    "ssid": ssid,
                    "signal": sig,
                    "security": sec,
                })
            return nets

        # ---------- iw (fallback) ----------
        def _scan_iw() -> list:
            iw_bin = _which_bin(ssh, ["iw", "/usr/sbin/iw", "/sbin/iw"])
            if not iw_bin:
                return []
            iface_q = quote(iface)
            out_all = ""
            for cmd in [
                _sudo_cmd(sudo_pw, f"{iw_bin} dev {iface_q} scan 2>/dev/null"),
                f"{iw_bin} dev {iface_q} scan 2>/dev/null",
            ]:
                _, out, _ = ssh_exec(ssh, cmd, timeout=20)
                if (out or "").strip():
                    out_all = out.strip()
                    break
            if not out_all:
                return []

            # Parsing af iw output
            nets = []
            cur = {"bssid": "", "ssid": "", "signal": 0, "security": "OPEN"}
            for ln in out_all.splitlines():
                m = re.match(r"^BSS\s+([0-9a-fA-F:]{17})", ln.strip())
                if m:
                    if cur["bssid"]:
                        if not cur["ssid"] and cur["bssid"]:
                             cur["ssid"] = f"<Hidden/Unknown> ({cur['bssid'][:8]})"
                        
                        if cur["ssid"] or cur["bssid"]:
                             nets.append({"in_use": False, **cur})
                    
                    cur = {"bssid": m.group(1).lower(), "ssid": "", "signal": 0, "security": "OPEN"}
                    continue
                m = re.search(r"signal:\s*(-?\d+)", ln)
                if m:
                    try:
                        cur["signal"] = int(m.group(1))
                    except Exception:
                        pass
                m = re.search(r"SSID:\s*(.*)$", ln)
                if m:
                    cur["ssid"] = m.group(1).strip()
                if "RSN:" in ln or "WPA:" in ln:
                    cur["security"] = "WPA/WPA2/WPA3"
            
            # Tilføj den sidste BSS
            if cur["bssid"]:
                if not cur["ssid"] and cur["bssid"]:
                     cur["ssid"] = f"<Hidden/Unknown> ({cur['bssid'][:8]})"

                if cur["ssid"] or cur["bssid"]:
                    nets.append({"in_use": False, **cur})
            return nets

        # --- Scan og merge ---
        try:
            res_nm = _scan_nmcli()
        except RuntimeError as e:
            # Videresend RuntimeError fra _scan_nmcli
            raise e

        # Hvis nmcli virker, behøver vi ikke wpa_cli/iw, da de ofte har problemer med SSID.
        res_wp = _scan_wpa_cli() if not res_nm else []
        res_iw = _scan_iw() if not (res_nm or res_wp) else []

        merged = {}
        for n in (res_nm + res_wp + res_iw):
            key = n.get("bssid") or f"ssid::{n.get('ssid','')}"
            cur = merged.get(key)
            if cur is None:
                merged[key] = dict(n)
            else:
                # Beholder den bedste SSID og signal.
                if (n.get("signal") or 0) > (cur.get("signal") or 0):
                    cur["signal"] = n.get("signal") or 0
                
                # Hvis n har et bedre (ikke-skjult) navn, brug det
                is_cur_hidden = cur.get("ssid", "").startswith("<Hidden/Unknown>")
                is_n_hidden = n.get("ssid", "").startswith("<Hidden/Unknown>")

                if n.get("ssid") and not is_n_hidden:
                    cur["ssid"] = n["ssid"]
                elif is_cur_hidden and n.get("ssid") and not n.get("ssid").startswith("Raw Hex"):
                     cur["ssid"] = n["ssid"]
                
                # Opdater altid sikkerhed, da wpa_cli kan have bedre info her
                if n.get("security") and n["security"] != "OPEN":
                    cur["security"] = n["security"]
                
                if n.get("in_use"):
                    cur["in_use"] = True
                if not cur.get("bssid") and n.get("bssid"):
                    cur["bssid"] = n["bssid"]

        nets = [v for v in merged.values() if v.get("ssid") or v.get("bssid")]

        # Markér aktiv forbindelse
        active_bssid = (active_bssid or "").lower()
        if active_bssid:
            for v in nets:
                if (v.get("bssid") or "").lower() == active_bssid:
                    v["in_use"] = True
                    if active_ssid and not v.get("ssid"):
                        v["ssid"] = active_ssid
        if active_ssid:
            for v in nets:
                if v.get("ssid") == active_ssid:
                    v["in_use"] = True

        nets.sort(key=lambda x: ((0 if x.get("in_use") else 1), -(x.get("signal") or 0)))

        try:
            ssh.close()
        except Exception:
            pass

        if not nets and not nmcli_bin:
             return jsonify({
                "ok": False,
                "error": "nmcli command not found on remote system. Cannot perform Wi-Fi scan."
            }), 200
        if not nets:
            return jsonify({
                "ok": False,
                "error": "Scan returned 0 networks. Likely Wi-Fi radio is off, or the rescan command failed. Try providing sudo password."
            }), 200

        return jsonify({"ok": True, "networks": nets})
    except Exception as e:
        # Fanger også RuntimeError fra _scan_nmcli
        return jsonify({"ok": False, "error": str(e)}), 200


@network_bp.post("/network/connect")
def connect():
    try:
        data = request.get_json(force=True) or {}
        ssid = (data.get("ssid") or "").strip()
        pw = data.get("password") or ""
        hidden = bool(data.get("hidden"))
        # Henter sudo password fra UI (qc-sudo) eller SSH settings (password)
        sudo_pw = data.get("sudo_pw") or _active().get("password")

        if not ssid:
            return jsonify({"ok": False, "error": "Missing SSID"}), 400

        ssh = _ssh()
        nmcli_bin = _nmcli_bin_path(ssh) # Find nmcli path
        nmcli_cmd = nmcli_bin or "nmcli"

        def sudo(cmd: str) -> str:
            return _sudo_cmd(sudo_pw, cmd) # Sender sudo_pw med

        if _has_nmcli(ssh):
            # Slet evt. eksisterende profil
            ssh_exec(
                ssh,
                sudo(f'{nmcli_cmd} -t -f NAME con | grep -Fx "{ssid}" && {nmcli_cmd} con del "{ssid}" || true'),
                timeout=10,
            )

            if pw:
                cmd = f'{nmcli_cmd} dev wifi connect "{ssid}" password "{pw}" ' + ("hidden yes " if hidden else "")
            else:
                cmd = f'{nmcli_cmd} dev wifi connect "{ssid}" ' + ("hidden yes " if hidden else "")

            rc, out, err = ssh_exec(ssh, sudo(cmd), timeout=40)
            ok = rc == 0
            msg = out or err or ""
        else:
            iface = _iface_detect(ssh)
            iface_q = quote(iface)
            wpa_bin = _which_bin(ssh, ["wpa_cli", "/sbin/wpa_cli", "/usr/sbin/wpa_cli", "/usr/bin/wpa_cli"]) or "wpa_cli"
            _nm_radio_on(ssh, iface, sudo_pw)
            _, netid, _ = ssh_exec(ssh, sudo(f"{wpa_bin} -i {iface_q} add_network"), timeout=5)
            netid = (netid or "0").strip()

            ssh_exec(ssh, sudo(f'{wpa_bin} -i {iface_q} set_network {netid} ssid \'"{ssid}"\''), timeout=5)
            if pw:
                ssh_exec(ssh, sudo(f'{wpa_bin} -i {iface_q} set_network {netid} psk \'"{pw}"\''), timeout=5)
            else:
                ssh_exec(ssh, sudo(f"{wpa_bin} -i {iface_q} set_network {netid} key_mgmt NONE"), timeout=5)

            ssh_exec(ssh, sudo(f"{wpa_bin} -i {iface_q} enable_network {netid}"), timeout=5)
            ssh_exec(ssh, sudo(f"{wpa_bin} -i {iface_q} save_config"), timeout=5)
            rc, out, err = ssh_exec(ssh, sudo(f"{wpa_bin} -i {iface_q} reconnect"), timeout=10)
            ok = rc == 0
            msg = out or err or ""

        try:
            ssh.close()
        except Exception:
            pass

        return jsonify({"ok": ok, "message": msg.strip()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@network_bp.post("/network/forget")
def forget():
    try:
        data = request.get_json(force=True) or {}
        ssid = (data.get("ssid") or "").strip()
        if not ssid:
            return jsonify({"ok": False, "error": "Missing SSID"}), 400

        ssh = _ssh()
        # Henter sudo password fra UI (qc-sudo) eller SSH settings (password)
        sudo_pw = data.get("sudo_pw") or _active().get("password")
        nmcli_bin = _nmcli_bin_path(ssh) # Find nmcli path
        nmcli_cmd = nmcli_bin or "nmcli"

        def sudo(cmd: str) -> str:
            return _sudo_cmd(sudo_pw, cmd) # Sender sudo_pw med

        if _has_nmcli(ssh):
            rc, out, err = ssh_exec(ssh, sudo(f'{nmcli_cmd} con delete id "{ssid}"'), timeout=10)
            ok = rc == 0
            msg = out or err or ""
        else:
            iface = _iface_detect(ssh)
            iface_q = quote(iface)
            wpa_bin = _which_bin(ssh, ["wpa_cli", "/sbin/wpa_cli", "/usr/sbin/wpa_cli", "/usr/bin/wpa_cli"]) or "wpa_cli"

            rc, out, _ = ssh_exec(ssh, sudo(f"{wpa_bin} -i {iface_q} list_networks"), timeout=6)
            for line in (out or "").splitlines()[1:]:
                c = line.split("\t")
                if len(c) >= 2 and c[1] == ssid:
                    ssh_exec(ssh, sudo(f"{wpa_bin} -i {iface_q} remove_network {c[0]}"), timeout=5)
                    ssh_exec(ssh, sudo(f"{wpa_bin} -i {iface_q} save_config"), timeout=5)
            ok = True
            msg = "Removed (if matched)."

        try:
            ssh.close()
        except Exception:
            pass

        return jsonify({"ok": ok, "message": msg.strip()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500