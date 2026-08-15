"""Settings and configuration views for Travel Assistant.

Provides web interface endpoints for managing add-on configuration,
credentials, and integration settings using the Post/Redirect/Get pattern.
"""

from typing import Any, Dict
from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.db import SettingsRepository

config_bp = Blueprint("config", __name__, url_prefix="/config")

CREDENTIAL_FIELDS = [
    "bus_api_key",
    "train_s3_bucket",
    "train_s3_access_key",
    "train_s3_secret_key",
    "train_s3_region",
    "train_live_api_key",
    "train_live_endpoint",
    "open_api_key",
    "open_api_base_url",
]


@config_bp.route("")
@config_bp.route("/")
def index() -> Any:
    """Redirect top-level /config to the default configuration page."""
    return redirect(url_for("config.credentials"))


@config_bp.route("/credentials", methods=["GET", "POST"])
def credentials() -> Any:
    """Manage API credentials and service tokens."""
    repo = SettingsRepository()

    if request.method == "POST":
        payload: Dict[str, str] = {}
        for field in CREDENTIAL_FIELDS:
            value = request.form.get(field, "").strip()
            payload[field] = value

        repo.set_many(payload, category="credentials")
        flash("API credentials saved successfully.", "success")
        return redirect(url_for("config.credentials"), code=303)

    stored = repo.get_all(category="credentials")
    current_credentials = {field: stored.get(field, "") for field in CREDENTIAL_FIELDS}

    return render_template(
        "config_credentials.html",
        credentials=current_credentials,
        active_tab="credentials",
    )
