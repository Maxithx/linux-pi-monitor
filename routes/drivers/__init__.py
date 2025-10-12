from flask import Blueprint

drivers_bp = Blueprint("drivers", __name__, url_prefix="/drivers")

# Attach HTTP routes
from . import views_drivers  # noqa: F401

# Export OS driver utilities for updates feature
try:  # noqa: E722
    from .os_debian import DebianDriver  # noqa: F401
    from .os_mint import MintDriver      # noqa: F401
    from .os_detect import choose_driver_name, fetch_os_info  # noqa: F401
except Exception:
    # It's fine if these fail at import-time; updates will handle gracefully
    pass

