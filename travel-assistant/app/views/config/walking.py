"""Walking connections configuration endpoints."""

from typing import Any, Dict, Optional

from app.models import Walking
from app.models.base import LOCATION_TYPES
from app.sync.worker import request_sync
from app.views.config import config_bp
from app.views.config.common import PageConfig, register_config_page


def _trigger_bus_sync_if_bus_changed(
    stats: Dict[str, int], changeset: Dict[str, list[Any]]
) -> None:
    """Queue bus timetable synchronisation when walking routes involving bus stops are modified."""
    modified_entries = changeset.get("added", []) + changeset.get("updated", [])
    if not modified_entries:
        return

    has_bus_endpoint = False
    for entry in modified_entries:
        if not isinstance(entry, dict):
            continue

        start_type = str(entry.get("start_type", "")).strip().lower()
        finish_type = str(entry.get("finish_type", "")).strip().lower()

        if start_type == "bus" or finish_type == "bus":
            has_bus_endpoint = True
            break

    if has_bus_endpoint:
        try:
            request_sync("bus_timetables")
        except Exception:
            pass


def clean_walking_item(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate and sanitise a single walking route item."""
    if not isinstance(entry, dict):
        return None

    start_type = str(entry.get("start_type", "custom")).lower().strip()
    if start_type not in LOCATION_TYPES:
        start_type = "custom"

    start_id = str(entry.get("start_id", "")).strip()
    start_name = str(entry.get("start_name", "")).strip()

    finish_type = str(entry.get("finish_type", "custom")).lower().strip()
    if finish_type not in LOCATION_TYPES:
        finish_type = "custom"

    finish_id = str(entry.get("finish_id", "")).strip()
    finish_name = str(entry.get("finish_name", "")).strip()

    if not (start_id and start_name and finish_id and finish_name):
        return None

    try:
        time_needed = max(1, int(entry.get("time_needed_minutes", 5)))
    except (ValueError, TypeError):
        time_needed = 5

    item_id: Optional[int] = None
    if entry.get("id") is not None and str(entry.get("id")).strip():
        try:
            item_id = int(entry.get("id"))
        except (ValueError, TypeError):
            item_id = None

    result: Dict[str, Any] = {
        "start_type": start_type,
        "start_id": start_id,
        "start_name": start_name,
        "finish_type": finish_type,
        "finish_id": finish_id,
        "finish_name": finish_name,
        "time_needed_minutes": time_needed,
        "bidirectional": bool(entry.get("bidirectional", True)),
        "auto_generated": bool(entry.get("auto_generated", False)),
    }
    if item_id is not None:
        result["id"] = item_id

    return result


register_config_page(
    config_bp,
    PageConfig(
        route="/walking",
        endpoint="walking",
        template="config_walking.html",
        model_class=Walking,
        clean_item_func=clean_walking_item,
        entity_label="Walking",
        scope_filter=(Walking.auto_generated == False),  # noqa: E712
        post_save_hook=_trigger_bus_sync_if_bus_changed,
    ),
)
