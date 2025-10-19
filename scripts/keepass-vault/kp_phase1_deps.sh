#!/usr/bin/env bash
set -euo pipefail
VAULT_USER="keepass"
VAULT_BASE="/srv/keepass"
VAULT_DIR="${VAULT_BASE}/vault"

echo "[*] Detect distro and package manager..."
OS_ID=""; OS_LIKE=""; PM=""; UPDATE=""; INSTALL=""
if [ -r /etc/os-release ]; then
  OS_ID=$(grep -E '^ID=' /etc/os-release | cut -d= -f2 | tr -d '"') || true
  OS_LIKE=$(grep -E '^ID_LIKE=' /etc/os-release | cut -d= -f2 | tr -d '"') || true
fi

pick_pm() {
  if command -v apt-get >/dev/null 2>&1; then
    PM=apt; UPDATE='sudo apt-get update -y'; INSTALL='sudo apt-get install -y'
  elif command -v dnf >/dev/null 2>&1; then
    PM=dnf; UPDATE='sudo dnf -y makecache'; INSTALL='sudo dnf -y install'
  elif command -v yum >/dev/null 2>&1; then
    PM=yum; UPDATE='sudo yum -y makecache'; INSTALL='sudo yum -y install'
  elif command -v zypper >/dev/null 2>&1; then
    PM=zypper; UPDATE='sudo zypper --non-interactive refresh'; INSTALL='sudo zypper --non-interactive install --auto-agree-with-licenses'
  elif command -v pacman >/dev/null 2>&1; then
    PM=pacman; UPDATE='sudo pacman -Sy --noconfirm'; INSTALL='sudo pacman -S --noconfirm'
  elif command -v apk >/dev/null 2>&1; then
    PM=apk; UPDATE='sudo apk update'; INSTALL='sudo apk add --no-cache'
  else
    echo "[error] No supported package manager found." >&2; exit 1
  fi
}

pick_pm
echo "[*] Using PM=$PM"

echo "[*] Installing dependencies..."
eval "$UPDATE"

# Pick package names per family
PKG_SAMBA_SERVER=samba
PKG_SAMBA_CLIENT=smbclient
PKG_FIREWALL=ufw
case "$PM" in
  dnf|yum)
    PKG_SAMBA_SERVER=samba
    PKG_SAMBA_CLIENT=samba-client
    PKG_FIREWALL=firewalld
    ;;
  zypper)
    PKG_SAMBA_SERVER=samba
    PKG_SAMBA_CLIENT=samba-client
    PKG_FIREWALL=firewalld
    ;;
  pacman)
    PKG_SAMBA_SERVER=samba
    PKG_SAMBA_CLIENT=smbclient
    PKG_FIREWALL=firewalld
    ;;
  apk)
    PKG_SAMBA_SERVER=samba
    PKG_SAMBA_CLIENT=samba-client
    PKG_FIREWALL=
    ;;
esac

set +e
eval "$INSTALL $PKG_SAMBA_SERVER" || true
if [ -n "$PKG_SAMBA_CLIENT" ]; then eval "$INSTALL $PKG_SAMBA_CLIENT" || true; fi
if [ -n "$PKG_FIREWALL" ]; then eval "$INSTALL $PKG_FIREWALL" || true; fi
set -e

# Create system user if missing (portable)
if ! id -u "$VAULT_USER" >/dev/null 2>&1; then
  echo "[*] Creating system user '$VAULT_USER'..."
  NOLOGIN="$(command -v nologin || command -v /usr/sbin/nologin || command -v /sbin/nologin || echo /sbin/nologin)"
  if command -v adduser >/dev/null 2>&1; then
    sudo adduser --system --home "$VAULT_BASE" --group --shell "$NOLOGIN" "$VAULT_USER"
  else
    sudo groupadd -f "$VAULT_USER" || true
    sudo useradd -r -M -d "$VAULT_BASE" -s "$NOLOGIN" -g "$VAULT_USER" "$VAULT_USER" || true
  fi
fi

echo "[*] Preparing vault directory..."
sudo mkdir -p "$VAULT_DIR"
sudo chown -R "$VAULT_USER:$VAULT_USER" "$VAULT_BASE"
sudo chmod 700 "$VAULT_DIR"

echo "[OK] Phase 1 done: deps/user/dir ready at $VAULT_DIR"
