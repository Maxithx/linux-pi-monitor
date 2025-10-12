# routes/updates_drivers/driver_mint.py
# Linux Mint driver — reuses DebianDriver logic (stable and consistent).

from .driver_debian import DebianDriver as MintDriver

__all__ = ["MintDriver"]
