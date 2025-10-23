# utils.py â€” robust CPU usage via /proc/stat (awk), SMART via /usr/sbin/smartctl
import os
import re
import json
import time
import socket
import threading
import paramiko

# --------- active profile loading ---------
def _profiles_path_from_env() -> str | None:
    return os.environ.get("RPI_MONITOR_PROFILES_PATH")

def _load_active_profile() -> dict:
    path = _profiles_path_from_env()
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        pid = data.get("active_profile_id")
        prof = next((p for p in data.get("profiles", []) if p.get("id") == pid), None)
        if not prof:
            return {}
        return {
            "host": (prof.get("pi_host") or "").strip(),
            "user": (prof.get("pi_user") or "").strip(),
            "auth_method": (prof.get("auth_method") or "key").strip(),
            "key_path": (prof.get("ssh_key_path") or "").strip(),
            "password": prof.get("password") or "",
        }
    except Exception:
        return {}

# --------- SSH manager ---------
class SSHManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._client: paramiko.SSHClient | None = None
        self._fp = None
        self.connect_timeout = 6
        self.auth_timeout = 6
        self.banner_timeout = 6
        self.read_timeout = 6
        self.keepalive_secs = 10

    def _finger(self, s): return (s.get("host"), s.get("user"), s.get("auth_method"), s.get("key_path"))
    def _need_reconnect(self, s): return (self._client is None) or (self._fp != self._finger(s))
    def _close(self):
        if self._client:
            try: self._client.close()
            except: pass
        self._client = None

    def _connect(self, s):
        self._close()
        if not s.get("host") or not s.get("user"):
            raise RuntimeError("SSH settings incomplete")
        cli = paramiko.SSHClient()
        cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kw = dict(
            hostname=s["host"], username=s["user"],
            timeout=self.connect_timeout, auth_timeout=self.auth_timeout,
            banner_timeout=self.banner_timeout, look_for_keys=False, allow_agent=False,
        )
        if s.get("auth_method") == "password":
            if not s.get("password"): raise RuntimeError("Password auth selected but no password set")
            cli.connect(password=s["password"], **kw)
        else:
            kp = s.get("key_path")
            if not kp or not os.path.isfile(kp): raise RuntimeError(f"SSH key not found: {kp!r}")
            key = None
            for loader in (paramiko.RSAKey, getattr(paramiko,"Ed25519Key",None), paramiko.ECDSAKey):
                if loader is None: continue
                try:
                    key = loader.from_private_key_file(kp); break
                except: pass
            if key is None: raise RuntimeError("Unsupported/invalid SSH private key")
            cli.connect(pkey=key, **kw)
        try:
            tr = cli.get_transport()
            if tr: tr.set_keepalive(self.keepalive_secs)
        except: pass
        self._client = cli
        self._fp = self._finger(s)

    def exec(self, command: str) -> str:
        with self._lock:
            s = _load_active_profile()
            if not s: return ""
            try:
                if self._need_reconnect(s): self._connect(s)
                _, out, _ = self._client.exec_command(command, timeout=self.read_timeout)
                try: out.channel.settimeout(self.read_timeout)
                except: pass
                return out.read().decode(errors="replace").strip()
            except (socket.timeout, paramiko.ssh_exception.SSHException):
                try:
                    self._connect(s)
                    _, out, _ = self._client.exec_command(command, timeout=self.read_timeout)
                    try: out.channel.settimeout(self.read_timeout)
                    except: pass
                    return out.read().decode(errors="replace").strip()
                except: return ""
            except: return ""

_ssh = SSHManager()
def ssh_run(cmd: str) -> str: return _ssh.exec(cmd)

# --------- CPU model / freq ---------
def _clean_cpu_name(raw: str) -> str:
    if not raw: return ""
    name = re.sub(r'\s*@\s*[\d\.]+\s*([GM]Hz)?\s*$', '', raw.strip())
    return re.sub(r'\s+', ' ', name).strip()

def _to_ghz(val: str) -> str:
    try:
        v = float(str(val).strip())
        return str(round(v/1000.0, 2))
    except Exception:
        return ""

def _fmt_freq(cur_mhz: str, min_mhz: str, max_mhz: str) -> str:
    """Format CPU frequency favoring dynamic current MHz.

    Prefer current MHz (scaled) when available; fallback to max MHz; if not
    available, display min/max in GHz. Avoid question marks to keep UI clean.
    """
    try:
        cur = float(str(cur_mhz).strip())
        if cur > 0:
            return f"{int(round(cur))} MHz"
    except Exception:
        pass
    try:
        mx = float(str(max_mhz).strip())
        if mx > 0:
            return f"{int(round(mx))} MHz"
    except Exception:
        pass
    ghz_min = _to_ghz(min_mhz)
    ghz_max = _to_ghz(max_mhz)
    if ghz_min and ghz_max:
        return f"{ghz_min} / {ghz_max} GHz"
    return ""

def parse_cpu_info():
    # Try lscpu JSON first (fast, structured)
    js = ssh_run("LC_ALL=C lscpu -J 2>/dev/null")
    try:
        if js:
            obj = json.loads(js)
            fields = {e.get("field","").strip(): e.get("data","").strip() for e in obj.get("lscpu",[])}
            name = _clean_cpu_name(fields.get("Model name:") or fields.get("Model name") or "")
            cores = (fields.get("CPU(s):") or "").strip()
            cur_mhz = (fields.get("CPU MHz:") or "").strip()
            max_mhz = (fields.get("CPU max MHz:") or fields.get("CPU max MHz") or "").strip()
            min_mhz = (fields.get("CPU min MHz:") or fields.get("CPU min MHz") or "").strip()
            freq = _fmt_freq(cur_mhz, min_mhz, max_mhz)
            return (name or "Unknown CPU", cores, freq)
    except Exception:
        pass

    # Fallbacks (plain lscpu/grep)
    name = ssh_run("LC_ALL=C lscpu | sed -nr '/Model name/ s/.*:\\s*(.*) @ .*/\\1/p'").strip() \
        or ssh_run("LC_ALL=C lscpu | grep -m1 'Model name' | cut -d: -f2- | awk '{$1=$1}1'").strip()
    name = _clean_cpu_name(name) or \
           _clean_cpu_name(ssh_run("grep -m1 'model name' /proc/cpuinfo | awk -F: '{print $2}'").strip())
    cores = ssh_run("nproc").strip()

    cur_mhz = ssh_run("LC_ALL=C lscpu | grep -m1 'CPU MHz' | awk -F: '{print $2}'").strip()
    max_mhz = ssh_run("LC_ALL=C lscpu | grep -m1 'CPU max MHz' | awk -F: '{print $2}'").strip()
    min_mhz = ssh_run("LC_ALL=C lscpu | grep -m1 'CPU min MHz' | awk -F: '{print $2}'").strip()
    freq = _fmt_freq(cur_mhz, min_mhz, max_mhz)

    return (name or "Unknown CPU", cores, freq)

# --------- CPU usage: /proc/stat (awk) â†’ mpstat â†’ top ---------
def _cpu_usage_via_procstat() -> float | None:
    """Compute CPU usage using /proc/stat across two samples (~200ms).

    Previous version sometimes read different lines (cpu vs cpu0) and relied on
    awk NF, which led to incorrect 100% results. This version explicitly reads
    the aggregated 'cpu ' line twice and sums known fields.
    """
    cmd = (
        "awk '"
        "function readcpu(arr){"
        "  while ((getline line < \"/proc/stat\") > 0) {"
        "    if (substr(line,1,4) == \"cpu \") { split(line, arr); close(\"/proc/stat\"); return 1 }"
        "  }"
        "  close(\"/proc/stat\"); return 0"
        "}"
        "BEGIN{" 
        "  if (!readcpu(a)) { print \"\"; exit }"
        "  t0=a[2]+a[3]+a[4]+a[5]+a[6]+a[7]+a[8]+a[9]; i0=a[5]+a[6];"
        "  system(\"sleep 0.2\");"
        "  if (!readcpu(b)) { print \"\"; exit }"
        "  t1=b[2]+b[3]+b[4]+b[5]+b[6]+b[7]+b[8]+b[9]; i1=b[5]+b[6];"
        "  u = (1 - (i1 - i0)/(t1 - t0)) * 100;"
        "  if (u < 0) u = 0; if (u > 100) u = 100;"
        "  printf(\"%.1f\\n\", u);"
        "}'"
    )
    out = ssh_run(cmd)
    try:
        return round(float((out or "").strip().replace(",", ".")), 1)
    except Exception:
        return None

def _per_core_mhz_via_sys() -> list[int]:
    try:
        import glob
        vals: list[int] = []
        for p in glob.glob('/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq'):
            try:
                vtxt = ssh_run(f"cat {p} 2>/dev/null") or "0"
                v = int(vtxt)
                if v > 0:
                    vals.append(int(round(v/1000)))
            except Exception:
                pass
        return vals
    except Exception:
        return []

def _per_core_mhz_via_proc() -> list[int]:
    try:
        txt = ssh_run("grep -i 'cpu MHz' /proc/cpuinfo 2>/dev/null")
        vals: list[int] = []
        for line in (txt or '').splitlines():
            try:
                parts = line.split(':',1)
                if len(parts) == 2:
                    v = float(parts[1].strip())
                    if v > 0:
                        vals.append(int(round(v)))
            except Exception:
                pass
        return vals
    except Exception:
        return []

def _max_mhz_via_lscpu() -> int:
    try:
        v = ssh_run("LC_ALL=C lscpu | grep -m1 'CPU max MHz' | awk -F: '{print $2}'")
        if v:
            return int(round(float(v.strip())))
    except Exception:
        pass
    try:
        v2 = ssh_run("cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq 2>/dev/null")
        if v2:
            return int(round(int(v2.strip())/1000))
    except Exception:
        pass
    return 0

def get_cpu_freq_info() -> dict:
    """Return dynamic CPU frequency info: current MHz (avg), max MHz, per-core list."""
    per = _per_core_mhz_via_sys()
    if not per:
        per = _per_core_mhz_via_proc()
    cur = int(round(sum(per)/len(per))) if per else 0
    mx = _max_mhz_via_lscpu()
    return {"current_mhz": cur, "max_mhz": mx, "per_core": per}
def _cpu_usage_via_mpstat() -> float | None:
    txt = ssh_run("LC_ALL=C mpstat 1 1 2>/dev/null")
    if not txt: return None
    avg = None
    for line in txt.splitlines():
        if line.strip().startswith("Average:"): avg = line
    if not avg: return None
    parts = avg.split()
    try:
        idle = float(parts[-1].replace(",", "."))
        return round(max(0.0, min(100.0, 100.0 - idle)), 1)
    except Exception:
        return None

def _cpu_usage_via_top() -> float | None:
    line = ssh_run("LC_ALL=C top -bn1 | grep -m1 'Cpu(s)'")
    if not line: return None
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*%?\s*id', line)
    if not m: return None
    try:
        idle = float(m.group(1).replace(",", "."))
        return round(max(0.0, min(100.0, 100.0 - idle)), 1)
    except Exception:
        return None

def get_cpu_usage() -> float:
    for fn in (_cpu_usage_via_procstat, _cpu_usage_via_mpstat, _cpu_usage_via_top):
        v = fn()
        if v is not None:
            return v
    return 0.0

# ---- Backward compatibility: old callers importing parse_cpu_usage ----
def parse_cpu_usage(top_line: str = "") -> float:
    """
    Legacy shim. If a top(1) line is provided, parse it; otherwise use get_cpu_usage().
    """
    if top_line:
        m = re.search(r'(\d+(?:[.,]\d+)?)\s*%?\s*id', top_line or "")
        if m:
            try:
                idle = float(m.group(1).replace(",", "."))
                return round(max(0.0, min(100.0, 100.0 - idle)), 1)
            except Exception:
                pass
    return get_cpu_usage()

# --------- Memory / Disk / Network ---------
def parse_mem(free_txt: str):
    for line in free_txt.splitlines():
        if line.lower().startswith("mem:"):
            p = line.split()
            if len(p) >= 7:
                total, used, free = int(p[1]), int(p[2]), int(p[6])
                return round(used/total*100,1), total, free
    return 0.0, 0, 0

def parse_disk(df_txt: str):
    for line in df_txt.splitlines():
        if "/" in line and "%" in line:
            parts = line.split()
            if len(parts) >= 5:
                used_pct = int(parts[4].rstrip('%'))
                return used_pct, parts[1], parts[2], parts[3]
    return 0, "?", "?", "?"

_last_net = {"rx": None, "tx": None, "t": None}
def parse_net_speed(dev_txt: str):
    try:
        best_iface, rx, tx, best_total = None, 0, 0, 0
        for line in dev_txt.strip().splitlines():
            if ":" not in line: continue
            iface, rest = line.split(":", 1)
            f = rest.split()
            curr_rx, curr_tx = int(f[0]), int(f[8])
            tot = curr_rx + curr_tx
            if tot > best_total:
                best_total, best_iface, rx, tx = tot, iface.strip(), curr_rx, curr_tx
        now = time.time()
        if _last_net["rx"] is None:
            _last_net.update({"rx": rx, "tx": tx, "t": now})
            return 0.0, 0.0, 0.0, best_iface or "?"
        dt = max(now - _last_net["t"], 1e-6)
        drx = (rx - _last_net["rx"]) / dt
        dtx = (tx - _last_net["tx"]) / dt
        _last_net.update({"rx": rx, "tx": tx, "t": now})
        return round((drx + dtx)/1024,1), round(drx/1024,1), round(dtx/1024,1), best_iface or "?"
    except Exception as e:
        print("[parse_net_speed] Error:", e)
        return 0.0, 0.0, 0.0, "?"

def get_uptime():
    try:
        secs = int(ssh_run("cut -d. -f1 /proc/uptime") or "0")
        return f"{secs//3600}h {(secs%3600)//60}m {secs%60}s"
    except Exception:
        return "?"

# --------- Temps ---------
def _cpu_temp_from_sensors():
    out = ssh_run("sensors -j 2>/dev/null")
    if not out: return "?"
    try:
        obj = json.loads(out); best = None
        for chip,data in obj.items():
            if not isinstance(data, dict): continue
            for k,v in data.items():
                if not isinstance(v, dict): continue
                for kk,vv in v.items():
                    if not kk.endswith("_input"): continue
                    tag = f"{chip} {k}".lower()
                    if any(t in tag for t in ("core","package","cpu","tdie","tctl")):
                        try:
                            val = float(vv); best = max(best,val) if best is not None else val
                        except: pass
        return round(best,1) if best is not None else "?"
    except Exception:
        return "?"

def get_cpu_temp():
    s = _cpu_temp_from_sensors()
    if s != "?": return s
    try: return round(int(ssh_run("cat /sys/class/thermal/thermal_zone0/temp"))/1000,1)
    except: return "?"

# --------- Disk hardware + SMART temp ---------
SMART = "/usr/sbin/smartctl"  # match sudoers path

def _root_block_device():
    src = ssh_run("findmnt -no SOURCE /").strip()
    if not src: return "", ""
    pkname = ssh_run(f"lsblk -no PKNAME {src} 2>/dev/null").strip()
    if pkname: return src, pkname
    base = os.path.basename(src)
    if base.startswith("nvme") and "p" in base: base = base.split("p")[0]
    else: base = re.sub(r'\d+$','', base)
    return src, base

def _disk_model_for(dev: str) -> str:
    if not dev: return "?"
    model = ssh_run(f"lsblk -dno MODEL /dev/{dev} 2>/dev/null").strip()
    return model or "?"

def _smartctl_available() -> bool:
    return ssh_run(f"test -x {SMART} && echo yes || echo no").strip() == "yes"

def _parse_ata_temp(raw: str) -> str:
    for attr in ("Temperature_Celsius","Temp","Temperature_Internal","Airflow_Temperature_Cel"):
        m = re.search(rf"^\s*\d+\s+{attr}\b.*?(\d+)\s*(?:\(|$)", raw, re.MULTILINE)
        if m: return m.group(1)
    m = re.search(r'(?:Temperature|Composite).*?:\s*([0-9]+)\s*C', raw)
    return m.group(1) if m else "?"

def _disk_temp_via_smartctl(dev: str) -> str:
    if not dev or not _smartctl_available(): return "?"
    if dev.startswith("nvme"):
        out = ssh_run(f"sudo -n {SMART} -A /dev/{dev} 2>/dev/null || {SMART} -A /dev/{dev} 2>/dev/null")
        m = re.search(r'(?:Temperature|Composite):\s*([0-9]+)\s*C', out)
        return m.group(1) if m else "?"
    out = ssh_run(f"sudo -n {SMART} -A /dev/{dev} 2>/dev/null || {SMART} -A /dev/{dev} 2>/dev/null")
    t = _parse_ata_temp(out)
    if t != "?": return t
    out2 = ssh_run(f"sudo -n {SMART} -A -d sat /dev/{dev} 2>/dev/null || {SMART} -A -d sat /dev/{dev} 2>/dev/null")
    return _parse_ata_temp(out2)

def get_disk_hardware_info():
    _, dev = _root_block_device()
    if not dev: return "?", "?", "?"
    return _disk_model_for(dev), dev, _disk_temp_via_smartctl(dev)

# --------- Aggregate ---------
def collect_metrics():
    mem_raw  = ssh_run("free -m")
    disk_raw = ssh_run("df -h /")
    net_raw  = ssh_run("cat /proc/net/dev")
    cpu_name, cpu_cores, cpu_freq = parse_cpu_info()
    cpu_usage = get_cpu_usage()
    ram_usage, ram_total, ram_free = parse_mem(mem_raw or "")
    disk_usage, disk_total, disk_used, disk_free = parse_disk(disk_raw or "")
    net_total, net_rx, net_tx, net_iface = parse_net_speed(net_raw or "")
    uptime = get_uptime()
    cpu_temp = get_cpu_temp()
    disk_model, disk_device, disk_temp = get_disk_hardware_info()
    return {
        "cpu": cpu_usage,
        "cpu_name": cpu_name,
        "cpu_cores": cpu_cores,
        "cpu_freq": cpu_freq,
        "cpu_temp": cpu_temp,
        "ram": ram_usage,
        "ram_total": ram_total,
        "ram_free": ram_free,
        "disk": disk_usage,
        "disk_total": disk_total,
        "disk_used": disk_used,
        "disk_free": disk_free,
        "disk_model": disk_model,
        "disk_device": disk_device,
        "disk_temp": disk_temp,
        "network": net_total,
        "net_rx": net_rx,
        "net_tx": net_tx,
        "net_iface": net_iface,
        "uptime": uptime,
    }

def background_updater() -> None:
    global latest_metrics, first_cached_metrics
    first = True
    while True:
        try:
            metrics = collect_metrics()
            latest_metrics = metrics
            if first:
                first_cached_metrics = metrics
                first = False
        except Exception as e:
            print(f"[background_updater] Error: {e}")
        finally:
            time.sleep(10)
