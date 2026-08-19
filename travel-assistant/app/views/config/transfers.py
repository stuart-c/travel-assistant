"""Transfers configuration endpoints."""

from typing import Any, Dict, Optional
from flask import jsonify

from app.models import PlatformTransfer
from app.models.base import LOCATION_TYPES
from app.views.config import config_bp
from app.views.config.common import PageConfig, register_html_page


def clean_platform_transfer_item(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate and sanitise a single platform/stand transfer item."""
    if not isinstance(entry, dict):
        return None

    loc_type = str(entry.get("location_type", "rail")).lower().strip()
    if loc_type not in LOCATION_TYPES:
        loc_type = "rail"

    location_id = str(entry.get("location_id", "")).strip()
    location_name = str(entry.get("location_name", "")).strip()
    from_platform = str(entry.get("from_platform", "")).strip()
    to_platform = str(entry.get("to_platform", "")).strip()

    try:
        transfer_time = max(1, int(entry.get("transfer_time_minutes", 2)))
    except (ValueError, TypeError):
        transfer_time = 2

    if not (location_id and location_name and from_platform and to_platform):
        return None

    item_id: Optional[int] = None
    if entry.get("id") is not None and str(entry.get("id")).strip():
        try:
            item_id = int(entry.get("id"))
        except (ValueError, TypeError):
            item_id = None

    result: Dict[str, Any] = {
        "location_type": loc_type,
        "location_id": location_id,
        "location_name": location_name,
        "from_platform": from_platform,
        "to_platform": to_platform,
        "transfer_time_minutes": transfer_time,
        "bidirectional": bool(entry.get("bidirectional", True)),
        "step_free": bool(entry.get("step_free", False)),
        "notes": str(entry.get("notes", "")).strip(),
    }
    if item_id is not None:
        result["id"] = item_id

    return result


@config_bp.route("/transfers/data", methods=["GET"])
def transfers_data() -> Any:
    """Return all platform transfers as JSON for Grid.js remote data loading."""
    items = [t.to_dict() for t in PlatformTransfer.select()]
    return jsonify({"data": items, "total": len(items)})


register_html_page(
    config_bp,
    PageConfig(
        route="/transfers",
        endpoint="transfers",
        template="config_transfers.html",
        form_key="platform_transfers_json",
        model_class=PlatformTransfer,
        clean_item_func=clean_platform_transfer_item,
        entity_label="Transfers",
        get_template_context=lambda: {},
    ),
)
