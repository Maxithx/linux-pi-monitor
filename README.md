![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B-informational)
![Flask](https://img.shields.io/badge/Flask-2.x-black)

# Linux Pi Monitor

**Linux Pi Monitor** is a fast, modern web application (Python + Flask) for monitoring and managing Linux and Raspberry Pi machines **over SSH** — directly from your Windows PC.

It features a live dashboard with charts, a built-in web terminal, one-click Glances installation, a **System Update Center**, and **multi-profile** SSH management (keys or passwords).

---

## 📸 Screenshots & Navigation

| Feature | Description | Link |
| :--- | :--- | :--- |
| Dashboard | CPU, RAM, disk, temperatures, and mini charts. | [View Dashboard](#dashboard) |
| Settings | Manage SSH profiles, keys, and Glances service. | [View Settings](#settings) |
| Network | Interface overview, Wi-Fi scanning, and DNS info. | [View Network](#network) |
| Logs | View service and application logs directly in the browser. | [View Logs](#logs) |
| Live Monitor | Embedded Glances Web UI for detailed system monitoring. | [View Live Monitor](#live-system-glances) |
| Terminal | Full-width xterm.js terminal with saved commands. | [View Terminal](#terminal) |
| Update Center | Run security and full system upgrades. | [View Update Center](#update-center) |

---

## ✨ Highlights

- **Multi-profile SSH**: Save multiple hosts (Pi, Linux server), switch instantly.
- **Secure Authentication**: Generate **ed25519** keys and install the public key on the host with one click.
- **Glances Integration**: Install, start, stop, and view logs for the Glances service remotely.
- **Update Center**: Displays status for APT, Flatpak, Snap, and Docker packages.
- **Windows Host**: The app runs locally on your Windows machine (Python 3.10+ required).

---

## 📦 Install & Run (Windows)

> The app runs locally on your Windows machine and connects to your Linux/Pi host over SSH.

1.  **Clone the repository**
    ```bash
    git clone [https://github.com/Maxithx/linux-pi-monitor.git](https://github.com/Maxithx/linux-pi-monitor.git)
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
[![Dashboard – Linux Pi Monitor](docs/screenshots/image-1.png)](docs/screenshots/image-1.png)

<a id="settings"></a>
### Settings
[![Settings – SSH/Glances](docs/screenshots/image-2.png)](docs/screenshots/image-2.png)

<a id="network"></a>
### Network
[![Network – Interfaces & Wi-Fi](docs/screenshots/image-7.png)](docs/screenshots/image-7.png)

<a id="logs"></a>
### Logs
[![Logs](docs/screenshots/image-3.png)](docs/screenshots/image-3.png)

<a id="live-system-glances"></a>
### Live System Monitor (Glances)
[![Live System Monitor (Glances)](docs/screenshots/image-4.png)](docs/screenshots/image-4.png)

<a id="terminal"></a>
### Terminal
[![Terminal](docs/screenshots/image-5.png)](docs/screenshots/image-5.png)

<a id="update-center"></a>
### Update Center
[![Update-Center](docs/screenshots/image-6.png)](docs/screenshots/image-6.png)

---

## 🧰 Tech Stack

- **Backend**: Python 3, Flask, Paramiko (SSH)
- **Frontend**: HTML/CSS/JavaScript, Chart.js, xterm.js
- **System Monitor**: Glances (remote), systemd service
- **Platform**: Windows 10/11 (Python 3.10+ recommended)

---

## 🗺️ Roadmap & Contribution

Future enhancements include:
- Language switcher (UI localization).
- Packaging as an executable.
- More detailed charts (per-core, disk IO).

Feel free to contribute to the project! See the repository for details.