import re
from shlex import quote
from flask import jsonify, request

from . import network_bp
from routes.common.ssh_utils import ssh_exec
from .helpers import (
    _ssh,
    _active,
    _has_nmcli,
    _iface_detect,
    _which_bin,
    _nmcli_bin_path,
    _active_bss,
    _sudo_cmd,
    _nm_radio_on,
)


@network_bp.post("/network/scan")
def scan():
    try:
        ssh = _ssh()
        s = _active()
        data = request.get_json(silent=True) or {}
        # Henter sudo password fra UI (qc-sudo) eller SSH settings (password)
        sudo_pw = data.get("sudo_pw") or s.get("password") or None

        nmcli_bin = _nmcli_bin_path(ssh)  # Find nmcli path (fx /usr/bin/nmcli)

        def _unescape_nm(sv: str) -> str:
            # nmcli -t -e yes escaper tegn
            return (sv or "").replace(r"\|", "|").replace(r"\:", ":").replace(r"\\", "\\")

        # ---------- aktiv forbindelse (BSSID/SSID) ----------
        active_bssid, active_ssid = _active_bss(ssh)
        active_nm_conn = ""

        # Sørg for radio ON & iface UP
        iface = _iface_detect(ssh)
        _nm_radio_on(ssh, iface, sudo_pw)  # Sender sudo_pw med
        if _has_nmcli(ssh) and nmcli_bin:
            _, _nm, _ = ssh_exec(ssh, f"{nmcli_bin} -t -f GENERAL.CONNECTION dev show {quote(iface)} 2>/dev/null | sed 's/GENERAL.CONNECTION://'", timeout=3)
            active_nm_conn = (_nm or "").strip()


        # ---------- nmcli (primær / bedst) ----------
        def _scan_nmcli() -> list:
            if not _has_nmcli(ssh) or not nmcli_bin:
                return []
            iface_q = quote(iface)

            # Tving rescan. KUN MED SUDO, og tjek for fejl.
            # Vi fjerner redirect og || true for at SE FEJLEN.
            rescan_cmd = _sudo_cmd(sudo_pw, f"{nmcli_bin} device wifi rescan ifname {iface_q}")
            rc_r, out_r, err_r = ssh_exec(ssh, rescan_cmd, timeout=8)
            # allow nmcli to refresh cache
            ssh_exec(ssh, "sleep 1", timeout=2)

            # Hvis rescan fejler, gemmer vi fejlen, men prøver stadig at liste fra cache.
            # Fejlen vil blive rapporteret i slutningen af scan(), hvis der ikke findes netværk.
            if rc_r != 0:
                # Ignorer rescan fejl her, men brug listen som den er (kan stadig være tom)
                # Fortsæt til list for at se om cachen er god nok
                pass

            # Prøv at liste netværk UDEN sudo (NetworkManager cacher resultatet)
            cmds_try = [
                f"{nmcli_bin} -t --separator '|' -e yes -f IN-USE,BSSID,SSID,SIGNAL,SECURITY device wifi list ifname {iface_q} --rescan yes || true",
                f"{nmcli_bin} -t -e yes -f IN-USE,BSSID,SSID,SIGNAL,SECURITY device wifi list ifname {iface_q} --rescan yes || true",
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

            # Retry while result looks incomplete (scan warming up)
            attempts = 0
            def _count_lines(txt: str) -> int:
                return len([ln for ln in (txt or '').splitlines() if ln.strip()])
            while (not out_all or _count_lines(out_all) <= 1) and attempts < 3:
                ssh_exec(ssh, "sleep 1", timeout=2)
                out_try = ""
                for cmd in cmds_try:
                    _, out, _ = ssh_exec(ssh, cmd, timeout=15)
                    out = (out or "").strip()
                    if out and re.match(r'^(\*|yes|no|[01]|([0-9a-fA-F]{2}:){5})', out.lower()):
                        out_try = out
                        break
                if out_try:
                    out_all = out_try
                attempts += 1

            nets = []
            for raw in out_all.splitlines():
                raw = raw.strip()
                if not raw:
                    continue

                parts = raw.split("|")
                if len(parts) >= 5:  # Bruger custom separator
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

                    is_connected = (
                        inuse_raw in ("yes", "true", "1", "*")
                        or (active_bssid and bssid and bssid == active_bssid)
                        or (active_ssid and ssid and ssid.strip().lower() == active_ssid.strip().lower())
                        or (active_nm_conn and ssid and ssid.strip().lower() == active_nm_conn.strip().lower())
                    )
                    nets.append({
                        "in_use": bool(is_connected),
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
            lines = [
                ln
                for ln in out_all.splitlines()
                if not ln.startswith("Selected interface") and ln.strip() != "OK"
            ]
            if lines and lines[0].lower().startswith("bssid"):
                lines = lines[1:]
            for line in lines:
                c = line.split("\t")
                if len(c) < 5:
                    continue
                bssid = (c[0] or "").strip().lower()
                try:
                    sig = int((c[2] or "0").strip())
                except Exception:
                    sig = 0
                ssid = (c[4] or "").strip()
                sec = "WPA/WPA2/WPA3" if ("WPA" in (c[3] or "") or "RSN" in (c[3] or "")) else "OPEN"
                if not ssid and bssid:
                    ssid = f"<Hidden/Unknown> ({bssid[:8]})"
                elif not ssid:
                    continue
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
            iface_q = quote(iface)
            # iw dev <iface> scan output parsing
            _, out, _ = ssh_exec(ssh, _sudo_cmd(sudo_pw, f"iw dev {iface_q} scan 2>/dev/null || true"), timeout=12)
            if not (out or "").strip():
                return []
            nets = []
            cur = {"bssid": "", "ssid": "", "signal": 0, "security": "OPEN"}
            for ln in out.splitlines():
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
        if active_nm_conn:
            for v in nets:
                if (v.get("ssid") or "").strip().lower() == (active_nm_conn or "").strip().lower():
                    v["in_use"] = True
        if active_ssid:
            for v in nets:
                if (v.get("ssid") or "").strip().lower() == (active_ssid or "").strip().lower():
                    v["in_use"] = True
        nets.sort(key=lambda x: ((0 if x.get("in_use") else 1), -(x.get("signal") or 0)))

        try:
            ssh.close()
        except Exception:
            pass

        if not nets and not nmcli_bin:
            return jsonify(
                {
                    "ok": False,
                    "error": "nmcli command not found on remote system. Cannot perform Wi-Fi scan.",
                }
            ), 200
        if not nets:
            return jsonify(
                {
                    "ok": False,
                    "error": "Scan returned 0 networks. Likely Wi-Fi radio is off, or the rescan command failed. Try providing sudo password.",
                }
            ), 200

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
        nmcli_bin = _nmcli_bin_path(ssh)  # Find nmcli path
        nmcli_cmd = nmcli_bin or "nmcli"

        def sudo(cmd: str) -> str:
            return _sudo_cmd(sudo_pw, cmd)  # Sender sudo_pw med

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
        nmcli_bin = _nmcli_bin_path(ssh)  # Find nmcli path
        nmcli_cmd = nmcli_bin or "nmcli"

        def sudo(cmd: str) -> str:
            return _sudo_cmd(sudo_pw, cmd)  # Sender sudo_pw med

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














