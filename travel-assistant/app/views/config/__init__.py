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
)
from app.views.config.credentials import CREDENTIAL_FIELDS  # noqa: E402, F401
from app.views.config.places import search_places  # noqa: E402, F401
from app.validators import validate_service_credentials  # noqa: E402, F401

__all__ = [
    "config_bp",
    "CREDENTIAL_FIELDS",
    "search_places",
    "validate_service_credentials",
    "credentials",
    "journeys",
    "locations",
    "places",
    "sync",
    "timetables",
    "transfers",
]
