"""Locations configuration and Home Assistant synchronisation endpoints."""

from typing import Any, Dict, Optional
from flask import jsonify, render_template, request

from app.models import Location
from app.views.config import config_bp
from app.views.config.common import save_changeset_config


def clean_location_item(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate and sanitise a single location input item."""
    if not isinstance(entry, dict):
        return None

    name = str(entry.get("name", "")).strip()
    if not name:
        return None

    try:
        lat_val = entry.get("latitude")
        lon_val = entry.get("longitude")
        if lat_val is None or lon_val is None:
            return None
        lat = float(lat_val)
        lon = float(lon_val)
    except (ValueError, TypeError):
        return None

    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None

    item_id = str(entry.get("id") or "").strip()
    is_ha = bool(entry.get("ha", False))
    if not is_ha and (not item_id or not item_id.startswith("custom:")):
        item_id = Location.generate_custom_id()

    return {
        "id": item_id,
        "name": name,
        "latitude": round(lat, 6),
        "longitude": round(lon, 6),
        "ha": is_ha,
    }


@config_bp.route("/locations/data", methods=["GET"])
def locations_data() -> Any:
    """Return all configured locations as JSON for Grid.js remote data loading."""
    items = [loc.to_dict() for loc in Location.select()]
    return jsonify({"data": items, "total": len(items)})


@config_bp.route("/locations", methods=["GET", "POST"])
def locations() -> Any:
    """Manage configured geographic locations."""
    if request.method == "POST":
        return save_changeset_config(
            form_key="locations_json",
            model_class=Location,
            clean_item_func=clean_location_item,
            entity_label="Locations",
            redirect_endpoint="config.locations",
            scope_filter=(Location.ha == False),  # noqa: E712
        )

    return render_template(
        "config_locations.html",
        active_tab="locations",
    )
