#!/usr/bin/env bash
set -euo pipefail

SAMBA_SHARES="/etc/samba/shares.conf"
WRITABLE="${KP_WRITABLE:-}"

if [[ "$WRITABLE" != "0" && "$WRITABLE" != "1" ]]; then
  echo "[error] KP_WRITABLE must be 0 or 1"
  exit 2
fi

if ! sudo test -f "$SAMBA_SHARES"; then
  echo "[error] KeePass Samba config not found: $SAMBA_SHARES"
  exit 3
fi

if ! sudo grep -q '^\[keepass\]$' "$SAMBA_SHARES"; then
  echo "[error] Samba share [keepass] is not configured"
  exit 4
fi

READ_ONLY="yes"
MODE_LABEL="read-only"
if [[ "$WRITABLE" == "1" ]]; then
  READ_ONLY="no"
  MODE_LABEL="read/write"
fi

BACKUP="${SAMBA_SHARES}.bak.$(date +%Y%m%d-%H%M%S)"
sudo cp -a "$SAMBA_SHARES" "$BACKUP"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

sudo awk -v value="$READ_ONLY" '
  BEGIN { in_keepass=0; changed=0 }
  /^\[keepass\]$/ { in_keepass=1; print; next }
  /^\[/ { in_keepass=0 }
  in_keepass && /^[[:space:]]*read only[[:space:]]*=/ {
    print "  read only = " value
    changed=1
    next
  }
  { print }
  END { if (!changed) exit 5 }
' "$SAMBA_SHARES" > "$TMP"

sudo testparm -s "$TMP" >/dev/null
sudo install -o root -g root -m 0644 "$TMP" "$SAMBA_SHARES"

SAMBA_SERVICE="smbd"
if systemctl list-unit-files 2>/dev/null | grep -q '^smb\.service'; then
  SAMBA_SERVICE="smb"
fi
# Restart (rather than reload) so existing SMB write handles are revoked too.
sudo systemctl restart "$SAMBA_SERVICE"

echo "[OK] KeePass share is now $MODE_LABEL"
