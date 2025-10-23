"""Back-compat shim for the dashboard blueprint.

The blueprint has moved to routes.dashboard.dashboard. This module simply
re-exports it so existing imports keep working.
"""

from .dashboard.dashboard import dashboard_bp  # noqa: F401

