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
        if next_dep_m is None or next_dep_m < prev_arr_m:
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
                    # Bus legs do not use rail platform
                    if active.platform and not any(
                        w in active.platform.lower() for w in ("stand", "stop")
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


__all__ = [
    "_find_next_timetable_trip",
    "_propagate_leg_timings",
    "_realign_active_journey_timings",
]
