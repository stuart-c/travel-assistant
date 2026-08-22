"""Travel Assistant Flask Application.

Provides the Home Assistant Add-on web interface and API endpoints.
"""

import logging
import os
import sys
import uuid
from typing import Any, Dict
from flask import Flask, render_template, jsonify, request

from app import db
from app.logging_config import GunicornLogger, StaticAccessLogFilter, configure_logging
from app.sync import request_sync, start_background_worker
from app.views.config import config_bp

__all__ = [
    "app",
    "create_app",
    "GunicornLogger",
    "StaticAccessLogFilter",
    "configure_logging",
]

STARTUP_CACHE_BUST = uuid.uuid4().hex[:8]


logger = logging.getLogger(__name__)


class IngressMiddleware:
    """WSGI middleware to handle Home Assistant Ingress dynamic subpaths."""

    def __init__(self, wsgi_app: Any) -> None:
        self.wsgi_app = wsgi_app

    def __call__(self, environ: Dict[str, Any], start_response: Any) -> Any:
        ingress_path = environ.get("HTTP_X_INGRESS_PATH", "").rstrip("/")
        if ingress_path:
            environ["SCRIPT_NAME"] = ingress_path
        return self.wsgi_app(environ, start_response)


def create_app(test_config: Dict[str, Any] = None) -> Flask:
    """Application factory for the Travel Assistant Flask service."""
    configure_logging()

    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-key-change-in-prod"),
        VERSION=os.environ.get("BUILD_VERSION", "0.1.0"),
        APP_NAME="Travel Assistant",
    )

    if test_config:
        app.config.update(test_config)

    log_level_name = os.environ.get("LOG_LEVEL", "INFO").upper().strip()
    logger.info(
        "Initialising %s v%s (log level: %s)...",
        app.config.get("APP_NAME"),
        app.config.get("VERSION"),
        log_level_name,
    )

    # Initialise SQLite database
    db.init_app(app)

    # Enable Ingress middleware
    app.wsgi_app = IngressMiddleware(app.wsgi_app)

    # Register blueprints
    app.register_blueprint(config_bp)

    # Start background synchronization daemon worker if enabled
    if (
        not app.config.get("TESTING")
        and not app.config.get("DISABLE_BACKGROUND_WORKER", False)
        and "pytest" not in sys.modules
        and not os.environ.get("PYTEST_CURRENT_TEST")
    ):
        start_background_worker(app)

    # Refresh live LDBWS Swagger schema on startup outside test environments
    if (
        not app.config.get("TESTING")
        and "pytest" not in sys.modules
        and not os.environ.get("PYTEST_CURRENT_TEST")
    ):
        try:
            from app.datasources.train_live import sync_swagger_schema

            sync_swagger_schema()
            logger.info("National Rail Darwin Swagger schema initialised.")
        except Exception as exc:
            logger.warning(
                "Could not sync National Rail Darwin Swagger schema on startup: %s", exc
            )

    @app.context_processor
    def inject_ingress_path() -> Dict[str, str]:
        """Inject ingress base path and cache busting token into templates."""
        ingress_path = request.headers.get("X-Ingress-Path", "").rstrip("/")
        return {
            "ingress_path": ingress_path,
            "app_version": app.config.get("VERSION", "0.1.0"),
            "app_name": app.config.get("APP_NAME", "Travel Assistant"),
            "cache_bust": STARTUP_CACHE_BUST,
        }

    @app.route("/")
    def index() -> str:
        """Render the primary dashboard page."""
        return render_template(
            "index.html",
            message="Welcome to Travel Assistant for Home Assistant.",
        )

    @app.route("/api/ping")
    def ping() -> Dict[str, str]:
        """Health check endpoint."""
        return jsonify({"status": "ok"})

    @app.route("/api/info")
    def info() -> Dict[str, Any]:
        """Add-on information and metadata."""
        return jsonify(
            {
                "name": app.config.get("APP_NAME"),
                "version": app.config.get("VERSION"),
                "ingress_enabled": True,
            }
        )

    @app.route("/api/sync", methods=["POST"], strict_slashes=False)
    @app.route("/api/sync/<table_name>", methods=["POST"], strict_slashes=False)
    def api_sync(table_name: str = "all") -> Any:
        """API endpoint to queue dataset synchronisation on demand."""
        from app.sync.worker import SYNC_REGISTRY

        norm_name = table_name.lower().strip()
        valid_names = [e.table_name for e in SYNC_REGISTRY]

        if norm_name in ("all", ""):
            for entry in SYNC_REGISTRY:
                request_sync(entry.table_name)
            return jsonify(
                {
                    "success": True,
                    "status": "queued",
                    "message": "All sync tables have been queued.",
                    "tables": valid_names,
                }
            )

        if norm_name not in valid_names:
            return (
                jsonify(
                    {
                        "success": False,
                        "status": "error",
                        "message": (
                            f"Unknown table: '{norm_name}'. "
                            f"Valid tables are: {', '.join(valid_names)}."
                        ),
                    }
                ),
                400,
            )

        request_sync(norm_name)
        return jsonify(
            {
                "success": True,
                "table": norm_name,
                "status": "queued",
                "message": (
                    f"Synchronisation of '{norm_name}' has been queued "
                    "and will run shortly."
                ),
            }
        )

    @app.errorhandler(404)
    def not_found(error: Any) -> Any:
        """Handle 404 errors with JSON or HTML depending on request path."""
        if request.path.startswith("/api/"):
            return jsonify({"error": "Not Found", "status": 404}), 404
        return (
            render_template(
                "index.html",
                message="Page not found",
                error=True,
            ),
            404,
        )

    return app


app = create_app()

if __name__ == "__main__":  # pragma: no cover
    port = int(os.environ.get("PORT", 8099))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
