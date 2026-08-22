"""RAPTOR (Round-Based Public Transit Routing) trip scheduling engine (Mode 2)."""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from app.models.timetable import Timetable
from app.models.transit import StopInterchange
from app.models.walking import Walking
from app.services.exceptions import (
    InvalidEndpointError,
    JourneyPlanningError,
    JourneyPlanningErrorCode,
    NoAccessStopsError,
    NoCorridorPathError,
    NoServicesOnDayError,
    NoTripsInWindowError,
)
from app.services.models import (
    ItineraryEndpoint,
    ItineraryLeg,
    ScheduledItinerary,
)
from app.services.route_finder import find_routes
from app.services.transfers import (
    format_minutes_to_time,
    get_access_edges,
    is_timetable_active,
    normalise_id,
    parse_time_to_minutes,
    resolve_active_days_and_date,
    resolve_endpoint_name,
    resolve_transfer_duration,
)


class _ParsedTrip:
    """Internal representation of a timetable trip for the RAPTOR solver."""

    def __init__(
        self,
        trip_id: str,
        timetable_id: int,
        line_name: str,
        transport_mode: str,
        operator: Optional[str],
        headsign: Optional[str],
        stops: List[str],
        arr_times: List[Optional[int]],
        dep_times: List[Optional[int]],
    ) -> None:
        self.trip_id = trip_id
        self.timetable_id = timetable_id
        self.line_name = line_name
        self.transport_mode = transport_mode
        self.operator = operator
        self.headsign = headsign
        self.stops = stops
        self.arr_times = arr_times
        self.dep_times = dep_times
        self.stop_indices = {s: i for i, s in enumerate(stops)}


def _extract_parsed_trips(timetables: List[Timetable]) -> List[_ParsedTrip]:
    """Convert Peewee Timetable models to structured in-memory trips."""
    parsed_trips: List[_ParsedTrip] = []

    for tt in timetables:
        content_dict = tt.get_content()
        stops_raw = content_dict.get("stops", [])
        trips_raw = content_dict.get("trips", [])

        if not stops_raw or not trips_raw:
            continue

        stop_ids = [str(s.get("id", "")).strip() for s in stops_raw]

        for tr in trips_raw:
            times = tr.get("times", [])
            arr_list: List[Optional[int]] = []
            dep_list: List[Optional[int]] = []

            for t_item in times:
                if isinstance(t_item, dict):
                    arr_s = t_item.get("arr") or ""
                    dep_s = t_item.get("dep") or ""
                else:
                    arr_s = str(t_item or "")
                    dep_s = str(t_item or "")

                arr_m = parse_time_to_minutes(arr_s)
                dep_m = parse_time_to_minutes(dep_s)

                if arr_m is None and dep_m is not None:
                    arr_m = dep_m
                elif dep_m is None and arr_m is not None:
                    dep_m = arr_m

                arr_list.append(arr_m)
                dep_list.append(dep_m)

            while len(arr_list) < len(stop_ids):
                arr_list.append(None)
                dep_list.append(None)

            parsed_trips.append(
                _ParsedTrip(
                    trip_id=str(tr.get("id", "")),
                    timetable_id=tt.id,
                    line_name=tt.name,
                    transport_mode=tt.transport_type,
                    operator=tr.get("operator") or tr.get("toc"),
                    headsign=tr.get("headsign"),
                    stops=stop_ids,
                    arr_times=arr_list,
                    dep_times=dep_list,
                )
            )

    return parsed_trips


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
        to_type: Destination location type ("ha", "custom", "rail", "bus", etc.).
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

    # 1. Access & Egress Footpaths
    origin_walks = get_access_edges(f_type, f_id, is_origin=True)
    dest_walks = get_access_edges(t_type, t_id, is_origin=False)

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

    # 2. Extract and Filter Timetables & Trips
    all_timetables = list(Timetable.select())
    active_timetables = [
        tt for tt in all_timetables if is_timetable_active(tt, active_days, date_obj)
    ]

    trips = _extract_parsed_trips(active_timetables)

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
        eval_departures = [t_start_min]
    elif t_mode == "window":
        eval_departures = list(range(t_start_min, (t_end_min or t_start_min) + 1, 10))
    elif t_mode == "arrive":
        earliest_dep = max(0, t_start_min - 240)
        eval_departures = list(range(earliest_dep, t_start_min, 10))

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
        try:
            find_routes(f_type, f_id, t_type, t_id, days_of_week, target_date)
            raise NoTripsInWindowError(
                f"Corridor exists, but no trips operate in the time window '{time_str}'.",
                {
                    "timing_mode": t_mode,
                    "time_str": time_str,
                    "active_days": active_days,
                },
            )
        except (NoAccessStopsError, NoCorridorPathError):
            raise

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


def _run_raptor_forward(
    dep_time_min: int,
    origin_walks: List[Tuple[str, str, str, str, int, str]],
    dest_walks: List[Tuple[str, str, str, str, int, str]],
    trips: List[_ParsedTrip],
    f_type: str,
    f_id: str,
    t_type: str,
    t_id: str,
    min_transfer_min: int = 3,
    max_rounds: int = 5,
) -> Optional[ScheduledItinerary]:
    """Execute a single forward RAPTOR run from dep_time_min."""
    infinity = 99999

    tau: Dict[int, Dict[str, int]] = {}
    tau_star: Dict[str, int] = {}
    leg_pointer: Dict[int, Dict[str, Any]] = {}

    for k in range(max_rounds + 1):
        tau[k] = {}
        leg_pointer[k] = {}

    marked_stops: Set[str] = set()
    orig_name = resolve_endpoint_name(f_type, f_id)

    for _, _, target_type, target_id, walk_min, kind in origin_walks:
        target_norm = normalise_id(target_id)
        arr_t = dep_time_min + walk_min
        tau[0][target_norm] = arr_t
        tau_star[target_norm] = arr_t
        leg_pointer[0][target_norm] = {
            "mode": "walk",
            "from_type": f_type,
            "from_id": f_id,
            "from_name": orig_name,
            "to_type": target_type,
            "to_id": target_id,
            "to_name": resolve_endpoint_name(target_type, target_id),
            "dep_time": dep_time_min,
            "arr_time": arr_t,
            "duration": walk_min,
        }
        marked_stops.add(target_norm)

    stop_to_trips: Dict[str, List[_ParsedTrip]] = {}
    for tr in trips:
        for s in tr.stops:
            s_norm = normalise_id(s)
            stop_to_trips.setdefault(s_norm, []).append(tr)

    stop_interchanges = list(StopInterchange.select())
    interchanges_by_stop: Dict[str, List[Tuple[str, int]]] = {}
    for si in stop_interchanges:
        f_st = normalise_id(si.from_stop_atco)
        t_st = normalise_id(si.to_stop_atco)
        interchanges_by_stop.setdefault(f_st, []).append(
            (t_st, si.estimated_walk_minutes)
        )

    for k in range(1, max_rounds + 1):
        for s, arr_t in tau[k - 1].items():
            tau[k][s] = arr_t

        routes_to_scan: Set[_ParsedTrip] = set()
        for s in marked_stops:
            for tr in stop_to_trips.get(s, []):
                routes_to_scan.add(tr)

        marked_stops.clear()

        for tr in routes_to_scan:
            boarding_idx: Optional[int] = None
            boarding_dep_t: Optional[int] = None

            for i, stop_id in enumerate(tr.stops):
                s_norm = normalise_id(stop_id)
                arr_t = tr.arr_times[i]
                dep_t = tr.dep_times[i]

                if boarding_idx is not None and arr_t is not None:
                    prev_best = tau_star.get(s_norm, infinity)
                    if arr_t < prev_best:
                        tau[k][s_norm] = arr_t
                        tau_star[s_norm] = arr_t
                        boarding_stop_id = tr.stops[boarding_idx]
                        leg_pointer[k][s_norm] = {
                            "mode": tr.transport_mode,
                            "trip": tr,
                            "from_stop": boarding_stop_id,
                            "from_name": resolve_endpoint_name(
                                tr.transport_mode, boarding_stop_id
                            ),
                            "to_stop": stop_id,
                            "to_name": resolve_endpoint_name(
                                tr.transport_mode, stop_id
                            ),
                            "dep_time": boarding_dep_t,
                            "arr_time": arr_t,
                            "duration": arr_t - (boarding_dep_t or arr_t),
                            "stops_count": i - boarding_idx,
                            "timetable_id": tr.timetable_id,
                            "line": tr.line_name,
                            "operator": tr.operator,
                            "headsign": tr.headsign,
                        }
                        marked_stops.add(s_norm)

                prev_arr = tau[k - 1].get(s_norm, infinity)
                if prev_arr < infinity and dep_t is not None:
                    transfer_slack = min_transfer_min if k > 1 else 0
                    if dep_t >= prev_arr + transfer_slack:
                        if boarding_idx is None or dep_t < (boarding_dep_t or infinity):
                            boarding_idx = i
                            boarding_dep_t = dep_t

        for stop_norm in list(marked_stops):
            curr_arr = tau[k][stop_norm]

            for target_norm, walk_min in interchanges_by_stop.get(stop_norm, []):
                trans_arr = curr_arr + walk_min
                if trans_arr < tau_star.get(target_norm, infinity):
                    tau[k][target_norm] = trans_arr
                    tau_star[target_norm] = trans_arr
                    leg_pointer[k][target_norm] = {
                        "mode": "interchange",
                        "from_stop": stop_norm,
                        "from_name": resolve_endpoint_name("bus", stop_norm),
                        "to_stop": target_norm,
                        "to_name": resolve_endpoint_name("bus", target_norm),
                        "dep_time": curr_arr,
                        "arr_time": trans_arr,
                        "duration": walk_min,
                    }
                    marked_stops.add(target_norm)

            trans_info = resolve_transfer_duration("rail", stop_norm, "rail", stop_norm)
            if trans_info:
                dur, kind, _ = trans_info
                plat_arr = curr_arr + dur
                if plat_arr < tau_star.get(stop_norm, infinity):
                    tau[k][stop_norm] = plat_arr
                    tau_star[stop_norm] = plat_arr

        if not marked_stops:
            break

    best_final_arrival = infinity
    best_egress_info: Optional[Tuple[int, str, str, int]] = None

    for k in range(1, max_rounds + 1):
        for source_type, source_id, _, _, walk_min, _ in dest_walks:
            s_norm = normalise_id(source_id)
            if s_norm in tau[k]:
                total_arr = tau[k][s_norm] + walk_min
                if total_arr < best_final_arrival:
                    best_final_arrival = total_arr
                    best_egress_info = (k, s_norm, source_id, walk_min)

    if best_egress_info is None or best_final_arrival >= infinity:
        return None

    target_round, curr_stop, egress_stop_id, egress_walk_min = best_egress_info
    dest_name = resolve_endpoint_name(t_type, t_id)
    legs_backtracked: List[ItineraryLeg] = []

    if egress_walk_min > 0 or normalise_id(egress_stop_id) != normalise_id(t_id):
        arr_s = format_minutes_to_time(best_final_arrival)
        dep_s = format_minutes_to_time(best_final_arrival - egress_walk_min)
        legs_backtracked.append(
            ItineraryLeg(
                leg_index=999,
                mode="walk",
                origin=ItineraryEndpoint(
                    id=egress_stop_id,
                    name=resolve_endpoint_name(t_type, egress_stop_id),
                ),
                destination=ItineraryEndpoint(id=t_id, name=dest_name),
                dep_time=dep_s,
                arr_time=arr_s,
                duration_minutes=egress_walk_min,
            )
        )

    r = target_round
    curr = curr_stop
    slack_minutes_list: List[int] = []

    while r >= 0 and curr:
        p = leg_pointer[r].get(curr)
        if not p:
            break

        mode = p.get("mode", "walk")
        dep_t = p.get("dep_time", 0)
        arr_t = p.get("arr_time", 0)
        dur = p.get("duration", 0)

        if mode == "walk":
            if dur > 0 or normalise_id(p.get("from_id", "")) != normalise_id(
                p.get("to_id", "")
            ):
                legs_backtracked.append(
                    ItineraryLeg(
                        leg_index=0,
                        mode="walk",
                        origin=ItineraryEndpoint(
                            id=p.get("from_id", ""), name=p.get("from_name", "")
                        ),
                        destination=ItineraryEndpoint(
                            id=p.get("to_id", ""), name=p.get("to_name", "")
                        ),
                        dep_time=format_minutes_to_time(dep_t),
                        arr_time=format_minutes_to_time(arr_t),
                        duration_minutes=dur,
                    )
                )
            break
        elif mode == "interchange":
            legs_backtracked.append(
                ItineraryLeg(
                    leg_index=0,
                    mode="interchange",
                    origin=ItineraryEndpoint(
                        id=p.get("from_stop", ""), name=p.get("from_name", "")
                    ),
                    destination=ItineraryEndpoint(
                        id=p.get("to_stop", ""), name=p.get("to_name", "")
                    ),
                    dep_time=format_minutes_to_time(dep_t),
                    arr_time=format_minutes_to_time(arr_t),
                    duration_minutes=dur,
                )
            )
            curr = normalise_id(p.get("from_stop", ""))
        else:
            legs_backtracked.append(
                ItineraryLeg(
                    leg_index=0,
                    mode=mode,
                    origin=ItineraryEndpoint(
                        id=p.get("from_stop", ""), name=p.get("from_name", "")
                    ),
                    destination=ItineraryEndpoint(
                        id=p.get("to_stop", ""), name=p.get("to_name", "")
                    ),
                    dep_time=format_minutes_to_time(dep_t),
                    arr_time=format_minutes_to_time(arr_t),
                    duration_minutes=dur,
                    line=p.get("line"),
                    operator=p.get("operator"),
                    headsign=p.get("headsign"),
                    stops_count=p.get("stops_count"),
                    timetable_id=p.get("timetable_id"),
                )
            )
            curr = normalise_id(p.get("from_stop", ""))
            r -= 1

    legs_backtracked.reverse()

    final_legs: List[ItineraryLeg] = []
    for idx, leg in enumerate(legs_backtracked, start=1):
        leg.leg_index = idx
        final_legs.append(leg)

    if not final_legs:
        return None

    for i in range(len(final_legs) - 1):
        l1 = final_legs[i]
        l2 = final_legs[i + 1]
        l1_arr = parse_time_to_minutes(l1.arr_time) or 0
        l2_dep = parse_time_to_minutes(l2.dep_time) or 0
        slack = l2_dep - l1_arr
        if l1.mode != "walk" or l2.mode != "walk":
            slack_minutes_list.append(slack)

    min_slack = min(slack_minutes_list) if slack_minutes_list else 10
    if min_slack >= 6:
        robustness = f"High (+{min_slack} min transfer slack)"
    elif min_slack >= 2:
        robustness = f"Moderate (+{min_slack} min transfer slack)"
    else:
        robustness = f"Tight (+{min_slack} min transfer slack)"

    initial_dep_str = final_legs[0].dep_time
    final_arr_str = final_legs[-1].arr_time
    dep_m = parse_time_to_minutes(initial_dep_str) or 0
    arr_m = parse_time_to_minutes(final_arr_str) or 0
    total_dur = max(1, arr_m - dep_m)
    transfers = (
        sum(
            1
            for leg in final_legs
            if leg.mode in ("bus", "rail", "metro", "tram", "ferry")
        )
        - 1
    )

    return ScheduledItinerary(
        departure_time=initial_dep_str,
        arrival_time=final_arr_str,
        total_duration_minutes=total_dur,
        transfers_count=max(0, transfers),
        robustness_score=robustness,
        legs=final_legs,
    )


__all__ = [
    "plan_journey",
]
