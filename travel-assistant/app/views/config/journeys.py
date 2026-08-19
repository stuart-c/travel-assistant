"""Journeys configuration endpoints."""

from typing import Any, Dict, Optional
from app.models import Journey, JourneyTimeSetting
from app.models.base import LOCATION_TYPES
from app.sync.walking_sync import trigger_journey_walking_sync_async
from app.views.config import config_bp
from app.views.config.common import save_changeset_config
from flask import current_app, jsonify, render_template, request


def _trigger_walking_sync_if_changed(stats: Dict[str, int]) -> None:
    """Trigger background walking route synchronisation when journeys are modified."""
    if (
        stats.get("added", 0) > 0
        or stats.get("updated", 0) > 0
        or stats.get("deleted", 0) > 0
    ):
        try:
            app_obj = current_app._get_current_object() if current_app else None
            trigger_journey_walking_sync_async(app_obj)
        except Exception:
            pass


def clean_journey_item(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate and sanitise a single journey input item."""
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

    item_id: Optional[int] = None
    if entry.get("id") is not None and str(entry.get("id")).strip():
        try:
            item_id = int(entry.get("id"))
        except (ValueError, TypeError):
            item_id = None

    raw_time_settings = entry.get("time_settings", [])
    cleaned_time_settings: list[Dict[str, Any]] = []
    if isinstance(raw_time_settings, list):
        for tw in raw_time_settings:
            if not isinstance(tw, dict):
                continue
            try:
                setting_obj = JourneyTimeSetting.model_validate(tw)
                cleaned_time_settings.append(setting_obj.model_dump())
            except Exception:
                continue

    result: Dict[str, Any] = {
        "name": name,
        "from_type": from_type,
        "from_id": from_id,
        "from_name": from_name,
        "to_type": to_type,
        "to_id": to_id,
        "to_name": to_name,
        "time_settings": cleaned_time_settings,
    }
    if item_id is not None:
        result["id"] = item_id

    return result


@config_bp.route("/journeys/data", methods=["GET"])
def journeys_data() -> Any:
    """Return all configured journeys as JSON for Grid.js remote data loading."""
    items = [j.to_dict() for j in Journey.select()]
    return jsonify({"data": items, "total": len(items)})


@config_bp.route("/journeys", methods=["GET", "POST"])
def journeys() -> Any:
    """Manage configured travel journeys and multi-time-window schedules."""
    if request.method == "POST":
        return save_changeset_config(
            form_key="journeys_json",
            model_class=Journey,
            clean_item_func=clean_journey_item,
            entity_label="Journeys",
            redirect_endpoint="config.journeys",
            post_save_hook=_trigger_walking_sync_if_changed,
        )

    return render_template(
        "config_journeys.html",
        active_tab="journeys",
    )
