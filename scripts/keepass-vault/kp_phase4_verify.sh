#!/usr/bin/env bash
set -euo pipefail
echo "[*] smbd status:"
SVC=smbd
if command -v systemctl >/dev/null 2>&1; then
  if systemctl list-unit-files | grep -q '^smb\.service'; then SVC=smb; fi
fi
systemctl is-active "$SVC" && echo "  $SVC is active"
echo "[*] testparm (first 20 lines):"
testparm -s | head -n 20
echo "[*] Next: run 'smbclient -L localhost -U keepass' to confirm [keepass] is listed."
echo "[OK] Phase 4 done"
