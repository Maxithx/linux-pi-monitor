from shlex import quote
from flask import render_template, jsonify

from . import network_bp
from routes.common.ssh_utils import ssh_exec
from .helpers import _ssh, _has_nmcli, _nmcli_bin_path
from .dns_helpers import _dns_status


@network_bp.route("/network", endpoint="network")
def page():
    return render_template("network.html")


@network_bp.get("/network/summary")
def summary():
    try:
        ssh = _ssh()
        nmcli_bin = _nmcli_bin_path(ssh)  # Find nmcli path
        nmcli_cmd = nmcli_bin or "nmcli"  # Brug path, fallback til navn

        # Liste over interfaces
        _, devs, _ = ssh_exec(ssh, "ls -1 /sys/class/net | tr -d '\r'", timeout=5)
        devices = [d.strip() for d in (devs or "").splitlines() if d.strip()]

        rows = []

        # Default route (gateway + device)
        _, rdef, _ = ssh_exec(
            ssh, "ip route | awk '/^default/{print $3\" \"$5; exit}'", timeout=4
        )
        gw, gwdev = ((rdef or "").strip().split(" ", 1) + [""])[:2]

        # DNS (comma separated) - for back-compat in summary (OPDATERET)
        _, dns_legacy, _ = ssh_exec(
            ssh,
            r"grep -E '^nameserver ' /etc/resolv.conf | awk '{print $2}' | paste -sd',' -",
            timeout=4,
        )

        # New DNS status (NYT)
        dns_status = _dns_status(ssh)

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

            # Link speed (best effort) — ethtool may say "Unknown!" for Wi‑Fi/virtual ifaces
            _, spd, _ = ssh_exec(
                ssh,
                f"(command -v ethtool >/dev/null 2>&1 && "
                f" ethtool {dev_q} 2>/dev/null | awk -F': ' '/Speed:/{{print $2; exit}}') || true",
                timeout=3,
            )
            # Link-state hints (ethernet): operstate/carrier
            _, operstate, _ = ssh_exec(ssh, f"cat /sys/class/net/{dev_q}/operstate 2>/dev/null", timeout=2)
            _, carrier, _ = ssh_exec(ssh, f"cat /sys/class/net/{dev_q}/carrier 2>/dev/null", timeout=2)

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
                    import re as _re

                    m = _re.search(r"signal:\s*(-?\d+)", link)
                    signal = (m.group(1) + " dBm") if m else ""
                    m = _re.search(r"tx bitrate:\s*([0-9.]+ [^\s\n]+)", link)
                    bitrate = m.group(1) if m else ""

            # Prefer a clean display speed:
            #  - Treat ethtool "Unknown!" as empty
            #  - Wi-Fi: fall back to bitrate when empty
            #  - Others: show "-" if empty
            spd_disp = (spd or "").strip()
            if spd_disp.lower().startswith("unknown"):
                spd_disp = ""
            if itype == "wifi":
                if not spd_disp:
                    spd_disp = (bitrate or "").strip() or "-"
            elif itype == "ethernet":
                link_up = ((operstate or "").strip() == "up") and ((carrier or "").strip() == "1")
                if not link_up or not spd_disp:
                    spd_disp = "-"
            else:
                if not spd_disp:
                    spd_disp = "-"

            rows.append(
                {
                    "iface": dev,
                    "type": itype,
                    "mac": (mac or "").strip(),
                    "ipv4": (ip4 or "").strip(),
                    "speed": spd_disp,
                    "ssid": (ssid or "").strip(),
                    "signal": (signal or "").strip(),
                    "bitrate": (bitrate or "").strip(),
                    "default_route": dev == (gwdev or "").strip(),
                    "is_dns_iface": dev == dns_status["iface"],  # NYT felt
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
                "dns": (dns_legacy or "").strip(),  # Tilbagekompatibilitet
                "interfaces": rows,
                "dns_status": dns_status,  # NY DNS status
            }
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
