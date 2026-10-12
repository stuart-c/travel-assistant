"""Dynamic schedule realignment and connection propagation for active journeys."""

import datetime
import logging
from typing import Optional, Tuple

from app.datasources.train_live import TrainLiveClient
from app.services.dispatcher.tracker.models import (
    FOOT_MODES,
    ActiveJourney,
    JourneyStepStatus,
)
from app.services.dispatcher.tracker.platform_service import resolve_live_rail_platform
from app.services.planner.transfers import (
    get_active_timetables,
    normalise_id,
)
from app.utils.geo import resolve_endpoint_coordinates
from app.utils.transit_time import (
    format_minutes_to_time,
    get_day_code,
    parse_time_to_minutes,
)

logger = logging.getLogger(__name__)


def _propagate_leg_timings(active: ActiveJourney, from_index: int) -> None:
    """Propagate updated departure and arrival times to downstream legs and final ETA."""
    for i in range(from_index, len(active.legs) - 1):
        prev_leg = active.legs[i]
        next_leg = active.legs[i + 1]
        prev_arr_m = parse_time_to_minutes(prev_leg.arr_time)
        if prev_arr_m is None:
            continue
        next_dep_m = parse_time_to_minutes(next_leg.dep_time)
        if next_leg.mode in FOOT_MODES or next_dep_m is None or next_dep_m < prev_arr_m:
            next_leg.dep_time = prev_leg.arr_time
            dur = next_leg.duration_minutes or 5
            next_leg.arr_time = format_minutes_to_time(prev_arr_m + dur)

    if active.legs:
        last_leg = active.legs[-1]
        if last_leg.arr_time:
            active.expected_arrival_time = last_leg.arr_time


def _find_next_timetable_trip(
    origin_id: str,
    dest_id: str,
    after_minutes: int,
    current_dt: datetime.datetime,
) -> Optional[Tuple[str, str, str, Optional[str]]]:
    """Find next scheduled timetable departure between two stops after a given time.

    Returns (dep_time, arr_time, line_name, operator_name) or None if no trip found.
    """
    day_code = get_day_code(current_dt)
    active_timetables = get_active_timetables([day_code], current_dt.date())

    norm_orig = normalise_id(origin_id)
    norm_dest = normalise_id(dest_id)

    best_match: Optional[Tuple[int, str, str, str, Optional[str]]] = None

    for tt in active_timetables:
        content = tt.get_content()
        stops = content.get("stops", [])
        if len(stops) < 2:
            continue

        orig_idx = -1
        dest_idx = -1
        for idx, s in enumerate(stops):
            s_id = normalise_id(s.get("id", ""))
            if s_id == norm_orig and orig_idx == -1:
                orig_idx = idx
            elif s_id == norm_dest and orig_idx != -1:
                dest_idx = idx
                break

        if orig_idx == -1 or dest_idx == -1 or orig_idx >= dest_idx:
            continue

        trips = content.get("trips", [])
        for trip in trips:
            times = trip.get("times", [])
            if len(times) <= max(orig_idx, dest_idx):
                continue

            t1 = times[orig_idx]
            t2 = times[dest_idx]
            dep_s = (t1.get("dep") or t1.get("arr")) if isinstance(t1, dict) else t1
            arr_s = (t2.get("arr") or t2.get("dep")) if isinstance(t2, dict) else t2
            dep_m = parse_time_to_minutes(dep_s)
            arr_m = parse_time_to_minutes(arr_s)

            if dep_m is not None and dep_m >= after_minutes:
                if best_match is None or dep_m < best_match[0]:
                    op = trip.get("operator") or trip.get("toc")
                    dur = (
                        max(1, (arr_m - dep_m))
                        if (arr_m is not None and dep_m is not None)
                        else 15
                    )
                    best_arr_s = (
                        arr_s
                        if arr_m is not None
                        else format_minutes_to_time(dep_m + dur)
                    )
                    best_match = (
                        dep_m,
                        dep_s,
                        best_arr_s,
                        tt.name,
                        op,
                    )

    if best_match:
        _, dep_time, arr_time, line, op = best_match
        return (dep_time, arr_time, line, op)
    return None


def _realign_active_journey_timings(
    active: ActiveJourney,
    current_dt: datetime.datetime,
    live_client: Optional[TrainLiveClient] = None,
) -> None:
    """Realign upcoming transit leg timings and downstream connections when falling behind schedule."""
    if not active.legs:
        return

    current_minutes = current_dt.hour * 60 + current_dt.minute

    # Scan upcoming legs from current_leg_index onwards
    for idx in range(active.current_leg_index, len(active.legs)):
        leg = active.legs[idx]

        # If Stuart is currently on board this leg, its departure is already in the past by definition
        if (
            idx == active.current_leg_index
            and active.current_status == JourneyStepStatus.ON_TRANSIT
        ):
            continue

        if leg.mode in FOOT_MODES:
            continue

        dep_m = parse_time_to_minutes(leg.dep_time)
        if dep_m is None:
            continue

        # Check if commuter is at an interchange or departure stop early with an excessive wait,
        # where an earlier departure could be caught:
        is_early = (
            idx == active.current_leg_index
            and active.current_status
            in (JourneyStepStatus.AT_INTERCHANGE, JourneyStepStatus.AT_DEPARTURE_STOP)
            and dep_m > current_minutes + 5
        )

        if is_early:
            # 1. Check timetable for an earlier trip departing after current time + 1 min buffer
            earlier_trip = _find_next_timetable_trip(
                origin_id=leg.origin.id,
                dest_id=leg.destination.id,
                after_minutes=current_minutes + 1,
                current_dt=current_dt,
            )
            if earlier_trip:
                e_dep, e_arr, e_line, e_op = earlier_trip
                e_dep_m = parse_time_to_minutes(e_dep)
                if e_dep_m is not None and e_dep_m < dep_m:
                    leg.dep_time = e_dep
                    leg.arr_time = e_arr
                    if e_line:
                        leg.line = e_line
                    if e_op:
                        leg.operator = e_op
                    if leg.origin and leg.origin.platform:
                        active.platform = leg.origin.platform
                    _propagate_leg_timings(active, idx)
                    logger.info(
                        "Pulled forward active timetable leg %d (%s -> %s) to earlier trip %s (arr %s)",
                        idx,
                        leg.origin.name,
                        leg.destination.name,
                        e_dep,
                        e_arr,
                    )
                    continue

            # 2. Check live rail if early at rail station
            if leg.mode == "rail" and live_client:
                live_res = resolve_live_rail_platform(
                    origin_id=leg.origin.id,
                    dest_id=leg.destination.id,
                    scheduled_time=format_minutes_to_time(current_minutes + 1),
                    live_client=live_client,
                )
                if live_res.std:
                    earlier_rail_dep_m = parse_time_to_minutes(live_res.std)
                    if (
                        earlier_rail_dep_m is not None
                        and current_minutes <= earlier_rail_dep_m < dep_m
                    ):
                        leg.dep_time = live_res.std
                        dur = leg.duration_minutes or 20
                        leg.arr_time = format_minutes_to_time(earlier_rail_dep_m + dur)
                        if live_res.platform:
                            leg.origin.platform = live_res.platform
                            active.platform = live_res.platform
                        active.live_status = live_res.etd
                        active.delay_minutes = live_res.delay_minutes
                        active.delay_reason = live_res.delay_reason
                        _propagate_leg_timings(active, idx)
                        logger.info(
                            "Pulled forward active rail leg %d (%s -> %s) to earlier live train %s (arr %s)",
                            idx,
                            leg.origin.name,
                            leg.destination.name,
                            leg.dep_time,
                            leg.arr_time,
                        )
                        continue

            # 3. If wait at interchange is long (> 15 mins) and active journey has an associated journey model,
            # query dynamic reroute from current stop to see if a faster connecting route is available
            if dep_m > current_minutes + 15 and active.journey_id:
                try:
                    from app.models.journey import Journey
                    from app.services.reroute_engine import RerouteEngine

                    journey_obj = Journey.get_by_id(active.journey_id)
                    if journey_obj:
                        re_engine = RerouteEngine(live_client=live_client)
                        cur_orig_lat, cur_orig_lon, _ = resolve_endpoint_coordinates(
                            leg.mode, leg.origin.id
                        )
                        rerouted_itin, _ = re_engine.evaluate_and_reroute(
                            journey=journey_obj,
                            trigger_reason=f"Early arrival at interchange ({dep_m - current_minutes}m wait)",
                            departure_time=current_dt,
                            current_lat=cur_orig_lat,
                            current_lon=cur_orig_lon,
                        )
                        if rerouted_itin and rerouted_itin.legs:
                            new_arr_m = parse_time_to_minutes(
                                rerouted_itin.arrival_time
                            )
                            old_arr_m = parse_time_to_minutes(
                                active.expected_arrival_time
                            )
                            if (
                                new_arr_m is not None
                                and old_arr_m is not None
                                and new_arr_m < old_arr_m
                            ):
                                spliced_legs = list(active.legs[:idx])
                                for r_idx, r_leg in enumerate(
                                    rerouted_itin.legs, start=idx
                                ):
                                    r_leg.leg_index = r_idx
                                    spliced_legs.append(r_leg)
                                active.legs = spliced_legs
                                active.expected_arrival_time = (
                                    rerouted_itin.arrival_time
                                )
                                cur_l = active.legs[idx]
                                if cur_l.origin and cur_l.origin.platform:
                                    active.platform = cur_l.origin.platform
                                elif active.platform and not any(
                                    w in str(active.platform).lower()
                                    for w in ("stand", "stop", "bay")
                                ):
                                    active.platform = None
                                logger.info(
                                    "Dynamic reroute pulled forward connection for journey %d at leg %d: new ETA %s (was %s)",
                                    active.journey_id,
                                    idx,
                                    active.expected_arrival_time,
                                    format_minutes_to_time(old_arr_m),
                                )
                                continue
                except Exception as reroute_exc:
                    logger.debug(
                        "Early arrival dynamic reroute check skipped: %s", reroute_exc
                    )

        # If departure time is in the past (more than 1 min ago)
        if dep_m < current_minutes - 1:
            if leg.mode == "rail" and live_client:
                live_res = resolve_live_rail_platform(
                    origin_id=leg.origin.id,
                    dest_id=leg.destination.id,
                    scheduled_time=leg.dep_time,
                    live_client=live_client,
                )
                if live_res.std:
                    new_dep_m = parse_time_to_minutes(live_res.std)
                    if new_dep_m is not None and new_dep_m >= current_minutes - 1:
                        leg.dep_time = live_res.std
                        dur = leg.duration_minutes or 20
                        leg.arr_time = format_minutes_to_time(new_dep_m + dur)
                        if live_res.platform:
                            leg.origin.platform = live_res.platform
                        if idx == active.current_leg_index:
                            active.platform = live_res.platform
                            active.live_status = live_res.etd
                            active.delay_minutes = live_res.delay_minutes
                            active.delay_reason = live_res.delay_reason
                        _propagate_leg_timings(active, idx)
                        logger.info(
                            "Realigned active rail leg %d (%s -> %s) to %s (arr %s)",
                            idx,
                            leg.origin.name,
                            leg.destination.name,
                            leg.dep_time,
                            leg.arr_time,
                        )
                        continue

            # Non-rail or rail fallback to timetable
            next_trip = _find_next_timetable_trip(
                origin_id=leg.origin.id,
                dest_id=leg.destination.id,
                after_minutes=current_minutes,
                current_dt=current_dt,
            )
            if next_trip:
                new_dep, new_arr, line_name, op = next_trip
                leg.dep_time = new_dep
                leg.arr_time = new_arr
                if line_name:
                    leg.line = line_name
                if op:
                    leg.operator = op
                if idx == active.current_leg_index:
                    active.live_status = None
                    active.delay_minutes = 0
                    active.delay_reason = None
                    # Non-rail legs (bus) do not use rail platform, but preserve bus stand/stop
                    if leg.origin and leg.origin.platform:
                        active.platform = leg.origin.platform
                    elif active.platform and not any(
                        w in active.platform.lower() for w in ("stand", "stop", "bay")
                    ):
                        active.platform = None
                _propagate_leg_timings(active, idx)
                logger.info(
                    "Realigned active timetable leg %d (%s -> %s) to %s (arr %s)",
                    idx,
                    leg.origin.name,
                    leg.destination.name,
                    new_dep,
                    new_arr,
                )
            else:
                # If neither live rail nor timetable trip was found, roll forward the estimated departure
                # to current time + 2 minutes to keep ETA realistic and prevent stale past departure times
                dur = leg.duration_minutes
                if dur is None:
                    orig_arr_m = parse_time_to_minutes(leg.arr_time)
                    if orig_arr_m is not None and dep_m is not None:
                        dur = max(1, orig_arr_m - dep_m)
                    else:
                        dur = 15
                new_dep_m = current_minutes + 2
                leg.dep_time = format_minutes_to_time(new_dep_m)
                leg.arr_time = format_minutes_to_time(new_dep_m + dur)
                if idx == active.current_leg_index:
                    active.live_status = None
                    active.delay_minutes = max(0, new_dep_m - dep_m)
                    active.delay_reason = "Service estimated / delayed"
                    if leg.origin and leg.origin.platform:
                        active.platform = leg.origin.platform
                    elif active.platform and not any(
                        w in active.platform.lower() for w in ("stand", "stop", "bay")
                    ):
                        active.platform = None
                _propagate_leg_timings(active, idx)
                logger.info(
                    "Estimated roll-forward for leg %d (%s -> %s) to %s (arr %s)",
                    idx,
                    leg.origin.name,
                    leg.destination.name,
                    leg.dep_time,
                    leg.arr_time,
                )


__all__ = [
    "_find_next_timetable_trip",
    "_propagate_leg_timings",
    "_realign_active_journey_timings",
]
