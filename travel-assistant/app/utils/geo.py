"""Geospatial utilities and coordinate resolution for Travel Assistant."""

from typing import Optional, Tuple
from geopy.distance import great_circle

from app.models.location import Location
from app.models.transit import Stop


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two GPS coordinates in metres using geopy."""
    if lat1 == lat2 and lon1 == lon2:
        return 0.0
    return float(great_circle((lat1, lon1), (lat2, lon2)).meters)


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
