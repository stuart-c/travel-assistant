"""Journeys configuration endpoints."""

from typing import Any, Dict, Optional

from app.models import Journey, JourneyTimeSetting
from app.models.base import LOCATION_TYPES
from app.sync.worker import request_sync
from app.views.config import config_bp
from app.views.config.common import (
    PageConfig,
    parse_optional_id,
    register_config_page,
    sanitise_choice,
)


def _trigger_syncs_if_changed(
    stats: Dict[str, int], changeset: Dict[str, list[Any]]
) -> None:
    """Queue targeted walking, timetable, and route synchronisation when journeys are modified."""
    modified_entries = changeset.get("added", []) + changeset.get("updated", [])
    if not modified_entries:
        return

    has_location_endpoint = False
    has_bus_endpoint = False

    for entry in modified_entries:
        if not isinstance(entry, dict):
            continue

        from_type = str(entry.get("from_type", "")).strip().lower()
        to_type = str(entry.get("to_type", "")).strip().lower()

        if from_type in ("ha", "custom") or to_type in ("ha", "custom"):
            has_location_endpoint = True

        if from_type == "bus" or to_type == "bus":
            has_bus_endpoint = True

    try:
        if has_location_endpoint:
            request_sync("walking")
        if has_bus_endpoint:
            request_sync("bus_timetables")
        request_sync("journey_routes")
    except Exception:
        pass


def clean_journey_item(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate and sanitise a single journey input item."""
    if not isinstance(entry, dict):
        return None

    name = str(entry.get("name", "")).strip()
    from_type = sanitise_choice(entry.get("from_type"), LOCATION_TYPES, "rail")
    from_id = str(entry.get("from_id", "")).strip()
    from_name = str(entry.get("from_name", "")).strip()

    to_type = sanitise_choice(entry.get("to_type"), LOCATION_TYPES, "rail")
    to_id = str(entry.get("to_id", "")).strip()
    to_name = str(entry.get("to_name", "")).strip()

    if not name or not (from_id and from_name and to_id and to_name):
        return None

    item_id = parse_optional_id(entry.get("id"))

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
        "calculated_routes": (
            entry.get("calculated_routes")
            if "calculated_routes" in entry
            and entry.get("calculated_routes") is not None
            else None
        ),
    }
    if item_id is not None:
        result["id"] = item_id

    return result


register_config_page(
    config_bp,
    PageConfig(
        route="/journeys",
        endpoint="journeys",
        template="config_journeys.html",
        model_class=Journey,
        clean_item_func=clean_journey_item,
        entity_label="Journeys",
        post_save_hook=_trigger_syncs_if_changed,
    ),
)
