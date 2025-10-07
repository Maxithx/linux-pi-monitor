![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B-informational)
![Flask](https://img.shields.io/badge/Flask-2.x-black)


## 📸 Screenshots
- [Dashboard](#s1-dashboard)
- [Settings (SSH/Glances)](#s2-settings)
- [Network – Interfaces & Wi-Fi](#s3-network)
- [Logs](#s4-logs)
- [Live System Monitor (Glances)](#s5-glances)
- [Terminal](#s6-terminal)
- [Update Center](#s7-update)

# Linux Pi Monitor

A simple web app to monitor and manage Linux and Raspberry Pi hosts from a Windows PC.  
Backend is **Flask**; remote actions are done over **SSH**; live metrics use **Glances**.  
UI includes a dashboard, terminal, network tools, logs, and an update center.

---

## Features

- **Profiles**: save multiple SSH targets and switch instantly.
- **Key or password auth**: generate ed25519 keys and install the public key on the host.
- **Dashboard**: CPU, RAM, disk, temperatures, and mini charts.
- **Glances integration**: install/start/stop service and open the web UI.
- **Terminal (redesigned)**: xterm.js with saved commands, Insert/Run actions.
- **Network**: interface overview, Wi-Fi scan and connect, default route and DNS.
- **Update Center**: security upgrades or full upgrades, plus status for APT/Flatpak/Snap/Docker.
- **Logs**: view service and app logs directly in the browser.
- **Dark theme** and responsive layout.

---

## Requirements

- **Runner**: Windows 10/11 with Python 3.10+ (the app runs on Windows).
- **Targets**: Linux hosts with SSH enabled; systemd required for Glances service control.
- Network access between Windows and the Linux/Pi hosts.

---

## Quick start (Windows)

```bash
git clone https://github.com/Maxithx/linux-pi-monitor.git
cd linux-pi-monitor

# Create venv and install
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Run
python app.py
# Open http://127.0.0.1:8080 in your browser

Pages overview
Settings

Manage SSH profiles and keys. Generate an ed25519 key pair and one-click install the public key to ~/.ssh/authorized_keys on the target. Shows active profile status across pages.

Network

Interface table (type, IPv4, MAC, SSID, signal, bitrate, default route, DNS).
Wi-Fi panel for scanning, connecting, and forgetting networks. Includes a filter box for SSIDs.

Terminal

Full-width xterm.js terminal. Saved commands table with columns Title | Command | Description | Action.
Actions:

Insert: write the command into the prompt without Enter.

Run: send the command followed by Enter.
Seeds 3 examples on first load: sudo reboot, free -h, df -h.

Live System (Glances)

Install Glances remotely, manage the systemd service, and open the embedded Glances web UI.

Update Center

Run security-only or full system upgrades. Shows basic package ecosystem info (APT/Flatpak/Snap/Docker).

Logs

View logs for Glances, services, and the app. Helpful for troubleshooting installs or services.


🗂️ Project Structure (simplified)
csharp
Kopier kode
linux-pi-monitor/
├─ app.py                    # Flask app entrypoint
├─ routes/                   # Flask blueprints & server logic
├─ static/
│  ├─ css/                   # Styles
│  └─ js/                    # Frontend logic (profiles, glances, charts, terminal)
├─ templates/                # Jinja2 HTML templates (Dashboard, Settings, Glances, Terminal, Logs)
├─ requirements.txt          # Python dependencies
├─ full_requirements.txt     # (optional, dev)
└─ README.md                 # This file
✅ Supported Targets
Remote: Raspberry Pi OS / Debian / Ubuntu (systemd available)

Local runner: Windows 10/11 (Python 3.10+ recommended)

You’ll need a user with permission to install packages/start services on the remote host (typically via sudo).

🔧 Troubleshooting
“No connection to Linux”
Check host/IP, username, and auth method in Settings.
If using keys, click Install key on host once, or ensure your public key exists in ~/.ssh/authorized_keys on the remote host.

Glances won’t start
View Glances log and service log from the Settings page.
Ensure systemd is present and the user can sudo systemctl ....

Charts look flat
Give it a minute; the dashboard samples continuously.
Network values are in KB/s (not Kb/s).

🗺️ Roadmap
Language switcher (Danish/English UI)

Packaging as .exe (optional)

Auto-update channel

More charts (per-core, disk IO, net per-iface)

Custom alerts (CPU temp, disk space)
🖼️ Screenshots

Add screenshots of Dashboard, Settings (SSH/Glances), Terminal, Glances page here.

<a id="s1-dashboard"></a>
<h3 style="margin-top:20px;">Dashboard</h3>
[![Dashboard – Linux Pi Monitor](docs/screenshots/image-1.png)](docs/screenshots/image-1.png)

<a id="s2-settings"></a>
<h3 style="margin-top:20px;">Settings</h3>
[![Settings – SSH/Glances](docs/screenshots/image-2.png)](docs/screenshots/image-2.png)

<a id="s3-network"></a>
<h3 style="margin-top:20px;">Network</h3>
[![Network – Interfaces & Wi-Fi](docs/screenshots/image-7.png)](docs/screenshots/image-7.png)

<a id="s4-logs"></a>
<h3 style="margin-top:20px;">Logs</h3>
[![Logs](docs/screenshots/image-3.png)](docs/screenshots/image-3.png)

<a id="s5-glances"></a>
<h3 style="margin-top:20px;">Live System Monitor (Glances)</h3>
[![Live System Monitor (Glances)](docs/screenshots/image-4.png)](docs/screenshots/image-4.png)

<a id="s6-terminal"></a>
<h3 style="margin-top:20px;">Terminal</h3>
[![Terminal](docs/screenshots/image-5.png)](docs/screenshots/image-5.png)

<a id="s7-update"></a>
<h3 style="margin-top:20px;">Update Center</h3>
[![Update-Center](docs/screenshots/image-6.png)](docs/screenshots/image-6.png)
