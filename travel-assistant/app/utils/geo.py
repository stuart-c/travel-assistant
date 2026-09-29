"""Geospatial utilities and coordinate resolution for Travel Assistant."""

from typing import Optional, Tuple
from geopy.distance import great_circle
from peewee import fn

from app.models.location import Location
from app.models.transit import Stop


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two GPS coordinates in metres using geopy."""
    if lat1 == lat2 and lon1 == lon2:
        return 0.0
    return float(great_circle((lat1, lon1), (lat2, lon2)).meters)


def distance_to_polyline_m(
    lat: float, lon: float, polyline_str: Optional[str]
) -> Optional[float]:
    """Calculate the minimum distance in metres from a coordinate to an encoded polyline."""
    if not polyline_str:
        return None
    try:
        import polyline

        points = polyline.decode(polyline_str)
        if not points:
            return None
        min_dist = float("inf")
        for p_lat, p_lon in points:
            d = haversine_distance_m(lat, lon, p_lat, p_lon)
            if d < min_dist:
                min_dist = d
        return min_dist if min_dist != float("inf") else None
    except Exception:
        return None


def resolve_endpoint_coordinates(
    endpoint_type: str, endpoint_id: str
) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """Resolve latitude, longitude, and display name for any journey origin or destination endpoint."""
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

    raw_lower = raw_id.lower()
    clean_lower = clean_id.lower()

    # 1. Location table lookups (HA zones and custom locations)
    if (
        e_type in ("ha", "custom")
        or raw_lower.startswith("ha:")
        or raw_lower.startswith("custom:")
    ):
        loc = (
            Location.select()
            .where(
                (fn.LOWER(Location.id) == raw_lower)
                | (fn.LOWER(Location.id) == f"ha:{clean_lower}")
                | (fn.LOWER(Location.id) == f"custom:{clean_lower}")
                | (fn.LOWER(Location.id) == clean_lower)
                | (fn.LOWER(Location.name) == raw_lower)
                | (fn.LOWER(Location.name) == clean_lower)
            )
            .first()
        )
        if loc and loc.latitude is not None and loc.longitude is not None:
            return float(loc.latitude), float(loc.longitude), loc.name

    # 2. Stop table lookups (transit stops, rail stations, bus stands)
    stop = (
        Stop.select()
        .where(
            (fn.LOWER(Stop.atco_code) == raw_lower)
            | (fn.LOWER(Stop.atco_code) == clean_lower)
            | (fn.LOWER(Stop.naptan_code) == raw_lower)
            | (fn.LOWER(Stop.naptan_code) == clean_lower)
            | (fn.LOWER(Stop.name) == raw_lower)
            | (fn.LOWER(Stop.name) == clean_lower)
        )
        .first()
    )
    if stop and stop.latitude is not None and stop.longitude is not None:
        return float(stop.latitude), float(stop.longitude), stop.name

    # 3. General Location fallback by case-insensitive name or ID (even if e_type was walk/bus/etc.)
    fallback_loc = (
        Location.select()
        .where(
            (fn.LOWER(Location.id) == raw_lower)
            | (fn.LOWER(Location.id) == f"ha:{clean_lower}")
            | (fn.LOWER(Location.id) == f"custom:{clean_lower}")
            | (fn.LOWER(Location.id) == clean_lower)
            | (fn.LOWER(Location.name) == raw_lower)
            | (fn.LOWER(Location.name) == clean_lower)
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
