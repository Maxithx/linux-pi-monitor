# === routes/__init__.py ===
# This file registers all blueprint routes in the project.

def register_routes(app):
    from .glances import glances_bp
    from .settings import settings_bp
    from .dashboard import dashboard_bp
    from .logs import logs_bp
    from .terminal import terminal_bp
    from .software import software_bp
    from .profiles_routes import profiles_bp  # <-- FIX: was `.profiles`

    # Register each blueprint with the Flask app
    app.register_blueprint(glances_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(logs_bp)
    app.register_blueprint(terminal_bp)
    app.register_blueprint(software_bp)
    app.register_blueprint(profiles_bp)
