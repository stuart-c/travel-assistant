"""Waypoint compilation, coordinate resolution, and upcoming itinerary caching."""

import datetime
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from app.datasources.homeassistant import HomeAssistantClient
from app.models.journey import Journey
from app.services.dispatcher.evaluator import is_journey_active_for_datetime
from app.services.dispatcher.tracker.models import (
    ActiveJourney,
    ItineraryLeg,
)
from app.utils.geo import resolve_endpoint_coordinates
from app.utils.transit_time import get_day_code, parse_time_to_minutes

logger = logging.getLogger(__name__)

_UPCOMING_ITINERARY_CACHE: Dict[int, Tuple[float, Any]] = {}
_TRACKING_CACHE_TTL_SECONDS = 300.0  # 5 minutes


def clear_tracking_cache() -> None:
    """Flush in-memory planned itinerary cache for live tracking."""
    _UPCOMING_ITINERARY_CACHE.clear()


def _resolve_target_journey_id(
    journey_id: Optional[int],
    journeys_list: List[Dict[str, Any]],
    current_active_journeys: Dict[int, ActiveJourney],
    all_journeys: List[Journey],
    current_dt: datetime.datetime,
) -> Optional[int]:
    """Determine the most relevant journey ID to display."""
    if journey_id is not None and any(j["id"] == journey_id for j in journeys_list):
        return journey_id
    if current_active_journeys:
        return next(iter(current_active_journeys.keys()))
    if journeys_list:
        for j in all_journeys:
            is_active_window, _ = is_journey_active_for_datetime(j, current_dt)
            if is_active_window:
                return j.id

        current_minutes = current_dt.hour * 60 + current_dt.minute
        closest_j_id = None
        min_diff = float("inf")
        for j in all_journeys:
            t_settings = j.get_time_settings()
            for ts in t_settings:
                st = (
                    ts.get("start_time")
                    if isinstance(ts, dict)
                    else getattr(ts, "start_time", None)
                )
                sm = parse_time_to_minutes(st) if st else None
                if sm is not None:
                    diff = (sm - current_minutes) % 1440
                    if diff < min_diff:
                        min_diff = diff
                        closest_j_id = j.id
        return closest_j_id if closest_j_id is not None else journeys_list[0]["id"]
    return None


def _resolve_person_location(
    ha_client: Optional[HomeAssistantClient],
) -> Tuple[Optional[float], Optional[float], str]:
    """Retrieve Stuart's current coordinates and state from Home Assistant."""
    client = ha_client or HomeAssistantClient.from_settings()
    person_state: Optional[Dict[str, Any]] = None
    if client and client.token:
        try:
            person_state = client.get_entity_state("person.stuart")
        except Exception as exc:
            logger.debug("Could not query Home Assistant for person.stuart: %s", exc)

    person_lat: Optional[float] = None
    person_lon: Optional[float] = None
    person_status_str = "unknown"
    if person_state and isinstance(person_state, dict):
        person_status_str = str(person_state.get("state", "unknown"))
        attrs = person_state.get("attributes", {}) or {}
        raw_lat = attrs.get("latitude")
        raw_lon = attrs.get("longitude")
        if raw_lat is not None and raw_lon is not None:
            try:
                person_lat = float(raw_lat)
                person_lon = float(raw_lon)
            except (ValueError, TypeError):
                pass
    return person_lat, person_lon, person_status_str


def _plan_upcoming_itinerary_cached(
    target_id: int,
    j_obj: Journey,
    current_dt: datetime.datetime,
) -> Optional[Any]:
    """Plan upcoming itinerary with caching to avoid repeated RAPTOR runs."""
    time_str = current_dt.strftime("%H:%M")
    now_ts = time.time()
    cached_entry = _UPCOMING_ITINERARY_CACHE.get(target_id)
    if (
        cached_entry is not None
        and (now_ts - cached_entry[0]) < _TRACKING_CACHE_TTL_SECONDS
    ):
        return cached_entry[1]

    time_settings = j_obj.get_time_settings()
    should_plan = False
    if not time_settings:
        should_plan = True
    else:
        is_active_window, _ = is_journey_active_for_datetime(j_obj, current_dt)
        if is_active_window:
            should_plan = True

    upcoming_itinerary = None
    if should_plan:
        day_code = get_day_code(current_dt)
        try:
            from app.services.planner.raptor import plan_journey

            plans = plan_journey(
                from_type=j_obj.from_type,
                from_id=j_obj.from_id,
                to_type=j_obj.to_type,
                to_id=j_obj.to_id,
                timing_mode="depart",
                time_str=time_str,
                days_of_week=[day_code],
                target_date=current_dt.date(),
                max_itineraries=1,
            )
            if plans:
                upcoming_itinerary = plans[0]
        except Exception as exc:
            logger.debug(
                "Could not plan upcoming itinerary for journey %d: %s",
                target_id,
                exc,
            )

    _UPCOMING_ITINERARY_CACHE[target_id] = (now_ts, upcoming_itinerary)
    return upcoming_itinerary


def _build_waypoints_and_legs(
    legs: List[ItineraryLeg],
    current_leg_index: int,
    platform: Optional[str],
    is_active: bool,
    from_name: str,
    from_type: str,
    from_id: str,
    to_name: str,
    to_type: str,
    to_id: str,
) -> Tuple[
    Optional[float],
    Optional[float],
    Optional[float],
    Optional[float],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
]:
    """Compile serialized leg payloads and geographic waypoints."""
    origin_lat, origin_lon, _ = resolve_endpoint_coordinates(from_type, from_id)
    dest_lat, dest_lon, _ = resolve_endpoint_coordinates(to_type, to_id)

    serialized_legs: List[Dict[str, Any]] = []
    waypoints: List[Dict[str, Any]] = []

    if origin_lat is not None and origin_lon is not None:
        waypoints.append(
            {
                "lat": origin_lat,
                "lon": origin_lon,
                "name": from_name,
                "type": "origin",
                "description": f"Origin: {from_name}",
            }
        )

    for idx, leg in enumerate(legs):
        o_lat, o_lon, _ = resolve_endpoint_coordinates(leg.mode, leg.origin.id)
        d_lat, d_lon, _ = resolve_endpoint_coordinates(leg.mode, leg.destination.id)

        leg_plat = getattr(leg.origin, "platform", None)
        if idx == current_leg_index and platform:
            leg_plat = platform

        is_completed = (idx < current_leg_index) if is_active else False
        is_current = (idx == current_leg_index) if is_active else (idx == 0)
        is_upcoming = (idx > current_leg_index) if is_active else (idx > 0)

        leg_dict = {
            "leg_index": idx,
            "mode": leg.mode,
            "line": leg.line,
            "operator": leg.operator,
            "headsign": getattr(leg, "headsign", None),
            "dep_time": leg.dep_time,
            "arr_time": leg.arr_time,
            "duration_minutes": leg.duration_minutes,
            "origin": {
                "id": leg.origin.id,
                "name": leg.origin.name,
                "platform": leg_plat,
                "latitude": o_lat,
                "longitude": o_lon,
            },
            "destination": {
                "id": leg.destination.id,
                "name": leg.destination.name,
                "latitude": d_lat,
                "longitude": d_lon,
            },
            "status": (
                "completed"
                if is_completed
                else ("current" if is_current else "upcoming")
            ),
            "is_completed": is_completed,
            "is_current": is_current,
            "is_upcoming": is_upcoming,
        }
        serialized_legs.append(leg_dict)

        if o_lat is not None and o_lon is not None:
            if not waypoints or (
                abs(waypoints[-1]["lat"] - o_lat) > 1e-5
                or abs(waypoints[-1]["lon"] - o_lon) > 1e-5
            ):
                waypoints.append(
                    {
                        "lat": o_lat,
                        "lon": o_lon,
                        "name": leg.origin.name,
                        "type": ("origin" if idx == 0 and not waypoints else "stop"),
                        "description": f"{leg.origin.name} ({leg.mode.title()})",
                    }
                )

        if d_lat is not None and d_lon is not None:
            is_final = idx == len(legs) - 1
            waypoints.append(
                {
                    "lat": d_lat,
                    "lon": d_lon,
                    "name": leg.destination.name,
                    "type": "destination" if is_final else "interchange",
                    "description": (
                        f"Destination: {leg.destination.name}"
                        if is_final
                        else f"Interchange: {leg.destination.name}"
                    ),
                }
            )

    if dest_lat is not None and dest_lon is not None:
        if not waypoints or (
            abs(waypoints[-1]["lat"] - dest_lat) > 1e-5
            or abs(waypoints[-1]["lon"] - dest_lon) > 1e-5
        ):
            waypoints.append(
                {
                    "lat": dest_lat,
                    "lon": dest_lon,
                    "name": to_name,
                    "type": "destination",
                    "description": f"Destination: {to_name}",
                }
            )

    return (
        origin_lat,
        origin_lon,
        dest_lat,
        dest_lon,
        serialized_legs,
        waypoints,
    )


__all__ = [
    "_TRACKING_CACHE_TTL_SECONDS",
    "_UPCOMING_ITINERARY_CACHE",
    "_build_waypoints_and_legs",
    "_plan_upcoming_itinerary_cached",
    "_resolve_person_location",
    "_resolve_target_journey_id",
    "clear_tracking_cache",
]
