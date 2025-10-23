from routes.common.ssh_utils import ssh_exec, ssh_exec_shell


def read_os_release(ssh) -> dict:
    rc, out, _ = ssh_exec_shell(ssh, "cat /etc/os-release 2>/dev/null || true", timeout=3)
    data = {}
    if out:
        for ln in out.splitlines():
            if '=' in ln:
                k, v = ln.split('=', 1)
                v = v.strip().strip('"')
                data[k.strip()] = v
    return data
