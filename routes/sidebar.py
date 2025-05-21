from flask import request

def register_sidebar_context(app):
    @app.context_processor
    def inject_sidebar_state():
        sidebar_state = request.cookies.get("sidebarState", "open")
        return dict(sidebar_state=sidebar_state)
