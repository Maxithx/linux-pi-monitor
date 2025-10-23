Glances (pipx web) — Install, Service, Uninstall

This app installs Glances Web UI with pipx in the user scope and runs it as a systemd service listening on 0.0.0.0:61208.

Requirements

Debian/Ubuntu/Mint with systemd and sudo

Python 3.12+, pipx available (apt ensures it)

SSH profile configured in the app (host/user/auth)

What the app does (happy path)

Install Glances (user via pipx)

/usr/bin/pipx install --force "glances[web]"


Create the systemd unit (runs as <USER>)

# /etc/systemd/system/glances.service
[Unit]
Description=Glances (pipx web)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=<USER>
Environment=PATH=/home/<USER>/.local/bin:/usr/bin:/bin
ExecStart=/home/<USER>/.local/share/pipx/venvs/glances/bin/glances -w -B 0.0.0.0
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target


Enable & start

sudo systemctl daemon-reload
sudo systemctl enable glances
sudo systemctl restart glances


Open firewall (only if ufw is active)

sudo ufw allow 61208/tcp

Uninstall flow (what the app runs)
# Stop/disable and remove unit
sudo systemctl disable --now glances || true
sudo rm -rf /etc/systemd/system/glances.service.d || true
sudo rm -f  /etc/systemd/system/glances.service || true
sudo systemctl daemon-reload || true

# Kill any stray user processes (best effort)
pkill -f "glances -w"      || true
pkill -f "uvicorn.*glances"|| true

# Remove pipx app and leftovers (user scope)
pipx uninstall glances || true
rm -f  "$HOME/.local/bin/glances" || true
rm -rf "$HOME/.local/share/pipx/venvs/glances" "$HOME/.local/pipx/venvs/glances" || true

Verify
# Service
systemctl is-enabled glances   || echo "not enabled"
systemctl is-active glances    || echo "inactive"
systemctl cat glances 2>/dev/null || echo "no unit file"

# Binary / port
command -v glances || echo "no glances in PATH"
ss -ltn 'sport = :61208' | tail -n +2 || echo "port 61208 closed"

Notes & edge cases

On Debian/Ubuntu with PEP 668 (“externally managed environment”), use pipx (system-wide pip is blocked by design). We call /usr/bin/pipx directly to avoid $PATH issues.

The service runs as the SSH user from your active profile to ensure the pipx venv and PATH are correct.

If you previously installed Glances via APT, purge it manually if you want to avoid /usr/bin/glances shadowing: sudo apt purge -y glances.