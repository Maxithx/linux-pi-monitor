# === routes/__init__.py ===
# Registers all blueprints

def register_routes(app):
    """
    Central place to import + register all app blueprints.

    - routes/glances.py        => glances_bp   (proxy namespace, e.g. /glances-proxy/*, /api/3/*)
    - routes/settings.py       => settings_bp  (settings UI, SSH checks, glances iframe)
    - routes/glances_manage.py => glances_admin_bp (install/uninstall/status/log/service/diag at /glances/*)
    - routes/updates.py        => updates_bp   (/updates pages + actions)

    Notes for updates:
    - The /updates endpoints use OS-specific drivers located in:
        routes/drivers/
            os_base.py
            os_debian.py
            os_mint.py
            os_detect.py
    """

    # --- GLOBAL context for ALL templates (fix 500 on /dashboard etc.) ---
    @app.context_processor
    def inject_connection_status_global():
        try:
            from .settings import test_ssh_connection
            status = "connected" if test_ssh_connection() else "disconnected"
        except Exception:
            status = "disconnected"
        return {"connection_status": status}

    # Ensure driver package is initialized (no-op import; avoids lints/caches)
    try:
        from .drivers import DebianDriver, MintDriver, choose_driver_name  # noqa: F401
    except Exception:
        # Safe to ignore; updates feature handles driver errors gracefully.
        pass

    # --- Imports AFTER the context-processor to avoid circulars ---
    from .settings import settings_bp                            # settings + iframe
    from .settings.glances_manage import glances_bp as glances_admin_bp   # /glances/*
    from .settings.glances import glances_bp as glances_compat_bp        # /glances-proxy/*
    from .updates import updates_bp                              # /updates/*
    from .dashboard.dashboard import dashboard_bp
    from .logs import logs_bp
    from .terminal import terminal_bp
    from .settings.software import software_bp
    from .settings.views_profiles import profiles_bp
    from .network import network_bp
    from .drivers import drivers_bp
    from .keepass import keepass_bp


    # UI blueprints first
    app.register_blueprint(settings_bp)        # /settings, /glances (iframe)
    app.register_blueprint(dashboard_bp)       # /dashboard
    app.register_blueprint(logs_bp)            # /logs
    app.register_blueprint(terminal_bp)        # /terminal
    app.register_blueprint(software_bp)        # /software
    app.register_blueprint(profiles_bp)        # /profiles/*
    app.register_blueprint(keepass_bp)         # /api/keepass/*

    # Admin/system endpoints
    app.register_blueprint(glances_admin_bp)   # /glances/* (install/uninstall/status/log/service/diag)
    app.register_blueprint(updates_bp)         # /updates, /updates/*
    # Proxy last (namespaced separately)
    app.register_blueprint(glances_compat_bp)  # /glances-proxy/* and /api/3/*
    app.register_blueprint(network_bp)         # /network, /network/*
    app.register_blueprint(drivers_bp)           # /drivers
