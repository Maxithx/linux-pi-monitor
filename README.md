![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B-informational)
![Flask](https://img.shields.io/badge/Flask-2.x-black)
![Version](https://img.shields.io/badge/version-v1.6-blue)
![OS](https://img.shields.io/badge/Supported%20OS-Windows%2010%2F11%20%7C%20Linux%20Mint-green)

# Linux Pi Monitor

**Linux Pi Monitor** is a fast, modern web application (Python + Flask) for monitoring and managing Linux and Raspberry Pi machines **over SSH** — directly from your Windows PC.

It features a live dashboard with charts, a built-in web terminal, one-click Glances installation, a **System Update Center**, a **Network & DNS Manager**, and **multi-profile SSH** management (keys or passwords).

---

## 📸 Screenshots & Navigation

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

## ✨ Highlights

- **Multi-profile SSH**: Save multiple hosts (Pi, Linux server), switch instantly.
- **Secure Authentication**: Generate **ed25519** keys and install the public key on the host with one click.
- **Glances Integration**: Install, start, stop, and view logs for the Glances service remotely.
- **Network & DNS Manager**:
  - View active interfaces, IPv4, MAC, and SSID.
  - Change DNS servers live (Google, Cloudflare, Quad9, or Custom).
  - Automatic detection of active connection and `systemd-resolved` method.
- **Driver Detection**:
  - Detect and manage OS-specific drivers (Debian, Mint).
  - Future support for automatic driver install/uninstall.
- **Update Center**:
  - Displays available APT updates with severity and details.
  - Buttons are locked while loading or installing, to prevent conflicts.
- **Windows Host**: The app runs locally on your Windows machine (Python 3.10+ required).

---

## 📦 Install & Run (Windows)

> The app runs locally on your Windows machine and connects to your Linux/Pi host over SSH.

1.  **Clone the repository**
    ```bash
    git clone https://github.com/Maxithx/linux-pi-monitor.git
    cd linux-pi-monitor
    ```

2.  **Create venv & install dependencies**
    ```bash
    python -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt
    ```

3.  **Start the application**
    ```bash
    python app.py
    ```
    Open: `http://127.0.0.1:8080` in your browser.

---

## 🖼️ Screenshots

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
![Update-Center](docs/screenshots/image-6.png)

---

## 🧰 Tech Stack

- **Backend**: Python 3, Flask, Paramiko (SSH)
- **Frontend**: HTML/CSS/JavaScript, Chart.js, xterm.js
- **System Monitor**: Glances (remote), systemd service
- **Modules**:
  - `routes/network/` — modularized DNS, Wi-Fi, and summary views
  - `routes/updates_drivers/` — OS driver handling
- **Platform**: Windows 10/11 (Python 3.10+ recommended)

---

## 🗺️ Roadmap & Contribution

Future enhancements include:
- Language switcher (UI localization).
- Packaging as an executable.
- Driver auto-update integration.
- More detailed charts (per-core, disk IO).

Feel free to contribute to the project! See the repository for details.

---

## 🕓 Change Log

### 🧩 **v1.6 – DNS & Drivers Update**
- Split `network.py` into modular structure:
  - `helpers.py`, `views_dns.py`, `views_wifi.py`, `views_summary.py`, `dns_helpers.py`.
- Added live **DNS Manager** with Google, Cloudflare, Quad9 and custom presets.
- Added **Drivers** page (auto-detects Mint/Debian drivers and kernel modules).
- Improved `sudo` handling (no `[sudo] password` prompt text in logs).
- DNS changes now use **nmcli reapply** instead of full reconnect — no more Wi-Fi disconnects.
- Added display of Stub + Upstream DNS in network header.
- Minor UI/UX polish across Network and Drivers pages.

### 🛠️ **v1.5 – Update Center Improvements**
- Buttons for "Full Update", "Security Update", and "All Updates" are **disabled while loading or installing**.
- Prevents accidental double actions.
- Added `setBusy()` helper in JS + CSS disabled styling.
- Smoothed loading state and aria-busy support for accessibility.

### 🧠 **v1.4 – System Stability & Glances Integration**
- Improved Glances installation and control.
- Added retry logic for SSH commands.
- Enhanced error output and timeout handling.

### 🚀 **v1.3 – Multi-profile SSH & Terminal**
- Multiple profile support with quick-switch dropdown.
- Added live xterm.js terminal with scroll and custom color scheme.
- Added saved command overview.

### 🌐 **v1.2 – Core UI Framework**
- Sidebar navigation with persistent state.
- Unified CSS grid layout for all pages.
- Base dark theme and responsive structure.

### 🎉 **v1.0 – Initial Release**
- First public release of Linux Pi Monitor.
- Core Flask structure, SSH connection, system summary, update check.

---

© 2025 **THXMAN Labs** — Developed by *Thomas & ChatGPT 🤖*
