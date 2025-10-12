from flask import Blueprint

# Keep URL paths declared in view module (no url_prefix)
updates_bp = Blueprint("updates", __name__)

# Attach routes
from . import views_updates  # noqa: F401

