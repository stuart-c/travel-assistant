"""Walking connections configuration endpoints."""

from typing import Any, Dict, Optional
from flask import render_template, request

from app.models import Walking
from app.models.base import LOCATION_TYPES
from app.views.config import config_bp
from app.views.config.common import save_bulk_config


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

    return {
        "start_type": start_type,
        "start_id": start_id,
        "start_name": start_name,
        "finish_type": finish_type,
        "finish_id": finish_id,
        "finish_name": finish_name,
        "time_needed_minutes": time_needed,
        "bidirectional": bool(entry.get("bidirectional", True)),
    }


@config_bp.route("/walking", methods=["GET", "POST"])
def walking() -> Any:
    """Manage configured walking connections between locations."""
    if request.method == "POST":
        return save_bulk_config(
            form_key="walking_json",
            model_class=Walking,
            clean_item_func=clean_walking_item,
            entity_label="Walking",
            redirect_endpoint="config.walking",
        )

    current_walking = [w.to_dict() for w in Walking.select()]
    return render_template(
        "config_walking.html",
        walking_routes=current_walking,
        active_tab="walking",
    )
