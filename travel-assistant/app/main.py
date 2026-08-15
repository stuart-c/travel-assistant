"""Travel Assistant Flask Application.

Provides the Home Assistant Add-on web interface and API endpoints.
"""

import os
from typing import Any, Dict
from flask import Flask, render_template, jsonify, request

from app import db
from app.views.config import config_bp


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

    # Initialise SQLite database
    db.init_app(app)

    # Enable Ingress middleware
    app.wsgi_app = IngressMiddleware(app.wsgi_app)

    # Register blueprints
    app.register_blueprint(config_bp)

    @app.context_processor
    def inject_ingress_path() -> Dict[str, str]:
        """Inject ingress base path into templates."""
        ingress_path = request.headers.get("X-Ingress-Path", "").rstrip("/")
        return {
            "ingress_path": ingress_path,
            "app_version": app.config.get("VERSION", "0.1.0"),
            "app_name": app.config.get("APP_NAME", "Travel Assistant"),
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

    @app.route("/api/timetables/search")
    def api_search_timetables() -> Any:
        """Search and lookup timetable feeds, stations, and bus routes."""
        from app.views.config import search_timetables

        return search_timetables()

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
