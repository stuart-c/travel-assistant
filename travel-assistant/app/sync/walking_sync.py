"""Walking connections discovery and synchronisation manager.

Identifies public transit stops (NaPTAN stops and custom timetable stops) within
500 metres of custom/HA journey endpoints, calculates walking durations using
the Google Maps Directions API, and reconciles records into the Walking model.
"""

import logging
import math
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from flask import Flask, current_app

from app.datasources import (
    DataSourceAuthError,
    DataSourceConfigError,
    DataSourceConnectionError,
    DataSourceError,
    DataSourceRateLimitError,
    GoogleMapsClient,
)
from app.db import db, init_db
from app.models import (
    Journey,
    Location,
    Stop,
    SyncMetadata,
    Timetable,
    Walking,
)

logger = logging.getLogger(__name__)

DEFAULT_WALK_RADIUS_METRES = 500.0
_walking_sync_lock = threading.Lock()


def _ensure_db_initialized(app: Optional[Flask] = None) -> None:
    """Ensure Peewee DatabaseProxy has been initialised."""
    if db.obj is None:
        init_db(app)


def calculate_haversine_distance_m(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Calculate the great-circle distance between two points in metres using Haversine formula."""
    r_earth = 6371000.0  # Earth mean radius in metres
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r_earth * c


def resolve_location_coords(
    loc_type: str, loc_id: str, loc_name: str
) -> Optional[Tuple[float, float]]:
    """Resolve geographic coordinates (latitude, longitude) for a custom or HA place."""
    if loc_type not in ("ha", "custom"):
        return None

    # Try direct ID lookup
    loc = Location.get_or_none(Location.id == loc_id)
    if loc and loc.latitude is not None and loc.longitude is not None:
        return (float(loc.latitude), float(loc.longitude))

    # Try stripped or prefixed ID variations
    if ":" in loc_id:
        raw_id = loc_id.split(":", 1)[1]
        loc = Location.get_or_none(Location.id == raw_id)
        if loc and loc.latitude is not None and loc.longitude is not None:
            return (float(loc.latitude), float(loc.longitude))
    else:
        for prefix in ("ha:", "custom:"):
            loc = Location.get_or_none(Location.id == f"{prefix}{loc_id}")
            if loc and loc.latitude is not None and loc.longitude is not None:
                return (float(loc.latitude), float(loc.longitude))

    # Fallback to name match
    if loc_name:
        loc = Location.get_or_none(Location.name == loc_name)
        if loc and loc.latitude is not None and loc.longitude is not None:
            return (float(loc.latitude), float(loc.longitude))

    return None


def find_candidate_stops_for_location(
    loc_lat: float,
    loc_lon: float,
    max_distance_m: float = DEFAULT_WALK_RADIUS_METRES,
) -> List[Dict[str, Any]]:
    """Discover all transit stops (NaPTAN + custom timetable stops) within radius metres."""
    candidates: List[Dict[str, Any]] = []
    seen_stop_keys: Set[Tuple[str, str]] = set()

    # 1. Query NaPTAN stops within bounding box pre-filter for performance
    lat_delta = (max_distance_m + 50.0) / 111320.0
    lon_delta = (max_distance_m + 50.0) / (
        111320.0 * max(0.01, math.cos(math.radians(loc_lat)))
    )

    naptan_stops = Stop.select().where(
        (Stop.latitude >= loc_lat - lat_delta)
        & (Stop.latitude <= loc_lat + lat_delta)
        & (Stop.longitude >= loc_lon - lon_delta)
        & (Stop.longitude <= loc_lon + lon_delta)
    )

    for st in naptan_stops:
        try:
            dist = calculate_haversine_distance_m(
                loc_lat, loc_lon, float(st.latitude), float(st.longitude)
            )
            if dist <= max_distance_m:
                st_id = (
                    f"naptan:{st.naptan_code}"
                    if st.naptan_code
                    else f"atco:{st.atco_code}"
                )
                stop_key = (st.stop_type, st_id)
                if stop_key not in seen_stop_keys:
                    seen_stop_keys.add(stop_key)
                    candidates.append(
                        {
                            "type": st.stop_type or "bus",
                            "id": st_id,
                            "name": st.name,
                            "latitude": float(st.latitude),
                            "longitude": float(st.longitude),
                            "distance_m": round(dist, 1),
                        }
                    )
        except (ValueError, TypeError):
            continue

    # 2. Query custom / HA stops used in any Timetable
    timetables = Timetable.select()
    for tt in timetables:
        content = tt.get_content()
        stops = content.get("stops", [])
        for st_entry in stops:
            if not isinstance(st_entry, dict):
                continue

            raw_id = str(st_entry.get("id", "")).strip()
            raw_name = str(st_entry.get("name", "")).strip()
            raw_type = (
                str(st_entry.get("type", tt.transport_type or "bus")).strip().lower()
            )

            if not raw_id:
                continue

            lat = st_entry.get("latitude")
            lon = st_entry.get("longitude")

            # Resolve coordinates if not directly in stop entry
            if lat is None or lon is None:
                if raw_type in ("ha", "custom") or raw_id.startswith(
                    ("ha:", "custom:")
                ):
                    coords = resolve_location_coords(raw_type, raw_id, raw_name)
                    if coords:
                        lat, lon = coords
                else:
                    st_obj = Stop.get_by_code(raw_id)
                    if (
                        st_obj
                        and st_obj.latitude is not None
                        and st_obj.longitude is not None
                    ):
                        lat, lon = float(st_obj.latitude), float(st_obj.longitude)
                        raw_name = raw_name or st_obj.name
                        raw_type = st_obj.stop_type or raw_type

            if lat is None or lon is None:
                continue

            try:
                dist = calculate_haversine_distance_m(
                    loc_lat, loc_lon, float(lat), float(lon)
                )
                if dist <= max_distance_m:
                    stop_key = (raw_type, raw_id)
                    if stop_key not in seen_stop_keys:
                        seen_stop_keys.add(stop_key)
                        candidates.append(
                            {
                                "type": raw_type,
                                "id": raw_id,
                                "name": raw_name or raw_id,
                                "latitude": float(lat),
                                "longitude": float(lon),
                                "distance_m": round(dist, 1),
                            }
                        )
            except (ValueError, TypeError):
                continue

    return candidates


def walking_route_exists(
    loc_type: str, loc_id: str, stop_type: str, stop_id: str
) -> bool:
    """Check whether a walking route already exists between place and stop in either direction."""
    s_type, s_id = loc_type.strip(), loc_id.strip()
    f_type, f_id = stop_type.strip(), stop_id.strip()

    # Check forward match
    forward = (
        Walking.select()
        .where(
            (Walking.start_type == s_type)
            & (Walking.start_id == s_id)
            & (Walking.finish_type == f_type)
            & (Walking.finish_id == f_id)
        )
        .first()
    )
    if forward:
        return True

    # Check reverse match (respecting bidirectional or reverse connection)
    reverse = (
        Walking.select()
        .where(
            (Walking.start_type == f_type)
            & (Walking.start_id == f_id)
            & (Walking.finish_type == s_type)
            & (Walking.finish_id == s_id)
        )
        .first()
    )
    return reverse is not None


def extract_walking_minutes(
    directions_response: List[Dict[str, Any]],
) -> Optional[int]:
    """Extract walking duration in minutes from Google Directions API response.

    Durations returned in seconds are rounded up to the nearest whole minute.
    """
    if not directions_response or not isinstance(directions_response, list):
        return None
    try:
        first_route = directions_response[0]
        legs = first_route.get("legs", [])
        if not legs or not isinstance(legs, list):
            return None
        duration_dict = legs[0].get("duration", {})
        seconds = duration_dict.get("value")
        if seconds is None:
            return None
        return max(1, math.ceil(float(seconds) / 60.0))
    except (IndexError, KeyError, ValueError, TypeError):
        return None


def sync_walking_routes(
    app: Optional[Flask] = None, force: bool = False
) -> Dict[str, Any]:
    """Discover nearby transit stops for journeys and synchronise walking duration records."""
    _ensure_db_initialized(app)
    start_time = time.time()

    with _walking_sync_lock:
        with db.connection_context():
            # Check Google Maps credentials
            client = GoogleMapsClient.from_settings()
            if not client.api_key:
                msg = "Google Maps API Key not configured in Settings > API Credentials"
                SyncMetadata.record_skipped("walking", msg)
                return {
                    "table": "walking",
                    "status": "skipped_no_credentials",
                    "records": 0,
                    "message": msg,
                    "duration_seconds": 0.0,
                }

            SyncMetadata.record_start("walking")

            try:
                # 1. Collect all custom/HA endpoints from configured journeys
                journeys = Journey.select()
                target_places: Dict[Tuple[str, str], Dict[str, Any]] = {}

                for j in journeys:
                    if j.from_type in ("ha", "custom") and j.from_id:
                        place_key = (j.from_type, j.from_id)
                        if place_key not in target_places:
                            coords = resolve_location_coords(
                                j.from_type, j.from_id, j.from_name
                            )
                            if coords:
                                target_places[place_key] = {
                                    "type": j.from_type,
                                    "id": j.from_id,
                                    "name": j.from_name,
                                    "latitude": coords[0],
                                    "longitude": coords[1],
                                }

                    if j.to_type in ("ha", "custom") and j.to_id:
                        place_key = (j.to_type, j.to_id)
                        if place_key not in target_places:
                            coords = resolve_location_coords(
                                j.to_type, j.to_id, j.to_name
                            )
                            if coords:
                                target_places[place_key] = {
                                    "type": j.to_type,
                                    "id": j.to_id,
                                    "name": j.to_name,
                                    "latitude": coords[0],
                                    "longitude": coords[1],
                                }

                if not target_places:
                    duration = round(time.time() - start_time, 2)
                    msg = (
                        "No custom or Home Assistant journey places found for "
                        "walking stop discovery."
                    )
                    SyncMetadata.record_success("walking", 0, duration)
                    return {
                        "table": "walking",
                        "status": "success",
                        "records": 0,
                        "message": msg,
                        "duration_seconds": duration,
                    }

                # 2. For each target place, find candidate stops within 500m
                added_records = 0
                for place_info in target_places.values():
                    loc_type = place_info["type"]
                    loc_id = place_info["id"]
                    loc_name = place_info["name"]
                    loc_lat = place_info["latitude"]
                    loc_lon = place_info["longitude"]

                    candidate_stops = find_candidate_stops_for_location(
                        loc_lat, loc_lon, max_distance_m=DEFAULT_WALK_RADIUS_METRES
                    )

                    for stop in candidate_stops:
                        st_type = stop["type"]
                        st_id = stop["id"]
                        st_name = stop["name"]
                        st_lat = stop["latitude"]
                        st_lon = stop["longitude"]

                        # Do not connect a location to itself
                        if loc_type == st_type and loc_id == st_id:
                            continue

                        # Skip if a walking route already exists (never overwrite)
                        if walking_route_exists(loc_type, loc_id, st_type, st_id):
                            continue

                        # Query Google Directions API in both directions
                        fwd_resp = client.directions(
                            origin=(loc_lat, loc_lon),
                            destination=(st_lat, st_lon),
                            mode="walking",
                        )
                        rev_resp = client.directions(
                            origin=(st_lat, st_lon),
                            destination=(loc_lat, loc_lon),
                            mode="walking",
                        )

                        fwd_min = extract_walking_minutes(fwd_resp)
                        rev_min = extract_walking_minutes(rev_resp)

                        if fwd_min is None and rev_min is not None:
                            fwd_min = rev_min
                        elif rev_min is None and fwd_min is not None:
                            rev_min = fwd_min
                        elif fwd_min is None and rev_min is None:
                            logger.warning(
                                "Could not compute walking duration between %s and %s "
                                "via Google Maps",
                                loc_name,
                                st_name,
                            )
                            continue

                        # Insert records: single bidirectional if equal, otherwise 2 directional
                        if fwd_min == rev_min:
                            Walking.create(
                                start_type=loc_type,
                                start_id=loc_id,
                                start_name=loc_name,
                                finish_type=st_type,
                                finish_id=st_id,
                                finish_name=st_name,
                                time_needed_minutes=fwd_min,
                                bidirectional=True,
                                auto_generated=True,
                            )
                            added_records += 1
                        else:
                            Walking.create(
                                start_type=loc_type,
                                start_id=loc_id,
                                start_name=loc_name,
                                finish_type=st_type,
                                finish_id=st_id,
                                finish_name=st_name,
                                time_needed_minutes=fwd_min,
                                bidirectional=False,
                                auto_generated=True,
                            )
                            Walking.create(
                                start_type=st_type,
                                start_id=st_id,
                                start_name=st_name,
                                finish_type=loc_type,
                                finish_id=loc_id,
                                finish_name=loc_name,
                                time_needed_minutes=rev_min,
                                bidirectional=False,
                                auto_generated=True,
                            )
                            added_records += 2

                duration = round(time.time() - start_time, 2)
                SyncMetadata.record_success("walking", added_records, duration)
                return {
                    "table": "walking",
                    "status": "success",
                    "records": added_records,
                    "message": f"Successfully synchronised {added_records} walking route(s).",
                    "duration_seconds": duration,
                }

            except (DataSourceAuthError, DataSourceConfigError) as exc:
                duration = round(time.time() - start_time, 2)
                err_msg = str(exc)
                SyncMetadata.record_error("walking", err_msg, duration)
                return {
                    "table": "walking",
                    "status": "error",
                    "records": 0,
                    "message": err_msg,
                    "duration_seconds": duration,
                }
            except (
                DataSourceConnectionError,
                DataSourceRateLimitError,
                DataSourceError,
            ) as exc:
                duration = round(time.time() - start_time, 2)
                err_msg = f"Google Maps API error during walking sync: {str(exc)}"
                SyncMetadata.record_error("walking", err_msg, duration)
                return {
                    "table": "walking",
                    "status": "error",
                    "records": 0,
                    "message": err_msg,
                    "duration_seconds": duration,
                }
            except Exception as exc:
                duration = round(time.time() - start_time, 2)
                err_msg = f"Unexpected error during walking synchronisation: {str(exc)}"
                SyncMetadata.record_error("walking", err_msg, duration)
                return {
                    "table": "walking",
                    "status": "error",
                    "records": 0,
                    "message": err_msg,
                    "duration_seconds": duration,
                }


def trigger_journey_walking_sync_async(
    app: Optional[Flask] = None,
) -> threading.Thread:
    """Trigger walking route discovery asynchronously in a background thread."""
    flask_app = app or (current_app._get_current_object() if current_app else None)

    def _worker() -> None:
        if flask_app:
            with flask_app.app_context():
                try:
                    sync_walking_routes(app=flask_app)
                except Exception as exc:
                    logger.error(
                        "Error in background walking route synchronisation: %s", exc
                    )
        else:
            try:
                sync_walking_routes()
            except Exception as exc:
                logger.error(
                    "Error in background walking route synchronisation: %s", exc
                )

    thread = threading.Thread(
        target=_worker, name="JourneyWalkingSyncWorker", daemon=True
    )
    thread.start()
    return thread
