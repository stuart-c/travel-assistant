"""Journey tracking view and live status API endpoints."""

import json
import logging
from typing import Any, Optional
from flask import Blueprint, jsonify, render_template, request

from app.datasources.homeassistant import HomeAssistantClient
from app.datasources.train_live import TrainLiveClient
from app.services.dispatcher import get_journey_live_tracking_data

logger = logging.getLogger(__name__)

journey_bp = Blueprint("journey", __name__)


@journey_bp.after_request
def add_no_cache_headers(response: Any) -> Any:
    """Disable browser caching for live journey tracking pages and telemetry."""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@journey_bp.route("/journey", methods=["GET"])
def view_journey() -> str:
    """Render the live journey tracking and progression screen."""
    raw_id = request.args.get("journey_id") or request.args.get("id")
    journey_id: Optional[int] = None
    if raw_id:
        try:
            journey_id = int(raw_id)
        except (ValueError, TypeError):
            pass

    ha_client = HomeAssistantClient.from_settings()
    live_client = TrainLiveClient.from_settings()

    tracking_data = get_journey_live_tracking_data(
        journey_id=journey_id,
        ha_client=ha_client,
        live_client=live_client,
    )

    return render_template(
        "journey.html",
        data=tracking_data,
        initial_data_json=json.dumps(tracking_data),
    )


@journey_bp.route("/api/journey/live", methods=["GET"])
def api_journey_live() -> Any:
    """Return real-time tracking telemetry, leg progression, and Stuart's location."""
    raw_id = request.args.get("journey_id") or request.args.get("id")
    journey_id: Optional[int] = None
    if raw_id:
        try:
            journey_id = int(raw_id)
        except (ValueError, TypeError):
            pass

    ha_client = HomeAssistantClient.from_settings()
    live_client = TrainLiveClient.from_settings()

    data = get_journey_live_tracking_data(
        journey_id=journey_id,
        ha_client=ha_client,
        live_client=live_client,
    )

    return jsonify(data)
