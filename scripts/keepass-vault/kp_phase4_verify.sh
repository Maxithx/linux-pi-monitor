#!/usr/bin/env bash
set -euo pipefail
VAULT_USER="keepass"
VAULT_DIR="/srv/keepass/vault"

echo "[*] smbd status:"
SVC=smbd
if command -v systemctl >/dev/null 2>&1; then
  if systemctl list-unit-files | grep -q '^smb\.service'; then SVC=smb; fi
fi
systemctl is-active --quiet "$SVC"
echo "  [OK] $SVC is active"

echo "[*] Checking KeePass system user..."
id "$VAULT_USER" >/dev/null
echo "  [OK] user '$VAULT_USER' exists"

echo "[*] Checking vault directory..."
test -d "$VAULT_DIR"
echo "  [OK] $VAULT_DIR exists"

echo "[*] Validating Samba configuration..."
CONFIG="$(testparm -s 2>/dev/null)"
printf '%s\n' "$CONFIG" | grep -q '^\[keepass\]$'
echo "  [OK] testparm passed and [keepass] is configured"

if ! command -v smbclient >/dev/null 2>&1; then
  echo "[error] smbclient is not installed; run Phase 1 first"
  exit 5
fi
if [[ -z "${SMB_PASS:-}" ]]; then
  echo "[error] SMB_PASS is required for authenticated verification"
  exit 6
fi

echo "[*] Verifying authenticated access to //localhost/keepass..."
AUTH_FILE="$(mktemp)"
trap 'rm -f "$AUTH_FILE"' EXIT
chmod 600 "$AUTH_FILE"
{
  printf 'username = %s\n' "$VAULT_USER"
  printf 'password = %s\n' "$SMB_PASS"
} > "$AUTH_FILE"

# The share is intentionally configured with "browseable = no", so it will
# not appear in `smbclient -L`. Connect to it directly and perform a read-only
# directory listing instead.
smbclient //localhost/keepass -A "$AUTH_FILE" -c 'ls' >/dev/null
echo "  [OK] authenticated connection to [keepass] succeeded"

echo "[OK] Verification passed: Samba service active and KeePass share available"
