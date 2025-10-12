from flask import Blueprint

terminal_bp = Blueprint("terminal", __name__)

from . import views_terminal  # noqa: F401

