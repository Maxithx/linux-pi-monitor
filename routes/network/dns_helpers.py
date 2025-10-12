import re
from shlex import quote

from ..ssh_utils import ssh_exec
from .helpers import _nmcli_bin_path, _has_nmcli


def _default_iface(ssh) -> str:
    """Return default-route interface (e.g., wlp3s0 or eth0)."""
    _, out, _ = ssh_exec(ssh, "ip route | awk '/^default/ {print $5; exit}'", timeout=4)
    return (out or "").strip()


def _active_connection_for_iface(ssh, iface: str) -> str:
    """Return active NetworkManager connection name for iface (empty if none)."""
    nmcli_bin = _nmcli_bin_path(ssh)
    if not nmcli_bin:
        return ""
    # nmcli -t -f NAME,DEVICE connection show --active | grep ":<iface>$" | cut -d: -f1
    cmd = (
        f"{nmcli_bin} -t -f NAME,DEVICE connection show --active | "
        f"grep -F ':{iface}' || true"
    )
    _, out, _ = ssh_exec(ssh, cmd, timeout=4)
    line = (out or "").strip().splitlines()
    if not line:
        return ""
    first = line[0]
    if ":" in first:
        # Ensure we only match on the interface name at the end
        if first.endswith(f":{iface}") or first.endswith(f":\"{iface}\""):
            return first.split(":", 1)[0]
    return ""


def _dns_status(ssh) -> dict:
    """Return dict with stub, upstream[], method, iface, connection."""
    iface = _default_iface(ssh)
    # Stub: what resolv.conf points to (often 127.0.0.53)
    _, stub, _ = ssh_exec(ssh, r"grep -E '^nameserver ' /etc/resolv.conf | awk '{print $2}' | paste -sd',' -", timeout=3)
    stub_str = (stub or "").strip()
    stub_first = (stub_str.split(",")[0] if stub_str else "")

    # Upstream via systemd-resolved (preferred)
    _, rs, _ = ssh_exec(ssh, "resolvectl status 2>/dev/null || systemd-resolve --status 2>/dev/null || true", timeout=6)
    upstream = []
    method = "unknown"
    if rs:
        method = "systemd-resolved"
        # Try to parse "Current DNS Server" (global) or "DNS Servers" under link
        # Look for the relevant section (Link, Global, etc.) and then the DNS list
        in_iface_section = False
        for ln in rs.splitlines():
            ln = ln.strip()
            # Start of a link section (like "Link 2 (eth0)")
            if iface and re.match(r"^Link \d+ \(" + re.escape(iface) + r"\)", ln):
                in_iface_section = True
            elif re.match(r"^Link \d+ \(", ln) and ln.startswith("Link"):
                in_iface_section = False  # Exiting a different link section

            if ln.startswith("Current DNS Server:"):
                # Global setting, but resolved often reports current as the "best" one
                val = ln.split(":", 1)[1].strip()
                if val and val != "127.0.0.53" and val not in upstream:
                    upstream.append(val)
            elif in_iface_section and ln.startswith("DNS Servers:"):
                # DNS list for the default interface
                rest = ln.split(":", 1)[1].strip()
                if rest:
                    for v in rest.replace(",", " ").split():
                        # Basic IP validation
                        if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", v) or ":" in v:
                            if v != "127.0.0.53" and v not in upstream:
                                upstream.append(v)
            elif ln.startswith("DNS Servers:"):
                # Fallback to general DNS servers list if interface specific failed or if it's "Global"
                rest = ln.split(":", 1)[1].strip()
                if rest:
                    for v in rest.replace(",", " ").split():
                        if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", v) or ":" in v:
                            if v != "127.0.0.53" and v not in upstream:
                                upstream.append(v)

        upstream = list(dict.fromkeys(upstream))  # unique, order

    # If no upstream parsed, fall back to resolv.conf nameservers (minus 127.0.0.53)
    if not upstream:
        _, ns, _ = ssh_exec(ssh, r"grep -E '^nameserver ' /etc/resolv.conf | awk '{print $2}'", timeout=3)
        for v in (ns or "").splitlines():
            v = v.strip()
            if v and v != "127.0.0.53":
                upstream.append(v)

    conn = _active_connection_for_iface(ssh, iface) if iface and _has_nmcli(ssh) else ""
    return {
        "stub": stub_first or "",
        "upstream": upstream,
        "method": method,
        "iface": iface,
        "connection": conn,
    }


def _set_dns_nm(ssh, sudo_pw, iface, conn_name, servers, auto):
    """
    Apply DNS via NetworkManager WITHOUT disconnect:
      - modify connection properties
      - nmcli connection reload
      - nmcli device reapply <iface>
      - resolvectl flush-caches
    Falls back to down/up only if reapply fails.
    """
    from .helpers import _sudo_cmd

    nm = _nmcli_bin_path(ssh) or "nmcli"
    out_all, rc_last = [], 0

    # 1) Modify connection properties
    if auto:
        cmds = [
            _sudo_cmd(sudo_pw, f'{nm} connection modify "{conn_name}" ipv4.ignore-auto-dns no'),
            _sudo_cmd(sudo_pw, f'{nm} connection modify "{conn_name}" ipv4.dns ""'),
        ]
    else:
        dns_list = " ".join(servers or [])
        cmds = [
            _sudo_cmd(sudo_pw, f'{nm} connection modify "{conn_name}" ipv4.ignore-auto-dns yes'),
            _sudo_cmd(sudo_pw, f'{nm} connection modify "{conn_name}" ipv4.dns "{dns_list}"'),
        ]

    for c in cmds:
        rc, out, err = ssh_exec(ssh, c, timeout=15)
        rc_last = rc_last or rc
        out_all.append((out or "") + (("\n" + err) if err else ""))

    # 2) Reload connection definitions
    rc1, out1, err1 = ssh_exec(ssh, _sudo_cmd(sudo_pw, f"{nm} connection reload || {nm} general reload || true"), timeout=10)
    rc_last = rc_last or rc1
    out_all.append((out1 or "") + (("\n" + err1) if err1 else ""))

    # 3) Try non-disruptive reapply on the device
    rc2, out2, err2 = ssh_exec(ssh, _sudo_cmd(sudo_pw, f"{nm} device reapply {quote(iface)}"), timeout=15)
    out_all.append((out2 or "") + (("\n" + err2) if err2 else ""))

    # 4) Flush resolver cache (harmless on systems without resolved)
    rc3, out3, err3 = ssh_exec(ssh, _sudo_cmd(sudo_pw, "resolvectl flush-caches || true"), timeout=6)
    out_all.append((out3 or "") + (("\n" + err3) if err3 else ""))

    # 5) If reapply failed, do a minimal fallback: brief up (last resort)
    if rc2 != 0:
        rc4, out4, err4 = ssh_exec(
            ssh,
            _sudo_cmd(sudo_pw, f'{nm} connection up "{conn_name}"'),
            timeout=40,
        )
        rc_last = rc_last or rc4
        out_all.append((out4 or "") + (("\n" + err4) if err4 else ""))

    return rc_last, "\n".join(out_all).strip(), ""


def _set_dns_resolvectl(ssh, sudo_pw: str | None, iface: str, servers: list[str] | None, auto: bool) -> tuple[int, str, str]:
    from .helpers import _sudo_cmd

    if not iface:
        return 1, "No active interface", ""
    if auto:
        cmd = _sudo_cmd(sudo_pw, f"resolvectl revert {quote(iface)} || true")
        return ssh_exec(ssh, cmd, timeout=12)
    else:
        dns = " ".join(servers or [])
        # resolvectl dns <iface> 1.1.1.1 1.0.0.1
        cmd = _sudo_cmd(sudo_pw, f"resolvectl dns {quote(iface)} {dns} && resolvectl flush-caches || true")
        return ssh_exec(ssh, cmd, timeout=20)
