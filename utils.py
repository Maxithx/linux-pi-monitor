# === SSH Parsing og Hjælpefunktioner ===
# Her ligger alle funktioner til at hente og analysere systemdata via SSH.
# Disse bruges af dashboard og baggrundsopdatering.

import re
import time
import json
import os
import paramiko

def get_ssh_settings():
    settings_path = os.path.join(os.getenv("APPDATA"), "raspberry_pi_monitor", "settings.json")
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "host": data.get("pi_host", ""),
            "user": data.get("pi_user", ""),
            "key_path": data.get("ssh_key_path", ""),
            "password": data.get("password", ""),
            "auth_method": data.get("auth_method", "key")
        }
    except Exception as e:
        print("[get_ssh_settings] Fejl:", e)
        return {}


# Bruges til at holde styr på tidligere netværksdata (for beregning af hastighed)
last_stats = {"rx": None, "tx": None, "time": None}

# === SSH-Kommando ===
def ssh_run(command):
    """Kører en SSH-kommando og returnerer output som tekst."""
    try:
        s = get_ssh_settings()
        if not s.get("host") or not s.get("user"):
            return ""

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        if s["auth_method"] == "key" and s["key_path"]:
            key = paramiko.RSAKey.from_private_key_file(s["key_path"])
            ssh.connect(s["host"], username=s["user"], pkey=key)
        elif s["auth_method"] == "password" and s["password"]:
            ssh.connect(s["host"], username=s["user"], password=s["password"])
        else:
            return ""

        stdin, stdout, stderr = ssh.exec_command(command)
        output = stdout.read().decode().strip()
        ssh.close()
        return output
    except Exception as e:
        print("[ssh_run] Fejl:", e)
        return ""

# === CPU Info ===
def parse_cpu_info():
    """Henter model, antal kerner og frekvens via SSH."""
    name = ssh_run("lscpu | grep 'Model name' | awk -F: '{print $2}'").strip() or "Unknown CPU"
    cores = ssh_run("nproc").strip() or "Unknown"
    freq_line = ssh_run("lscpu | grep MHz | tail -1").strip()
    freq_match = re.search(r'(\d+\.?\d*)', freq_line)
    freq_ghz = f"{round(float(freq_match.group(1)) / 1000, 2)}" if freq_match else "?"
    max_freq_line = ssh_run("lscpu | grep 'CPU max MHz'").strip()
    max_match = re.search(r'(\d+\.?\d*)', max_freq_line)
    max_ghz = f"{round(float(max_match.group(1)) / 1000, 2)}" if max_match else "?"
    return name, cores, f"{freq_ghz} / {max_ghz} GHz"

# === CPU-Forbrug ===
def parse_cpu_usage(output):
    """Parser CPU-idle værdi og beregner forbrug."""
    match = re.search(r'(\d+\.\d+)\s+id', output)
    return round(100 - float(match.group(1)), 1) if match else 0

# === RAM-brug ===
def parse_mem(output):
    """Parser RAM-forbrug og returnerer brugt %, total og fri."""
    for line in output.splitlines():
        if line.lower().startswith("mem:"):
            parts = line.split()
            if len(parts) >= 7:
                total = int(parts[1])
                used = int(parts[2])
                free = int(parts[6])
                return round(used / total * 100, 1), total, free
    return 0, 0, 0

# === Disk-brug ===
def parse_disk(output):
    """Parser diskplads og returnerer brugt %, total, brugt, fri."""
    for line in output.splitlines():
        if "/" in line and "%" in line:
            parts = line.split()
            if len(parts) >= 5:
                used = int(parts[4].replace('%', ''))
                return used, parts[1], parts[2], parts[3]
    return 0, "?", "?", "?"

# === Netværkshastighed ===
def parse_net_speed(output):
    """Parser netværkshastighed og estimerer RX + TX (kB/s)."""
    try:
        best_iface = None
        best_total = 0
        rx, tx = 0, 0
        for line in output.strip().split("\n"):
            if ":" in line:
                iface, data = line.split(":", 1)
                fields = data.split()
                curr_rx = int(fields[0])
                curr_tx = int(fields[8])
                total = curr_rx + curr_tx
                if total > best_total:
                    best_iface, rx, tx, best_total = iface.strip(), curr_rx, curr_tx, total
        now = time.time()
        if last_stats["rx"] is None:
            last_stats.update({"rx": rx, "tx": tx, "time": now})
            return 0, 0, 0, best_iface
        delta_time = now - last_stats["time"]
        delta_rx = (rx - last_stats["rx"]) / delta_time if delta_time > 0 else 0
        delta_tx = (tx - last_stats["tx"]) / delta_time if delta_time > 0 else 0
        last_stats.update({"rx": rx, "tx": tx, "time": now})
        return round((delta_rx + delta_tx) / 1024, 1), round(delta_rx / 1024, 1), round(delta_tx / 1024, 1), best_iface or "?"
    except Exception as e:
        print(f"[parse_net_speed] Fejl: {e}")
        print(f"[parse_net_speed] Output:\n{output}")
        return 0, 0, 0, ""

# === Uptime og Temperatur ===
def get_uptime():
    """Returnerer uptime-format t:m:s fra /proc/uptime."""
    try:
        total_seconds = int(float(ssh_run("cat /proc/uptime").split()[0]))
        return f"{total_seconds // 3600}t {(total_seconds % 3600) // 60}m {total_seconds % 60}s"
    except:
        return "?"

def get_cpu_temp():
    """Returnerer CPU-temperatur i grader celsius."""
    try:
        return round(int(ssh_run("cat /sys/class/thermal/thermal_zone0/temp")) / 1000, 1)
    except:
        return "?"

# === Samlet målefunktion ===
def collect_metrics():
    """Samler alle målinger ét sted og returnerer som dict."""
    cpu_raw = ssh_run("top -bn1 | grep 'Cpu(s)'")
    mem_raw = ssh_run("free -m")
    disk_raw = ssh_run("df -h /")
    net_raw = ssh_run("cat /proc/net/dev")
    cpu_name, cpu_cores, cpu_freq = parse_cpu_info()
    cpu_usage = parse_cpu_usage(cpu_raw)
    ram_usage, ram_total, ram_free = parse_mem(mem_raw)
    disk_usage, disk_total, disk_used, disk_free = parse_disk(disk_raw)
    net_total, net_rx, net_tx, net_iface = parse_net_speed(net_raw)
    uptime = get_uptime()
    cpu_temp = get_cpu_temp()
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
        "network": net_total,
        "net_rx": net_rx,
        "net_tx": net_tx,
        "net_iface": net_iface,
        "uptime": uptime
    }

# === Baggrundstråd som opdaterer målinger hver 10. sekund ===
def background_updater():
    global latest_metrics, first_cached_metrics
    first = True
    while True:
        try:
            metrics = collect_metrics()
            latest_metrics = metrics
            if first:
                first_cached_metrics = metrics
                first = False
            time.sleep(10)
        except Exception as e:
            print(f"[background_updater] Fejl: {e}")
            time.sleep(10)
