"""Locations configuration and Home Assistant synchronisation endpoints."""

import json
from typing import Any, Dict, List
from flask import (
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from app.models import Location
from app.views.config import config_bp


@config_bp.route("/locations", methods=["GET", "POST"])
def locations() -> Any:
    """Manage configured geographic locations."""
    if request.method == "POST":
        locations_raw = request.form.get("locations_json", "[]").strip()
        try:
            items = json.loads(locations_raw)
            if not isinstance(items, list):
                raise ValueError("Payload must be a list of location objects.")

            cleaned_items: List[Dict[str, Any]] = []
            for entry in items:
                if not isinstance(entry, dict):
                    continue
                name = str(entry.get("name", "")).strip()
                if not name:
                    continue

                try:
                    lat_val = entry.get("latitude")
                    lon_val = entry.get("longitude")
                    if lat_val is None or lon_val is None:
                        continue
                    lat = float(lat_val)
                    lon = float(lon_val)
                except (ValueError, TypeError):
                    continue

                if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                    continue

                item_id = str(entry.get("id") or "").strip()
                is_ha = bool(entry.get("ha", False))
                if not is_ha and (not item_id or not item_id.startswith("custom:")):
                    item_id = Location.generate_custom_id()

                cleaned_items.append(
                    {
                        "id": item_id,
                        "name": name,
                        "latitude": round(lat, 6),
                        "longitude": round(lon, 6),
                        "ha": is_ha,
                    }
                )

            with Location._meta.database.atomic():
                # Preserve all existing Home Assistant synchronised records
                existing_ha_records = [
                    {
                        "id": (
                            loc.id
                            if str(loc.id).startswith("ha:")
                            else f"ha:{loc.name.lower().replace(' ', '_')}"
                        ),
                        "name": loc.name,
                        "latitude": loc.latitude,
                        "longitude": loc.longitude,
                        "ha": True,
                    }
                    for loc in Location.select().where(
                        Location.ha == True  # noqa: E712
                    )
                ]

                # Extract only manual (ha=False) entries from submitted items
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

            flash("Locations saved successfully.", "success")
        except Exception as e:
            flash(f"Failed to save locations: {str(e)}", "error")

        return redirect(url_for("config.locations"), code=303)

    current_locations = [loc.to_dict() for loc in Location.select()]
    return render_template(
        "config_locations.html",
        locations=current_locations,
        active_tab="locations",
    )
