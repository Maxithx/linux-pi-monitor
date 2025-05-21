# === routes/__init__.py ===
# Denne fil registrerer alle blueprint-routes i projektet.
# routes/__init__.py

def register_routes(app):
    from .glances import glances_bp
    from .settings import settings_bp
    from .dashboard import dashboard_bp
    from .logs import logs_bp
    from .terminal import terminal_bp

    app.register_blueprint(glances_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(logs_bp)
    app.register_blueprint(terminal_bp)
