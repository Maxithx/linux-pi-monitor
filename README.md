# Linux Pi Monitor

**Linux Pi Monitor** is a powerful, modern dashboard for monitoring and interacting with your Linux or Raspberry Pi system – all from a user-friendly web interface built with Python + Flask and running on Windows.

## 🚀 Features

- 📡 Realtime system monitoring via SSH
- 📊 Live dashboard showing:
  - CPU and RAM usage
  - Swap, temperature, and disk space
  - Network activity
- 🖥️ HTOP-style monitoring via Glances (auto-installed)
- 🧠 Built-in terminal (live SSH terminal with command history)
- 🛠️ Settings panel for SSH configuration (key or password)
- 📦 Ready for Windows `.exe` packaging (via Inno Setup)
- 🌗 Dark theme UI
- 🔄 Multi-language ready (Danish and English support planned)

## 🧰 Technologies Used

- Python 3 + Flask
- Paramiko (SSH communication)
- HTML, CSS, JavaScript
- Glances (HTOP-style system monitor)
- xterm.js (web terminal interface)
- GitHub for version control

## 🖥️ Installation

1. Enable SSH on your Raspberry Pi
2. Clone the repo:
   ```bash
   git clone https://github.com/Maxithx/linux-pi-monitor.git
   cd linux-pi-monitor
3. Install dependencies: pip install -r requirements.txt

4. Run the app: python app.py
5. Open in browser:
http://127.0.0.1:8080

-------------------------------------------------------------------------------------------------------------

🔒 SSH Features
SSH Key or Password login

Secure background connection to your Pi

Automatically restores connection if lost

Web-based terminal with command history and feedback

🧪 Live Web Terminal
Run Pi commands directly from your browser

Powered by xterm.js + Flask

Editable command history

Color output and auto-scroll

📊 System Monitor: Glances
Auto-installable with one click

Runs as a background systemd service

Streams live stats to the dashboard

HTOP-style interface (CPU cores, memory, disk, network)

🛠️ Development Roadmap
 Auto-install Glances

 Live Terminal with SSH

 Real-time dashboard charts

 Multi-language UI (Danish + English)

 .exe installer via Inno Setup

 Background daemon & auto-updater

🖼️ Screenshots
(Insert screenshots of settings page, dashboard, terminal, etc.)

📄 License
This project is privately developed by Maxithx.
Please ask for permission before using this project commercially or redistributing it.




