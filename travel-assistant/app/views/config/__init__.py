"""Configuration views and REST API endpoints for Travel Assistant."""

from typing import Any
from flask import Blueprint

config_bp = Blueprint("config", __name__, url_prefix="/config")


@config_bp.after_request
def add_no_cache_headers(response: Any) -> Any:
    """Disable browser caching for all configuration pages and endpoints."""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# Import submodules to register routes with config_bp
from app.views.config import (  # noqa: E402, F401
    credentials,
    journeys,
    locations,
    places,
    sync,
    timetables,
    transfers,
    walking,
)

__all__ = [
    "config_bp",
    "credentials",
    "journeys",
    "locations",
    "places",
    "sync",
    "timetables",
    "transfers",
    "walking",
]
