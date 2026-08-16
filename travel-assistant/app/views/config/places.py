"""Consolidated places and transit lookup search endpoint."""

from typing import Any, Dict, List
from flask import jsonify, request

from app.models import Location, Stop
from app.views.config import config_bp


@config_bp.route("/search/places", methods=["GET"])
def search_places() -> Any:
    """Search public transit stops, Home Assistant zones, and custom locations."""
    target_type = request.args.get("type", "").lower().strip()
    query = request.args.get("q", "").strip()
    limit_raw = request.args.get("limit", "15").strip()
    try:
        limit = max(1, min(int(limit_raw), 50))
    except ValueError:
        limit = 15

    results: List[Dict[str, Any]] = []
    seen_ids = set()

    # Query Rail Stations
    if not target_type or target_type in (
        "station",
        "train",
        "rail",
        "stop",
        "all",
    ):
        try:
            st_list = (
                Stop.search(query, stop_type="rail", limit=limit)
                if query
                else list(Stop.select().where(Stop.stop_type == "rail").limit(limit))
            )
            for st in st_list:
                item_id = (
                    f"naptan:{st.naptan_code}"
                    if st.naptan_code
                    else f"atco:{st.atco_code}"
                )
                if item_id not in seen_ids:
                    seen_ids.add(item_id)
                    results.append(
                        {
                            "id": item_id,
                            "name": st.name,
                            "type": "station",
                            "description": (
                                f"National Rail Station - "
                                f"{st.naptan_code or st.atco_code}"
                            ),
                            "indicator": "Rail",
                            "icon": "train",
                            "latitude": st.latitude,
                            "longitude": st.longitude,
                        }
                    )
        except Exception:
            pass

    # Query Bus Stops
    if not target_type or target_type in ("bus_stop", "bus", "stop", "all"):
        try:
            stop_list = (
                Stop.search(query, stop_type="bus", limit=limit)
                if query
                else list(Stop.select().where(Stop.stop_type == "bus").limit(limit))
            )
            for sp in stop_list:
                item_id = (
                    f"naptan:{sp.naptan_code}"
                    if sp.naptan_code
                    else f"atco:{sp.atco_code}"
                )
                if item_id not in seen_ids:
                    seen_ids.add(item_id)
                    loc_suffix = f", {sp.locality}" if sp.locality else ""
                    ind_text = f" ({sp.indicator})" if sp.indicator else ""
                    results.append(
                        {
                            "id": item_id,
                            "name": f"{sp.name}{ind_text}",
                            "type": "bus_stop",
                            "description": (f"Bus Stop{loc_suffix} - {sp.atco_code}"),
                            "indicator": sp.indicator or "Bus Stop",
                            "icon": "directions_bus",
                            "latitude": sp.latitude,
                            "longitude": sp.longitude,
                        }
                    )
        except Exception:
            pass

    # Query Custom & Home Assistant Locations
    if not target_type or target_type in (
        "location",
        "ha_location",
        "custom_location",
        "ha",
        "custom",
        "all",
    ):
        try:
            loc_list = (
                Location.search(query, limit=limit)
                if query
                else list(Location.select().limit(limit))
            )
            for loc in loc_list:
                is_ha = bool(getattr(loc, "ha", False))
                loc_type = "ha_location" if is_ha else "custom_location"
                if target_type and target_type not in (
                    "location",
                    "all",
                    loc_type,
                    "ha" if is_ha else "custom",
                ):
                    continue

                item_id = str(loc.id)
                if item_id not in seen_ids:
                    seen_ids.add(item_id)
                    icon = "home" if is_ha else "pin_drop"
                    indicator = "Home Assistant" if is_ha else "Custom"
                    desc = (
                        f"{indicator} Location - "
                        f"({loc.latitude:.4f}, {loc.longitude:.4f})"
                        if loc.latitude is not None and loc.longitude is not None
                        else f"{indicator} Location"
                    )
                    results.append(
                        {
                            "id": item_id,
                            "name": loc.name,
                            "type": loc_type,
                            "description": desc,
                            "indicator": indicator,
                            "icon": icon,
                            "latitude": loc.latitude,
                            "longitude": loc.longitude,
                        }
                    )
        except Exception:
            pass

    return jsonify({"results": results, "total": len(results)})
