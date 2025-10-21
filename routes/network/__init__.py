# routes/network/__init__.py
from flask import Blueprint

# Public blueprint for the network feature
network_bp = Blueprint("network", __name__)

# Import views to register routes on the blueprint
# (imports have side effects by attaching route handlers)
from . import views_summary  # noqa: F401
from . import views_dns      # noqa: F401
from . import views_wifi     # noqa: F401
from . import views_firewall # noqa: F401
