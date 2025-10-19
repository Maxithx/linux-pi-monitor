#!/usr/bin/env bash
set -euo pipefail
VAULT_USER="keepass"
VAULT_DIR="/srv/keepass/vault"
LAN_SUBNET="${LAN_SUBNET:-192.168.1.0/24}"
SAMBA_MAIN="/etc/samba/smb.conf"
SAMBA_SHARES="/etc/samba/shares.conf"
BACKUP="/etc/samba/smb.conf.bak.$(date +%Y%m%d-%H%M%S)"

echo "[*] Backup smb.conf -> $BACKUP"
sudo cp -an "$SAMBA_MAIN" "$BACKUP" || true

if ! grep -q "include = ${SAMBA_SHARES}" "$SAMBA_MAIN"; then
  # Append a blank line and the include line with proper permissions
  echo "" | sudo tee -a "$SAMBA_MAIN" >/dev/null
  echo "include = ${SAMBA_SHARES}" | sudo tee -a "$SAMBA_MAIN" >/dev/null
fi

# Ensure hardened [global] settings are present (min protocol, interfaces binding)
if grep -q "^\s*\[global\]" "$SAMBA_MAIN"; then
  sudo awk -v lan_subnet="${LAN_SUBNET}" '
    BEGIN{in_g=0; inserted=0}
    /^\[global\]/{in_g=1; print; next}
    /^\[.*\]/{
      if(in_g && !inserted){
        print "   server min protocol = SMB3";
        print "   interfaces = 127.0.0.1/8 " lan_subnet;
        print "   bind interfaces only = yes";
        inserted=1
      }
      in_g=0; print; next
    }
    {
      if(in_g){
        # Drop any existing lines we manage in [global]
        if ($0 ~ /^[[:space:]]*server[[:space:]]+min[[:space:]]+protocol[[:space:]]*=/) next;
        if ($0 ~ /^[[:space:]]*interfaces[[:space:]]*=/) next;
        if ($0 ~ /^[[:space:]]*bind[[:space:]]+interfaces[[:space:]]+only[[:space:]]*=/) next;
      }
      print
    }
    END{
      if(in_g && !inserted){
        print "   server min protocol = SMB3";
        print "   interfaces = 127.0.0.1/8 " lan_subnet;
        print "   bind interfaces only = yes";
        inserted=1
      }
    }
  ' "$SAMBA_MAIN" | sudo tee "${SAMBA_MAIN}.new" >/dev/null && sudo mv "${SAMBA_MAIN}.new" "$SAMBA_MAIN"
else
  echo "" | sudo tee -a "$SAMBA_MAIN" >/dev/null
  printf "[global]\n  server min protocol = SMB3\n  interfaces = 127.0.0.1/8 %s\n  bind interfaces only = yes\n" "${LAN_SUBNET}" | sudo tee -a "$SAMBA_MAIN" >/dev/null
fi

TMP="$(mktemp)"
cat > "$TMP" <<EOF
[keepass]
  path = ${VAULT_DIR}
  browseable = no
  read only = no
  valid users = ${VAULT_USER}
  force user = ${VAULT_USER}
  create mask = 0600
  directory mask = 0700
  hosts allow = ${LAN_SUBNET}
  smb encrypt = required
EOF

if sudo test -f "$SAMBA_SHARES"; then
  sudo awk '
    BEGIN{skip=0}
    /^\[keepass\]/{skip=1; next}
    /^\[.*\]/{skip=0}
    skip==0{print $0}
  ' "$SAMBA_SHARES" | sudo tee "${SAMBA_SHARES}.new" >/dev/null
  sudo mv "${SAMBA_SHARES}.new" "$SAMBA_SHARES"
else
  echo "# Auto-generated local shares" | sudo tee "$SAMBA_SHARES" >/dev/null
fi

echo >>"$TMP"
sudo tee -a "$SAMBA_SHARES" < "$TMP" >/dev/null
rm -f "$TMP"

echo "[*] Set SMB password for user '${VAULT_USER}' (empty SMB_PASS -> interactive)"
if [ -n "${SMB_PASS:-}" ]; then
  (echo "${SMB_PASS}"; echo "${SMB_PASS}") | sudo smbpasswd -a -s "$VAULT_USER"
else
  sudo smbpasswd -a "$VAULT_USER"
fi

echo "[*] Test Samba config..."
sudo testparm -s >/dev/null

echo "[*] Restart smbd..."
# Detect Samba service name (smbd on Debian/Ubuntu, smb on RHEL/Fedora)
SAMBA_SERVICE="smbd"
if command -v systemctl >/dev/null 2>&1; then
  if systemctl list-unit-files | grep -q '^smb\.service'; then
    SAMBA_SERVICE="smb"
  fi
fi
sudo systemctl enable "$SAMBA_SERVICE" --now || true
sudo systemctl restart "$SAMBA_SERVICE"

echo "[OK] Phase 2 done: share [keepass] active"
