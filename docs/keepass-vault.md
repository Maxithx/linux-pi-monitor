# KeePass Vault Guide

This document explains the KeePass Vault flow in Linux Pi Monitor.

## Overview

The KeePass Vault page provisions a local-only Samba share on your Linux host so you can store and access a KeePassXC database from Windows.

The flow is split into four phases:

1. Install dependencies, create the vault user, and prepare the vault folder.
2. Configure Samba and create the `keepass` share.
3. Open firewall rules for the LAN only.
4. Verify the setup.

There is also a rollback action that removes the Samba share setup.

## Defaults

- Vault user: `keepass`
- Vault directory: `/srv/keepass/vault`
- Share name: `keepass`
- Default LAN subnet: `192.168.0.0/24`

## Phase 1 - Deps, User, Folder

Purpose:
- install required packages
- ensure the `keepass` system user exists
- create `/srv/keepass/vault`

Typical commands on the Pi:

```bash
sudo apt-get update -y
sudo apt-get install -y samba smbclient ufw
sudo adduser --system --home /srv/keepass --group --shell /usr/sbin/nologin keepass
sudo mkdir -p /srv/keepass/vault
sudo chown -R keepass:keepass /srv/keepass
sudo chmod 700 /srv/keepass/vault
```

## Phase 2 - Samba Share

Purpose:
- back up `smb.conf`
- ensure Samba binds to the LAN subnet
- create or replace the `keepass` share
- set the Samba password for the `keepass` user
- restart Samba

Typical share block:

```ini
[keepass]
  path = /srv/keepass/vault
  browseable = no
  read only = no
  valid users = keepass
  force user = keepass
  create mask = 0600
  directory mask = 0700
  hosts allow = 192.168.0.0/24
  smb encrypt = required
```

Windows mapping helper:

```cmd
net use Z: \\192.168.0.212\keepass /user:keepass *
```

## Phase 3 - Firewall for LAN

Purpose:
- allow SSH from the LAN if needed
- allow Samba ports only from the LAN subnet
- optionally allow Glances on `61208/tcp`

Typical UFW rules:

```bash
sudo ufw allow from 192.168.0.0/24 to any port 22 proto tcp
sudo ufw allow from 192.168.0.0/24 to any port 137 proto udp
sudo ufw allow from 192.168.0.0/24 to any port 138 proto udp
sudo ufw allow from 192.168.0.0/24 to any port 139 proto tcp
sudo ufw allow from 192.168.0.0/24 to any port 445 proto tcp
```

## Phase 4 - Verify

Purpose:
- confirm the share exists
- confirm Samba can see the share locally
- verify the Windows mapping command

Useful check:

```bash
smbclient -L localhost -U keepass
```

## Rollback

Purpose:
- remove the `keepass` block from Samba shares
- disable the Samba account if needed
- restart Samba

## Troubleshooting

If Windows shows `System error 67` or `network name cannot be found`:
- check that the Pi is on the same LAN subnet
- check that `hosts allow` matches your LAN
- check that Samba is bound to the correct interfaces
- check `testparm -s` for stale `192.168.1.0/24` values
- make sure the uploaded scripts on the Pi are line-ending clean

If a script fails with `set: pipefail` or `pipefail\r`:
- the uploaded `.sh` file still has CRLF line endings
- re-upload the scripts after line-ending normalization