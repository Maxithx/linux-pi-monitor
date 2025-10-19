#!/usr/bin/env bash
set -euo pipefail
VAULT_USER="keepass"
SAMBA_SHARES="/etc/samba/shares.conf"

echo "[*] Remove [keepass] block from shares.conf (if any)..."
if sudo test -f "$SAMBA_SHARES"; then
  sudo awk '
    BEGIN{skip=0}
    /^\[keepass\]/{skip=1; next}
    /^\[.*\]/{skip=0}
    skip==0{print $0}
  ' "$SAMBA_SHARES" | sudo tee "${SAMBA_SHARES}.new" >/dev/null
  sudo mv "${SAMBA_SHARES}.new" "$SAMBA_SHARES"
fi

echo "[*] Disable SMB account for keepass (if exists)..."
sudo smbpasswd -x "$VAULT_USER" || true

echo "[*] Restart smbd..."
sudo systemctl restart smbd || true

echo "[✓] Rollback completed. Manual cleanup of /srv/keepass if desired."

