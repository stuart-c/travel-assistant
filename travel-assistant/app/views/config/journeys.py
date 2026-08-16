"""Journeys configuration endpoints."""

from typing import Any, Dict, List, Optional
from flask import render_template, request

from app.models import Journey
from app.models.base import LOCATION_TYPES
from app.views.config import config_bp
from app.views.config.common import save_bulk_config

VALID_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun", "bank_holiday")


def clean_journey_item(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate and sanitize a single journey input item."""
    if not isinstance(entry, dict):
        return None

    name = str(entry.get("name", "")).strip()
    from_type = str(entry.get("from_type", "rail")).strip().lower()
    if from_type not in LOCATION_TYPES:
        from_type = "rail"

    from_id = str(entry.get("from_id", "")).strip()
    from_name = str(entry.get("from_name", "")).strip()

    to_type = str(entry.get("to_type", "rail")).strip().lower()
    if to_type not in LOCATION_TYPES:
        to_type = "rail"

    to_id = str(entry.get("to_id", "")).strip()
    to_name = str(entry.get("to_name", "")).strip()

    if not name or not (from_id and from_name and to_id and to_name):
        return None

    raw_time_settings = entry.get("time_settings", [])
    cleaned_time_settings: List[Dict[str, Any]] = []
    if isinstance(raw_time_settings, list):
        for tw in raw_time_settings:
            if not isinstance(tw, dict):
                continue
            days = tw.get("days", [])
            if not isinstance(days, list):
                days = []
            valid_days = [
                str(d).lower().strip()
                for d in days
                if str(d).lower().strip() in VALID_DAYS
            ]
            mode = str(tw.get("mode", "depart")).lower().strip()
            if mode not in ("depart", "arrive"):
                mode = "depart"
            start_time = str(tw.get("start_time", "")).strip()
            end_time = str(tw.get("end_time", "")).strip()

            cleaned_time_settings.append(
                {
                    "days": valid_days,
                    "mode": mode,
                    "start_time": start_time,
                    "end_time": end_time,
                }
            )

    return {
        "name": name,
        "from_type": from_type,
        "from_id": from_id,
        "from_name": from_name,
        "to_type": to_type,
        "to_id": to_id,
        "to_name": to_name,
        "time_settings": cleaned_time_settings,
    }


@config_bp.route("/journeys", methods=["GET", "POST"])
def journeys() -> Any:
    """Manage configured travel journeys and multi-time-window schedules."""
    if request.method == "POST":
        return save_bulk_config(
            form_key="journeys_json",
            model_class=Journey,
            clean_item_func=clean_journey_item,
            entity_label="Journeys",
            redirect_endpoint="config.journeys",
        )

    current_journeys = [j.to_dict() for j in Journey.select()]
    return render_template(
        "config_journeys.html",
        journeys=current_journeys,
        active_tab="journeys",
    )
