"""Journey planning orchestration and departure sweeps for the RAPTOR engine."""

from __future__ import annotations

import datetime
import time
from typing import List, Optional, Set, Union

from app.models.walking import Walking
from app.services.planner.exceptions import (
    InvalidEndpointError,
    JourneyPlanningError,
    JourneyPlanningErrorCode,
    NoAccessStopsError,
    NoCorridorPathError,
    NoServicesOnDayError,
    NoTripsInWindowError,
)
from app.services.planner.models import (
    ItineraryEndpoint,
    ItineraryLeg,
    ScheduledItinerary,
)
from app.services.planner.raptor.connectivity import (
    _check_corridor_connectivity,
    _load_interchanges_for_stops,
)
from app.services.planner.raptor.engine import _run_raptor_forward
from app.services.planner.raptor.trips import (
    _TRIPS_CACHE,
    _TRIPS_CACHE_TTL_SECONDS,
    _build_stop_to_trips,
    _extract_parsed_trips,
)
from app.services.planner.transfers import (
    format_minutes_to_time,
    get_access_edges,
    get_active_timetables,
    normalise_id,
    parse_time_to_minutes,
    resolve_active_days_and_date,
    resolve_endpoint_name,
)


def plan_journey(
    from_type: str,
    from_id: str,
    to_type: str,
    to_id: str,
    timing_mode: str = "depart",  # "depart", "arrive", or "window"
    time_str: str = "08:00",
    time_window_end: Optional[str] = None,
    days_of_week: Optional[List[str]] = None,
    target_date: Optional[Union[datetime.date, str]] = None,
    min_transfer_minutes: int = 3,
    max_transfers: int = 5,
    max_itineraries: int = 5,
) -> List[ScheduledItinerary]:
    """Calculate concrete scheduled travel itineraries matching time and day constraints.

    Uses an in-memory RAPTOR (Round-Based Public Transit Routing) algorithm to find
    Pareto-optimal scheduled travel plans directly from database timetable trips.

    Args:
        from_type: Origin location type ("ha", "custom", "rail", "bus", etc.).
        from_id: Origin location identifier.
        to_type: Destination location type ("ha", "custom", "rail", "bus", scalp, etc.).
        to_id: Destination location identifier.
        timing_mode: "depart" (leave after time_str), "arrive" (arrive before time_str), or "window".
        time_str: Target time in "HH:MM" format.
        time_window_end: Window end time in "HH:MM" format if timing_mode == "window".
        days_of_week: Optional list of active day codes ("mon".."sun", "bank_holiday").
        target_date: Optional target date object or YYYY-MM-DD string.
        min_transfer_minutes: Minimum interchange buffer duration in minutes (default: 3).
        max_transfers: Maximum number of transit changes allowed (default: 5).
        max_itineraries: Maximum number of ranked plans to return (default: 5).

    Returns:
        List of ranked ScheduledItinerary objects.

    Raises:
        InvalidEndpointError: If endpoints are invalid.
        NoAccessStopsError: If origin or destination has no reachable transit stops.
        NoCorridorPathError: If no transit path connects the endpoints.
        NoTripsInWindowError: If routes exist but no scheduled trips run in the requested window.
    """
    f_type = str(from_type).strip().lower()
    f_id = str(from_id).strip()
    t_type = str(to_type).strip().lower()
    t_id = str(to_id).strip()

    if not f_id or not t_id:
        raise InvalidEndpointError(
            "Both origin and destination identifiers must be provided.",
            {"from_id": f_id, "to_id": t_id},
        )

    if f_type == t_type and normalise_id(f_id) == normalise_id(t_id):
        raise JourneyPlanningError(
            JourneyPlanningErrorCode.SAME_ORIGIN_DESTINATION,
            "Origin and destination endpoints cannot be identical.",
            {"origin": f_id, "destination": t_id},
        )

    t_mode = str(timing_mode).strip().lower()
    if t_mode not in ("depart", "arrive", "window"):
        t_mode = "depart"

    t_start_min = parse_time_to_minutes(time_str)
    if t_start_min is None:
        t_start_min = 8 * 60

    t_end_min = parse_time_to_minutes(time_window_end) if time_window_end else None
    if t_mode == "window" and t_end_min is None:
        t_end_min = t_start_min + 120

    active_days, date_obj = resolve_active_days_and_date(days_of_week, target_date)

    # 1. Filter Active Timetables & Trips (with in-memory caching)
    cache_key = (
        tuple(sorted(active_days)),
        date_obj.isoformat() if date_obj else None,
    )
    now_ts = time.time()
    cached = _TRIPS_CACHE.get(cache_key)
    if cached and (now_ts - cached[0]) < _TRIPS_CACHE_TTL_SECONDS:
        _, trips, timetable_stop_ids = cached
    else:
        active_timetables = get_active_timetables(active_days, date_obj)
        trips, timetable_stop_ids = _extract_parsed_trips(active_timetables)
        _TRIPS_CACHE[cache_key] = (time.time(), trips, timetable_stop_ids)

    # 2. Access & Egress Footpaths
    origin_walks = get_access_edges(f_type, f_id, is_origin=True)
    dest_walks = get_access_edges(t_type, t_id, is_origin=False)

    # Check if origin or destination endpoint is directly served by active timetables
    if normalise_id(f_id) in timetable_stop_ids and not any(
        w[2] == f_type and normalise_id(w[3]) == normalise_id(f_id)
        for w in origin_walks
    ):
        origin_walks.append((f_type, f_id, f_type, f_id, 0, "direct"))
    if normalise_id(t_id) in timetable_stop_ids and not any(
        w[0] == t_type and normalise_id(w[1]) == normalise_id(t_id) for w in dest_walks
    ):
        dest_walks.append((t_type, t_id, t_type, t_id, 0, "direct"))

    direct_walk = Walking.find_walking_route(f_type, f_id, t_type, t_id)
    if not direct_walk:
        direct_walk = Walking.find_walking_route(
            f_type, normalise_id(f_id), t_type, normalise_id(t_id)
        )

    if not origin_walks and not direct_walk:
        raise NoAccessStopsError(
            f"No reachable transit stops found within walking distance of origin '{f_id}'.",
            {"endpoint": f_id, "type": f_type},
        )

    if not dest_walks and not direct_walk:
        raise NoAccessStopsError(
            f"No reachable transit stops found within walking distance of destination '{t_id}'.",
            {"endpoint": t_id, "type": t_type},
        )

    candidate_itineraries: List[ScheduledItinerary] = []
    if direct_walk:
        walk_min = direct_walk.time_needed_minutes
        if t_mode == "arrive":
            dep_min = t_start_min - walk_min
            arr_min = t_start_min
        else:
            dep_min = t_start_min
            arr_min = t_start_min + walk_min

        orig_name = resolve_endpoint_name(f_type, f_id)
        dest_name = resolve_endpoint_name(t_type, t_id)

        candidate_itineraries.append(
            ScheduledItinerary(
                departure_time=format_minutes_to_time(dep_min),
                arrival_time=format_minutes_to_time(arr_min),
                total_duration_minutes=walk_min,
                transfers_count=0,
                robustness_score="Optimal (Direct Walk)",
                legs=[
                    ItineraryLeg(
                        leg_index=1,
                        mode="walk",
                        origin=ItineraryEndpoint(id=f_id, name=orig_name),
                        destination=ItineraryEndpoint(id=t_id, name=dest_name),
                        dep_time=format_minutes_to_time(dep_min),
                        arr_time=format_minutes_to_time(arr_min),
                        duration_minutes=walk_min,
                    )
                ],
            )
        )

    if not trips and not candidate_itineraries:
        raise NoServicesOnDayError(
            f"No transit services operate on the requested day(s) {active_days}.",
            {"days": active_days},
        )

    # 3. Execute RAPTOR for departure sweeps
    eval_departures: List[int] = []
    if t_mode == "depart":
        if max_itineraries > 1:
            eval_departures = list(range(t_start_min, t_start_min + 120, 10))
        else:
            eval_departures = [t_start_min]
    elif t_mode == "window":
        eval_departures = list(range(t_start_min, (t_end_min or t_start_min) + 1, 10))
    elif t_mode == "arrive":
        earliest_dep = max(0, t_start_min - 240)
        eval_departures = list(range(earliest_dep, t_start_min, 10))

    # Precompute stop-to-trips index and query relevant stop interchanges once across all sweeps
    stop_to_trips = _build_stop_to_trips(trips)
    origin_access_stops = {normalise_id(w[3]) for w in origin_walks if len(w) >= 4}
    relevant_stops = set(stop_to_trips.keys()) | origin_access_stops
    interchanges_by_stop = _load_interchanges_for_stops(relevant_stops)

    for dep_t in eval_departures:
        itinerary = _run_raptor_forward(
            dep_time_min=dep_t,
            origin_walks=origin_walks,
            dest_walks=dest_walks,
            trips=trips,
            f_type=f_type,
            f_id=f_id,
            t_type=t_type,
            t_id=t_id,
            min_transfer_min=min_transfer_minutes,
            max_rounds=max_transfers + 1,
            stop_to_trips=stop_to_trips,
            interchanges_by_stop=interchanges_by_stop,
        )
        if itinerary:
            if t_mode == "arrive":
                arr_m = parse_time_to_minutes(itinerary.arrival_time)
                if arr_m is not None and arr_m <= t_start_min:
                    candidate_itineraries.append(itinerary)
            elif t_mode == "window":
                dep_m = parse_time_to_minutes(itinerary.departure_time)
                if (
                    dep_m is not None
                    and dep_m >= t_start_min
                    and dep_m <= (t_end_min or t_start_min)
                ):
                    candidate_itineraries.append(itinerary)
            else:
                candidate_itineraries.append(itinerary)

    if not candidate_itineraries:
        if _check_corridor_connectivity(origin_walks, dest_walks, trips):
            raise NoTripsInWindowError(
                f"Corridor exists, but no trips operate in the time window '{time_str}'.",
                {
                    "timing_mode": t_mode,
                    "time_str": time_str,
                    "active_days": active_days,
                },
            )
        raise NoCorridorPathError(
            f"No viable transit corridor connects origin '{f_id}' to destination '{t_id}'.",
            {"from_id": f_id, "to_id": t_id, "active_days": active_days},
        )

    unique_itineraries: List[ScheduledItinerary] = []
    seen_itineraries: Set[str] = set()

    for it in candidate_itineraries:
        sig = f"{it.departure_time}-{it.arrival_time}-{it.transfers_count}"
        if sig not in seen_itineraries:
            seen_itineraries.add(sig)
            unique_itineraries.append(it)

    if t_mode == "arrive":
        unique_itineraries.sort(
            key=lambda it: (
                -(parse_time_to_minutes(it.departure_time) or 0),
                it.total_duration_minutes,
                it.transfers_count,
            )
        )
    else:
        unique_itineraries.sort(
            key=lambda it: (
                parse_time_to_minutes(it.departure_time) or 0,
                it.total_duration_minutes,
                it.transfers_count,
            )
        )

    return unique_itineraries[:max_itineraries]
