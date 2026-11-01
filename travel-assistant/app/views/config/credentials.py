"""Credentials configuration and validation endpoints."""

import logging
from typing import Any, Dict
from flask import (
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from app.models import Setting
from app.services.api_tracker import (
    get_recent_calls,
    get_usage_summary,
    global_api_cache,
)
from app.validators import validate_service_credentials
from app.views.config import config_bp

logger = logging.getLogger(__name__)

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
    "open_api_model",
    "google_maps_api_key",
    "google_maps_region",
    "google_maps_daily_limit",
    "google_maps_monthly_limit",
]


@config_bp.route("")
@config_bp.route("/")
def index() -> Any:
    """Redirect top-level /config to the default configuration page."""
    return redirect(url_for("config.credentials"))


@config_bp.route("/credentials", methods=["GET", "POST"])
def credentials() -> Any:
    """Manage API credentials and service tokens."""
    if request.method == "POST":
        payload: Dict[str, str] = {}
        for field in CREDENTIAL_FIELDS:
            if field in request.form:
                value = request.form.get(field, "").strip()
                payload[field] = value

        if payload:
            Setting.bulk_set(payload, category="credentials")
            logger.info(
                "Saved API credentials configuration for fields: %s.",
                ", ".join(payload.keys()),
            )
        flash("API credentials saved successfully.", "success")
        return redirect(url_for("config.credentials"), code=303)

    stored = Setting.get_by_category("credentials")
    current_credentials = {field: stored.get(field, "") for field in CREDENTIAL_FIELDS}
    if not current_credentials.get("open_api_model"):
        current_credentials["open_api_model"] = "gpt-4o-mini"
    if not current_credentials.get("google_maps_region"):
        current_credentials["google_maps_region"] = "uk"
    if not current_credentials.get("google_maps_daily_limit"):
        current_credentials["google_maps_daily_limit"] = "100"
    if not current_credentials.get("google_maps_monthly_limit"):
        current_credentials["google_maps_monthly_limit"] = "1000"

    api_usage = get_usage_summary("google_maps")
    recent_calls = get_recent_calls(limit=15, provider="google_maps")

    return render_template(
        "config_credentials.html",
        credentials=current_credentials,
        api_usage=api_usage,
        recent_calls=recent_calls,
        active_tab="credentials",
    )


@config_bp.route("/credentials/clear_cache", methods=["POST"])
def clear_api_cache() -> Any:
    """Clear external API in-memory response cache."""
    provider = request.form.get("provider") or None
    cleared = global_api_cache.clear(provider=provider)
    flash(f"Successfully purged {cleared} cached API responses.", "success")
    return redirect(url_for("config.credentials"), code=303)


@config_bp.route("/credentials/api_usage", methods=["GET"])
def api_usage_summary_json() -> Any:
    """Retrieve JSON summary of external API usage and quota status."""
    provider = request.args.get("provider", "google_maps")
    summary = get_usage_summary(provider=provider)
    recent = get_recent_calls(limit=25, provider=provider)
    return jsonify({"summary": summary, "recent_calls": recent})


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

    # Fall back to saved database credentials if fields are not present in payload
    stored = Setting.get_all_dict()
    merged_payload = dict(stored)
    merged_payload.update(raw_payload)

    is_valid, message, extra_data = validate_service_credentials(
        service, merged_payload
    )
    status_code = 400 if message.startswith("Unknown service") else 200

    logger.info(
        "Credentials validation probe for '%s': valid=%s (%s).",
        service,
        is_valid,
        message,
    )

    response_body = {
        "valid": is_valid,
        "message": message,
        "service": service,
    }
    if extra_data:
        response_body.update(extra_data)

    return (
        jsonify(response_body),
        status_code,
    )
