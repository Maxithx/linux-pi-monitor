from flask import Blueprint

keepass_bp = Blueprint('keepass', __name__)

from .views_keepass import *  # noqa: F401,F403

