# === sidebar.py ===
# This file provides the current sidebar state (open/closed)
# based on a cookie and makes it available to all templates.

from flask import request

def register_sidebar_context(app):
    @app.context_processor
    def inject_sidebar_state():
        # Read sidebar state from cookies; default to "open"
        sidebar_state = request.cookies.get("sidebarState", "open")
        return dict(sidebar_state=sidebar_state)
