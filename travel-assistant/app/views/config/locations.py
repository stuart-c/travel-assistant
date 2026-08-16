"""Locations configuration and Home Assistant synchronisation endpoints."""

from typing import Any, Dict, List, Optional
from flask import render_template, request

from app.models import Location
from app.views.config import config_bp
from app.views.config.common import save_bulk_config


def clean_location_item(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate and sanitize a single location input item."""
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


def save_locations_with_ha_preservation(cleaned_items: List[Dict[str, Any]]) -> None:
    """Atomically save locations while preserving existing Home Assistant synchronised records."""
    with Location._meta.database.atomic():
        existing_ha_records = [
            {
                "id": (
                    str(loc.id)
                    if loc.id
                    else f"ha:{loc.name.lower().replace(' ', '_')}"
                ),
                "name": loc.name,
                "latitude": loc.latitude,
                "longitude": loc.longitude,
                "ha": True,
            }
            for loc in Location.select().where(Location.ha == True)  # noqa: E712
        ]

        used_ids = {r["id"] for r in existing_ha_records}
        manual_items = []
        for item in cleaned_items:
            if item.get("ha", False):
                continue
            m_id = item.get("id")
            if not m_id or m_id in used_ids:
                m_id = Location.generate_custom_id()
            used_ids.add(m_id)
            manual_items.append(
                {
                    "id": m_id,
                    "name": item["name"],
                    "latitude": item["latitude"],
                    "longitude": item["longitude"],
                    "ha": False,
                }
            )

        Location.delete().execute()
        all_records = existing_ha_records + manual_items
        if all_records:
            Location.insert_many(all_records).execute()


@config_bp.route("/locations", methods=["GET", "POST"])
def locations() -> Any:
    """Manage configured geographic locations."""
    if request.method == "POST":
        return save_bulk_config(
            form_key="locations_json",
            model_class=Location,
            clean_item_func=clean_location_item,
            entity_label="Locations",
            redirect_endpoint="config.locations",
            custom_save_fn=save_locations_with_ha_preservation,
        )

    current_locations = [loc.to_dict() for loc in Location.select()]
    return render_template(
        "config_locations.html",
        locations=current_locations,
        active_tab="locations",
    )
