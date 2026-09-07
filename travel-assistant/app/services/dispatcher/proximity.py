"""Proximity and geofencing evaluation for journey departure monitoring."""

import math
from typing import Any, Dict, Optional, Tuple

from app.models.location import Location
from app.models.transit import Stop


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two GPS coordinates in metres."""
    radius_earth_metres = 6371000.0

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

    return radius_earth_metres * c


def resolve_endpoint_coordinates(
    endpoint_type: str, endpoint_id: str
) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """Resolve latitude, longitude, and display name for any journey origin endpoint."""
    e_type = (endpoint_type or "").strip().lower()
    raw_id = (endpoint_id or "").strip()

    if not raw_id:
        return None, None, None

    # Strip prefixes if present for database queries
    clean_id = raw_id
    for prefix in ("ha:", "custom:", "naptan:", "atco:"):
        if clean_id.startswith(prefix):
            clean_id = clean_id[len(prefix) :]
            break

    # 1. Location table lookups (HA zones and custom locations)
    if (
        e_type in ("ha", "custom")
        or raw_id.startswith("ha:")
        or raw_id.startswith("custom:")
    ):
        loc = (
            Location.select()
            .where(
                (Location.id == raw_id)
                | (Location.id == f"ha:{clean_id}")
                | (Location.id == f"custom:{clean_id}")
                | (Location.id == clean_id)
                | (Location.name == raw_id)
                | (Location.name == clean_id)
            )
            .first()
        )
        if loc and loc.latitude is not None and loc.longitude is not None:
            return float(loc.latitude), float(loc.longitude), loc.name

    # 2. Stop table lookups (transit stops, rail stations, bus stands)
    stop = (
        Stop.select()
        .where(
            (Stop.atco_code == raw_id)
            | (Stop.atco_code == clean_id)
            | (Stop.naptan_code == raw_id)
            | (Stop.naptan_code == clean_id)
            | (Stop.name == raw_id)
            | (Stop.name == clean_id)
        )
        .first()
    )
    if stop and stop.latitude is not None and stop.longitude is not None:
        return float(stop.latitude), float(stop.longitude), stop.name

    # 3. General Location fallback by name
    fallback_loc = (
        Location.select()
        .where(
            (Location.id == raw_id)
            | (Location.id == clean_id)
            | (Location.name == raw_id)
            | (Location.name == clean_id)
        )
        .first()
    )
    if (
        fallback_loc
        and fallback_loc.latitude is not None
        and fallback_loc.longitude is not None
    ):
        return (
            float(fallback_loc.latitude),
            float(fallback_loc.longitude),
            fallback_loc.name,
        )

    return None, None, None


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

    dist = haversine_distance(person_lat, person_lon, origin_lat, origin_lon)
    return dist <= max_distance_metres
