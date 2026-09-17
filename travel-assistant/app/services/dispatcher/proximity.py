"""Proximity and geofencing evaluation for journey departure monitoring."""

from typing import Any, Dict, Optional

from app.utils.geo import haversine_distance_m, resolve_endpoint_coordinates


def is_person_near_origin(
    person_state: Optional[Dict[str, Any]],
    from_type: str,
    from_id: str,
    max_distance_metres: float = 200.0,
) -> bool:
    """Evaluate whether a person is detected near the start of a journey.

    Checks if the person is either inside the origin Home Assistant zone
    or within the specified distance radius in metres of the origin coordinates.
    """
    if not person_state or not isinstance(person_state, dict):
        return False

    f_type = (from_type or "").strip().lower()
    f_id = (from_id or "").strip()

    clean_id = f_id
    for prefix in ("ha:", "custom:", "naptan:", "atco:"):
        if clean_id.startswith(prefix):
            clean_id = clean_id[len(prefix) :]
            break

    # Check Home Assistant zone status if origin is a zone
    if f_type == "ha" or f_id.startswith("ha:"):
        zone_id = clean_id.lower()
        person_ha_state = str(person_state.get("state", "")).strip().lower()
        attributes = person_state.get("attributes", {}) or {}

        # Direct zone state match (e.g. state == "home" or state == "work")
        if person_ha_state == zone_id or person_ha_state == zone_id.replace("_", " "):
            return True

        # In-zones attribute array check (e.g. in_zones: ["zone.home", ...])
        in_zones = attributes.get("in_zones")
        if isinstance(in_zones, (list, set, tuple)):
            for z in in_zones:
                z_norm = str(z).lower().replace("zone.", "").strip()
                if z_norm == zone_id:
                    return True

    # Check GPS distance to origin coordinates
    attributes = person_state.get("attributes", {}) or {}
    raw_lat = attributes.get("latitude")
    raw_lon = attributes.get("longitude")

    if raw_lat is None or raw_lon is None:
        return False

    try:
        person_lat = float(raw_lat)
        person_lon = float(raw_lon)
    except (ValueError, TypeError):
        return False

    origin_lat, origin_lon, _ = resolve_endpoint_coordinates(from_type, from_id)
    if origin_lat is None or origin_lon is None:
        return False

    dist = haversine_distance_m(person_lat, person_lon, origin_lat, origin_lon)
    return dist <= max_distance_metres
