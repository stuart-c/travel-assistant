"""Consolidated places and transit lookup search endpoint."""

from typing import Any, Dict, List
from flask import jsonify, request

from app.models import Location, Stop
from app.views.config import config_bp

STOP_TYPE_CONFIG: Dict[str, Dict[str, str]] = {
    "rail": {
        "type": "rail",
        "icon": "train",
        "indicator": "Rail",
        "label": "National Rail Station",
    },
    "bus": {
        "type": "bus",
        "icon": "directions_bus",
        "indicator": "Bus Stop",
        "label": "Bus Stop",
    },
    "tram": {
        "type": "tram",
        "icon": "tram",
        "indicator": "Tram",
        "label": "Tram Stop",
    },
    "metro": {
        "type": "metro",
        "icon": "subway",
        "indicator": "Metro",
        "label": "Metro Station",
    },
    "ferry": {
        "type": "ferry",
        "icon": "directions_boat",
        "indicator": "Ferry",
        "label": "Ferry Terminal",
    },
    "air": {
        "type": "air",
        "icon": "flight",
        "indicator": "Air",
        "label": "Airport Terminal",
    },
}


@config_bp.route("/search/places", methods=["GET"])
def search_places() -> Any:
    """Search public transit stops, Home Assistant zones, and custom locations."""
    target_type = request.args.get("type", "").lower().strip()
    if target_type == "train":
        target_type = "rail"
    query = request.args.get("q", "").strip()
    limit_raw = request.args.get("limit", "15").strip()
    try:
        limit = max(1, min(int(limit_raw), 50))
    except ValueError:
        limit = 15

    results: List[Dict[str, Any]] = []
    seen_ids = set()

    # Determine which transit stop types to search
    if not target_type or target_type == "all":
        types_to_search = list(STOP_TYPE_CONFIG.keys())
    elif target_type in STOP_TYPE_CONFIG:
        types_to_search = [target_type]
    else:
        types_to_search = []

    for st_type in types_to_search:
        meta = STOP_TYPE_CONFIG[st_type]
        try:
            if query:
                st_list = Stop.search(query, stop_type=st_type, limit=limit)
            else:
                st_list = list(
                    Stop.select().where(Stop.stop_type == st_type).limit(limit)
                )
            for st in st_list:
                item_id = (
                    f"naptan:{st.naptan_code}"
                    if st.naptan_code
                    else f"atco:{st.atco_code}"
                )
                if item_id not in seen_ids:
                    seen_ids.add(item_id)
                    loc_suffix = f", {st.locality}" if st.locality else ""
                    ind_text = (
                        f" ({st.indicator})"
                        if st.indicator and st_type == "bus"
                        else ""
                    )
                    results.append(
                        {
                            "id": item_id,
                            "name": f"{st.name}{ind_text}",
                            "type": meta["type"],
                            "description": (
                                f"{meta['label']}{loc_suffix} - "
                                f"{st.naptan_code or st.atco_code}"
                            ),
                            "indicator": st.indicator or meta["indicator"],
                            "icon": meta["icon"],
                            "latitude": st.latitude,
                            "longitude": st.longitude,
                        }
                    )
        except Exception:
            pass

    # Query Custom & Home Assistant Locations
    # Included by default when searching 'all' or specifically requested
    include_locations = (
        not target_type or target_type == "all" or target_type in ("ha", "custom")
    )

    if include_locations:
        try:
            loc_list = (
                Location.search(query, limit=limit)
                if query
                else list(Location.select().limit(limit))
            )
            for loc in loc_list:
                is_ha = bool(getattr(loc, "ha", False))
                loc_type = "ha" if is_ha else "custom"
                if target_type == "ha" and not is_ha:
                    continue
                if target_type == "custom" and is_ha:
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
