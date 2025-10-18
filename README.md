![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B-informational)
![Flask](https://img.shields.io/badge/Flask-2.x-black)
![Version](https://img.shields.io/badge/version-v1.7-blue)
![OS](https://img.shields.io/badge/Supported%20OS-Windows%2010%2F11%20%7C%20Linux%20Mint-green)

# Linux Pi Monitor

Linux Pi Monitor is a fast, modern web application (Python + Flask) for monitoring and managing Linux and Raspberry Pi machines over SSH — directly from your Windows PC.

It features a live dashboard with charts, a built-in web terminal, one-click Glances installation, a System Update Center, a Network & DNS Manager, and multi-profile SSH management (keys or passwords).

---

## Screenshots & Navigation

| Feature | Description | Link |
| :--- | :--- | :--- |
| Dashboard | CPU, RAM, disk, temperatures, and mini charts. | [View Dashboard](#dashboard) |
| Settings | Manage SSH profiles, keys, and Glances service. | [View Settings](#settings) |
| Network | Interface overview, Wi-Fi scanning, and live DNS control. | [View Network](#network) |
| Logs | View service and application logs directly in the browser. | [View Logs](#logs) |
| Live Monitor | Embedded Glances Web UI for detailed system monitoring. | [View Live Monitor](#live-system-glances) |
| Terminal | Full-width xterm.js terminal with saved commands. | [View Terminal](#terminal) |
| Drivers | Detect Linux drivers per OS (Debian, Mint) and display versions. | [View Drivers](#drivers) |
| Update Center | Run security and full system upgrades with locked buttons during processing. | [View Update Center](#update-center) |

---

## Highlights

- Multi-profile SSH: Save multiple hosts (Pi, Linux server), switch instantly.
- Secure Authentication: Generate ed25519 keys and install the public key on the host with one click.
- Glances Integration: Install, start, stop, and view logs for the Glances service remotely.
- Network & DNS Manager:
  - View active interfaces, IPv4, MAC, and SSID.
  - Change DNS servers live (Google, Cloudflare, Quad9, or Custom).
  - Automatic detection of active connection and systemd-resolved method.
- Driver Detection:
  - Detect and manage OS-specific drivers (Debian, Mint).
  - Future support for automatic driver install/uninstall.
- Update Center:
  - Displays available APT updates with severity and details.
  - Buttons are locked while loading or installing, to prevent conflicts.
- Windows Host: The app runs locally on your Windows machine (Python 3.10+ required).

---

## Install & Run

This project supports two simple ways to run:

- **A. No Conda (works everywhere)** — Recommended for portability (Windows / Linux / Raspbian).
- **B. With Conda (Windows 10/11)** — Great if you prefer Conda-managed Python on Windows.

### A. Run without Conda (universal)

> Works on Windows 11, Linux Mint, and Raspbian using a plain Python virtual environment (venv).

1) Clone the repository
```bash
git clone https://github.com/Maxithx/linux-pi-monitor.git
cd linux-pi-monitor
```

2) Create & activate venv, install dependencies, run

**Windows (CMD/PowerShell)**
```bat
py -m venv .venv
.\.venv\Scriptsctivate
pip install -r requirements.txt
python app.py
```

**Linux (Mint / Raspbian)**
```bash
python3 -m venv .venv    # or: python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open: http://127.0.0.1:8080

To stop the app: `Ctrl+C`  
To deactivate the venv: `deactivate`

---

### B. Run with Conda (Windows 10/11)

> Keeps your system Python clean and runs everything inside an isolated Conda environment.

1) Clone the repository
```bat
git clone https://github.com/Maxithx/linux-pi-monitor.git
cd linux-pi-monitor
```

2) Create & activate Conda environment, install dependencies, run
```bat
conda create -n linux-pi-monitor-clean python=3.12 -y
conda activate linux-pi-monitor-clean
pip install -r requirements.txt
python app.py
```

Open: http://127.0.0.1:8080

**Notes**
- Always `conda activate linux-pi-monitor-clean` before running `pip` or `python`.
- Keep channels simple (`conda-forge` + `defaults`).
- Avoid `prefix:` in `environment.yml` (non-portable), if you later add one.

---

## Optional one-click scripts

> These helpers create `.venv`, install dependencies, and run the app automatically.

**Windows** — create `run-dev.bat`:
```bat
@echo off
setlocal
py -m venv .venv
call .venv\Scriptsctivate.bat
python -m pip install --upgrade pip wheel
pip install -r requirements.txt
python app.py
```

**Linux** — create `run-dev.sh`:
```bash
#!/usr/bin/env bash
set -e
[ -d ".venv" ] || python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip wheel
pip install -r requirements.txt
python app.py
```
Make executable: `chmod +x run-dev.sh`

---

## Screenshots

<a id="dashboard"></a>
### Dashboard
![Dashboard – Linux Pi Monitor](docs/screenshots/image-1.png)

<a id="settings"></a>
### Settings
![Settings – SSH/Glances](docs/screenshots/image-2.png)

<a id="network"></a>
### Network
![Network – Interfaces & Wi-Fi + DNS](docs/screenshots/image-7.png)

<a id="logs"></a>
### Logs
![Logs](docs/screenshots/image-3.png)

<a id="live-system-glances"></a>
### Live System Monitor (Glances)
![Live System Monitor (Glances)](docs/screenshots/image-4.png)

<a id="terminal"></a>
### Terminal
![Terminal](docs/screenshots/image-5.png)

<a id="drivers"></a>
### Drivers
![Drivers](docs/screenshots/image-8.png)

<a id="update-center"></a>
### Update Center
![Update Center](docs/screenshots/image-6.png)
