from flask import Blueprint

# Keep existing URLs unchanged (no url_prefix) to avoid breaking JS
settings_bp = Blueprint("settings", __name__)

# Re-export helpers for external imports (app.py, others)
try:
    from .views_settings import (  # noqa: F401
        test_ssh_connection,
        _get_active_ssh_settings,
        _glances_url_from_settings,
        _is_configured,
    )
except Exception:
    # During partial refactors or import-time errors, allow app to start
    pass

# Import routes/modules that attach to blueprints or are used externally
from . import views_settings  # noqa: F401
from . import glances_manage  # noqa: F401
from . import glances         # noqa: F401
from . import software        # noqa: F401
from . import views_profiles  # noqa: F401

