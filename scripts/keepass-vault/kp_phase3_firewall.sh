#!/usr/bin/env bash
set -euo pipefail
LAN_SUBNET="${LAN_SUBNET:-192.168.1.0/24}"

echo "[*] Configure firewall for LAN-only Samba..."
if command -v ufw >/dev/null 2>&1; then
  echo "[*] Detected UFW"
  # Ensure SSH stays accessible from LAN
  sudo ufw allow from "${LAN_SUBNET}" to any port 22 proto tcp || true
  # Samba rules (use app if available, else explicit ports)
  sudo ufw allow from "${LAN_SUBNET}" to any app Samba || {
    sudo ufw allow from "${LAN_SUBNET}" to any port 137 proto udp
    sudo ufw allow from "${LAN_SUBNET}" to any port 138 proto udp
    sudo ufw allow from "${LAN_SUBNET}" to any port 139 proto tcp
    sudo ufw allow from "${LAN_SUBNET}" to any port 445 proto tcp
  }
  sudo ufw status | grep -q "Status: active" || sudo ufw --force enable
  echo "[OK] Phase 3 done: UFW allows Samba from ${LAN_SUBNET}"
elif command -v firewall-cmd >/dev/null 2>&1; then
  echo "[*] Detected firewalld"
  sudo systemctl enable firewalld --now || true
  ZONE="keepasslan"
  # Create dedicated zone limited to LAN_SUBNET and allow Samba
  sudo firewall-cmd --permanent --get-zones | grep -qw "$ZONE" || sudo firewall-cmd --permanent --new-zone="$ZONE"
  sudo firewall-cmd --permanent --zone="$ZONE" --add-source="${LAN_SUBNET}"
  # Allow SSH from LAN zone
  if sudo firewall-cmd --permanent --zone="$ZONE" --add-service=ssh 2>/dev/null; then :; else
    sudo firewall-cmd --permanent --zone="$ZONE" --add-port=22/tcp
  fi
  if sudo firewall-cmd --permanent --zone="$ZONE" --add-service=samba 2>/dev/null; then :; else
    sudo firewall-cmd --permanent --zone="$ZONE" --add-port=137/udp
    sudo firewall-cmd --permanent --zone="$ZONE" --add-port=138/udp
    sudo firewall-cmd --permanent --zone="$ZONE" --add-port=139/tcp
    sudo firewall-cmd --permanent --zone="$ZONE" --add-port=445/tcp
  fi
  sudo firewall-cmd --reload || true
  echo "[OK] Phase 3 done: firewalld allows Samba from ${LAN_SUBNET} (zone: ${ZONE})"
else
  echo "[warn] No supported firewall (ufw/firewalld) detected. Skipping LAN scoping."
  echo "[OK] Phase 3 done: no firewall configured"
fi
