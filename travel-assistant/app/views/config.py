"""Settings and configuration views for Travel Assistant.

Provides web interface endpoints for managing add-on configuration,
credentials, and integration settings using the Post/Redirect/Get pattern.
"""

from typing import Any, Dict
from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from app.db import SettingsRepository
from app.validators import validate_service_credentials

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


@config_bp.route("/credentials/validate", methods=["POST"])
def validate_credentials() -> Any:
    """Validate a specific credential configuration asynchronously."""
    raw_payload = request.get_json(silent=True)
    if not isinstance(raw_payload, dict):
        raw_payload = request.form.to_dict()

    service = raw_payload.get("service", "").strip()
    if not service:
        return (
            jsonify(
                {
                    "valid": False,
                    "message": "Service name is required for validation.",
                }
            ),
            400,
        )

    # Fall back to saved repository credentials if fields are not present in payload
    repo = SettingsRepository()
    stored = repo.get_all(category="credentials")
    merged_payload = dict(stored)
    merged_payload.update(raw_payload)

    is_valid, message = validate_service_credentials(service, merged_payload)
    status_code = 400 if message.startswith("Unknown service") else 200

    return (
        jsonify(
            {
                "valid": is_valid,
                "message": message,
                "service": service,
            }
        ),
        status_code,
    )
