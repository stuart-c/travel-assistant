"""Round-based forward routing engine and path backtracking for RAPTOR."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from app.services.planner.models import (
    ItineraryEndpoint,
    ItineraryLeg,
    ScheduledItinerary,
)
from app.services.planner.raptor.connectivity import _load_interchanges_for_stops
from app.services.planner.raptor.models import _ParsedTrip
from app.services.planner.raptor.transfer_rules import _is_invalid_transfer
from app.services.planner.raptor.trips import _build_stop_to_trips
from app.services.planner.transfers import (
    format_minutes_to_time,
    normalise_id,
    parse_time_to_minutes,
    resolve_endpoint_name,
    resolve_transfer_duration,
)


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
    stop_to_trips: Optional[Dict[str, List[_ParsedTrip]]] = None,
    interchanges_by_stop: Optional[Dict[str, List[Tuple[str, int]]]] = None,
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

    if stop_to_trips is None:
        stop_to_trips = _build_stop_to_trips(trips)

    if interchanges_by_stop is None:
        origin_access_stops = {normalise_id(w[3]) for w in origin_walks if len(w) >= 4}
        interchanges_by_stop = _load_interchanges_for_stops(
            set(stop_to_trips.keys()) | origin_access_stops
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
                        if k > 1 and _is_invalid_transfer(tr, s_norm, k, leg_pointer):
                            continue
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
    best_weighted_score = infinity
    best_egress_info: Optional[Tuple[int, str, str, int]] = None

    for k in range(1, max_rounds + 1):
        for source_type, source_id, _, _, walk_min, _ in dest_walks:
            s_norm = normalise_id(source_id)
            if s_norm in tau[k]:
                total_arr = tau[k][s_norm] + walk_min
                # Apply a 5-minute penalty per additional transfer to disincentivise multi-bus hopping
                weighted_score = total_arr + (k - 1) * 5
                if weighted_score < best_weighted_score:
                    best_weighted_score = weighted_score
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
        if l2_dep < l1_arr:
            l2_dep += 1440
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
    if arr_m < dep_m:
        arr_m += 1440
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
