"""Heuristic corridor detection of en-route journeys based on spatial proximity."""

import datetime
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.datasources.train_live import TrainLiveClient
from app.models.journey import Journey
from app.services.dispatcher.proximity import is_person_near_origin
from app.services.dispatcher.tracker.models import (
    FOOT_MODES,
    ActiveJourney,
    JourneyStepStatus,
    LiveRailStatus,
)
from app.services.dispatcher.tracker.platform_service import (
    resolve_live_rail_platform,
)
from app.services.planner.models import ScheduledItinerary
from app.utils.geo import haversine_distance_m, resolve_endpoint_coordinates
from app.utils.transit_time import (
    format_minutes_to_time,
    get_day_code,
    parse_time_to_minutes,
)

logger = logging.getLogger(__name__)


def _discover_candidate_itineraries(
    journey: Journey,
    current_minutes: int,
    current_dt: datetime.datetime,
) -> Optional[List[ScheduledItinerary]]:
    """Search for candidate itineraries covering a 2-hour window up to 15 minutes ahead."""
    day_code = get_day_code(current_dt)
    search_start_min = max(0, current_minutes - 120)
    search_time_str = format_minutes_to_time(search_start_min)
    search_end_min = min(1439, current_minutes + 15)
    search_end_str = format_minutes_to_time(search_end_min)

    try:
        from app.services.planner.raptor import plan_journey

        return plan_journey(
            from_type=journey.from_type,
            from_id=journey.from_id,
            to_type=journey.to_type,
            to_id=journey.to_id,
            timing_mode="window",
            time_str=search_time_str,
            time_window_end=search_end_str,
            days_of_week=[day_code],
            target_date=current_dt.date(),
            max_itineraries=8,
        )
    except Exception as exc:
        logger.debug(
            "Could not plan candidate itineraries for en-route detection on journey %d: %s",
            journey.id,
            exc,
        )
        return None


def detect_en_route_journey(
    journey: Journey,
    person_state: Optional[Dict[str, Any]],
    current_dt: datetime.datetime,
    live_client: Optional[TrainLiveClient] = None,
    max_proximity_metres: float = 200.0,
) -> Optional[ActiveJourney]:
    """Detect if Stuart is currently en route along a scheduled journey corridor.

    Evaluates recent scheduled itineraries for the journey to determine if Stuart's
    current GPS location matches any intermediate transit stop, interchange, or transit leg.
    If a matching progression stage is detected, instantiates and returns an ActiveJourney.
    """
    if not person_state or not isinstance(person_state, dict):
        return None

    # Stuart cannot be en route if still near the origin or already at destination
    if is_person_near_origin(person_state, journey.from_type, journey.from_id):
        return None
    if is_person_near_origin(person_state, journey.to_type, journey.to_id):
        return None

    attrs = person_state.get("attributes", {}) or {}
    raw_lat = attrs.get("latitude")
    raw_lon = attrs.get("longitude")
    if raw_lat is None or raw_lon is None:
        return None

    try:
        person_lat = float(raw_lat)
        person_lon = float(raw_lon)
    except (ValueError, TypeError):
        return None

    current_minutes = current_dt.hour * 60 + current_dt.minute
    itineraries = _discover_candidate_itineraries(journey, current_minutes, current_dt)
    if not itineraries:
        return None

    matching_candidates: List[Tuple[float, ActiveJourney]] = []

    for itin in itineraries:
        if not itin.legs:
            continue

        dep_m = parse_time_to_minutes(itin.departure_time)
        arr_m = parse_time_to_minutes(itin.arrival_time)
        if dep_m is None or arr_m is None:
            continue

        if arr_m < dep_m:
            arr_m += 1440

        cur_m_effective = (
            current_minutes + 1440
            if (current_minutes < 120 and dep_m > 1200)
            else current_minutes
        )

        # Candidate must cover current time (dep_m <= cur_m_effective <= arr_m + 60)
        if dep_m > cur_m_effective or cur_m_effective > arr_m + 60:
            continue

        for leg_idx, leg in enumerate(itin.legs):
            orig_lat, orig_lon, _ = resolve_endpoint_coordinates(
                leg.mode, leg.origin.id
            )
            dest_lat, dest_lon, _ = resolve_endpoint_coordinates(
                leg.mode, leg.destination.id
            )

            dist_orig = (
                haversine_distance_m(person_lat, person_lon, orig_lat, orig_lon)
                if (orig_lat is not None and orig_lon is not None)
                else None
            )
            dist_dest = (
                haversine_distance_m(person_lat, person_lon, dest_lat, dest_lon)
                if (dest_lat is not None and dest_lon is not None)
                else None
            )

            leg_dep_m = parse_time_to_minutes(leg.dep_time)
            leg_arr_m = parse_time_to_minutes(leg.arr_time)
            if (
                leg_dep_m is not None
                and leg_arr_m is not None
                and leg_arr_m < leg_dep_m
            ):
                leg_arr_m += 1440

            leg_cur_m = (
                current_minutes + 1440
                if (
                    leg_dep_m is not None and current_minutes < 120 and leg_dep_m > 1200
                )
                else current_minutes
            )

            # 1. At the departure stop or interchange for this leg
            if dist_orig is not None and dist_orig <= max_proximity_metres:
                # If current time is past leg arrival time, this leg has already concluded
                if leg_arr_m is not None and leg_cur_m > leg_arr_m:
                    continue

                live_res = LiveRailStatus()
                if leg.mode == "rail" and live_client:
                    live_res = resolve_live_rail_platform(
                        origin_id=leg.origin.id,
                        dest_id=leg.destination.id,
                        scheduled_time=leg.dep_time,
                        live_client=live_client,
                    )

                # Expiration check: if scheduled departure was more than 15 mins ago,
                # only accept if live status confirms an expected departure that hasn't passed
                if leg_dep_m is not None and leg_cur_m > leg_dep_m + 15:
                    if live_res.etd and ":" in live_res.etd:
                        etd_m = parse_time_to_minutes(live_res.etd)
                        if etd_m is not None and leg_cur_m > etd_m + 10:
                            continue
                    elif live_res.etd not in ("Delayed",):
                        continue

                if leg_idx == 0 or (leg_idx == 1 and itin.legs[0].mode in FOOT_MODES):
                    status = JourneyStepStatus.AT_DEPARTURE_STOP
                else:
                    status = JourneyStepStatus.AT_INTERCHANGE

                ref_m = leg_dep_m if leg_dep_m is not None else leg_cur_m
                time_delta = abs(leg_cur_m - ref_m)

                matching_candidates.append(
                    (
                        time_delta,
                        ActiveJourney(
                            journey_id=journey.id,
                            journey_name=journey.name,
                            from_type=journey.from_type,
                            from_id=journey.from_id,
                            from_name=journey.from_name,
                            to_type=journey.to_type,
                            to_id=journey.to_id,
                            to_name=journey.to_name,
                            itinerary=itin,
                            legs=list(itin.legs),
                            current_leg_index=leg_idx,
                            current_status=status,
                            started_at=current_dt,
                            expected_arrival_time=itin.arrival_time,
                            platform=live_res.platform,
                            live_status=live_res.etd,
                            delay_minutes=live_res.delay_minutes,
                            delay_reason=live_res.delay_reason,
                        ),
                    )
                )

            # 2. At the destination of this leg
            if dist_dest is not None and dist_dest <= max_proximity_metres:
                if leg_arr_m is not None and leg_cur_m > leg_arr_m + 30:
                    continue

                next_idx = leg_idx + 1
                if leg_idx == 0 and leg.mode in FOOT_MODES:
                    status = JourneyStepStatus.AT_DEPARTURE_STOP
                elif next_idx >= len(itin.legs):
                    status = JourneyStepStatus.ARRIVED
                elif (
                    next_idx == len(itin.legs) - 1
                    and itin.legs[next_idx].mode in FOOT_MODES
                ):
                    status = JourneyStepStatus.EN_ROUTE_TO_DESTINATION
                else:
                    status = JourneyStepStatus.AT_INTERCHANGE

                next_leg = itin.legs[next_idx] if next_idx < len(itin.legs) else None
                live_res = LiveRailStatus()
                if next_leg and next_leg.mode == "rail" and live_client:
                    live_res = resolve_live_rail_platform(
                        origin_id=next_leg.origin.id,
                        dest_id=next_leg.destination.id,
                        scheduled_time=next_leg.dep_time,
                        live_client=live_client,
                    )

                # Connecting departure expiration check:
                if next_leg and next_leg.mode not in FOOT_MODES:
                    nl_dep = parse_time_to_minutes(next_leg.dep_time)
                    if nl_dep is not None:
                        effective_dep = nl_dep
                        if live_res.etd and ":" in live_res.etd:
                            etd_m = parse_time_to_minutes(live_res.etd)
                            if etd_m is not None:
                                effective_dep = etd_m
                        if effective_dep < leg_cur_m - 3:
                            continue

                ref_m = leg_arr_m if leg_arr_m is not None else leg_cur_m
                if next_leg:
                    nl_dep = parse_time_to_minutes(next_leg.dep_time)
                    if nl_dep is not None:
                        ref_m = nl_dep
                time_delta = abs(leg_cur_m - ref_m)

                matching_candidates.append(
                    (
                        time_delta,
                        ActiveJourney(
                            journey_id=journey.id,
                            journey_name=journey.name,
                            from_type=journey.from_type,
                            from_id=journey.from_id,
                            from_name=journey.from_name,
                            to_type=journey.to_type,
                            to_id=journey.to_id,
                            to_name=journey.to_name,
                            itinerary=itin,
                            legs=list(itin.legs),
                            current_leg_index=(
                                next_idx if next_idx < len(itin.legs) else leg_idx
                            ),
                            current_status=status,
                            started_at=current_dt,
                            expected_arrival_time=itin.arrival_time,
                            platform=live_res.platform,
                            live_status=live_res.etd,
                            delay_minutes=live_res.delay_minutes,
                            delay_reason=live_res.delay_reason,
                        ),
                    )
                )

            # 3. En route on board transit during transit leg duration
            if (
                leg_dep_m is not None
                and leg_arr_m is not None
                and leg_dep_m <= leg_cur_m <= leg_arr_m
                and leg.mode not in FOOT_MODES
                and orig_lat is not None
                and dest_lat is not None
                and (dist_orig is None or dist_orig > max_proximity_metres)
                and (dist_dest is None or dist_dest > max_proximity_metres)
            ):
                leg_span = haversine_distance_m(orig_lat, orig_lon, dest_lat, dest_lon)
                if (
                    dist_orig is not None
                    and dist_dest is not None
                    and (dist_orig + dist_dest)
                    <= max(leg_span * 1.5, leg_span + 1000.0)
                ):
                    live_res = LiveRailStatus()
                    if leg.mode == "rail" and live_client:
                        live_res = resolve_live_rail_platform(
                            origin_id=leg.origin.id,
                            dest_id=leg.destination.id,
                            scheduled_time=leg.dep_time,
                            live_client=live_client,
                        )

                    ref_m = (leg_dep_m + leg_arr_m) / 2.0
                    time_delta = abs(leg_cur_m - ref_m)

                    matching_candidates.append(
                        (
                            time_delta,
                            ActiveJourney(
                                journey_id=journey.id,
                                journey_name=journey.name,
                                from_type=journey.from_type,
                                from_id=journey.from_id,
                                from_name=journey.from_name,
                                to_type=journey.to_type,
                                to_id=journey.to_id,
                                to_name=journey.to_name,
                                itinerary=itin,
                                legs=list(itin.legs),
                                current_leg_index=leg_idx,
                                current_status=JourneyStepStatus.ON_TRANSIT,
                                started_at=current_dt,
                                expected_arrival_time=itin.arrival_time,
                                platform=live_res.platform,
                                live_status=live_res.etd,
                                delay_minutes=live_res.delay_minutes,
                                delay_reason=live_res.delay_reason,
                            ),
                        )
                    )

            # 4. Walking to departure stop (first leg is walk, left origin corridor towards transit stop)
            if (
                leg_idx == 0
                and leg.mode in FOOT_MODES
                and orig_lat is not None
                and dest_lat is not None
            ):
                walk_dep = leg_dep_m if leg_dep_m is not None else 0
                walk_arr = leg_arr_m if leg_arr_m is not None else 1440
                next_leg = itin.legs[1] if len(itin.legs) > 1 else None
                next_dep_m = (
                    parse_time_to_minutes(next_leg.dep_time) if next_leg else None
                )
                max_walk_time = next_dep_m if next_dep_m is not None else (walk_arr + 5)
                if (walk_dep - 15) <= leg_cur_m < max_walk_time:
                    leg_span = haversine_distance_m(
                        orig_lat, orig_lon, dest_lat, dest_lon
                    )
                    if (
                        dist_orig is not None
                        and dist_dest is not None
                        and (dist_orig + dist_dest)
                        <= max(leg_span * 1.5, leg_span + 1000.0)
                    ):
                        live_res = LiveRailStatus()
                        if next_leg and next_leg.mode == "rail" and live_client:
                            live_res = resolve_live_rail_platform(
                                origin_id=next_leg.origin.id,
                                dest_id=next_leg.destination.id,
                                scheduled_time=next_leg.dep_time,
                                live_client=live_client,
                            )

                        ref_m = walk_dep
                        time_delta = abs(leg_cur_m - ref_m)

                        matching_candidates.append(
                            (
                                time_delta,
                                ActiveJourney(
                                    journey_id=journey.id,
                                    journey_name=journey.name,
                                    from_type=journey.from_type,
                                    from_id=journey.from_id,
                                    from_name=journey.from_name,
                                    to_type=journey.to_type,
                                    to_id=journey.to_id,
                                    to_name=journey.to_name,
                                    itinerary=itin,
                                    legs=list(itin.legs),
                                    current_leg_index=0,
                                    current_status=JourneyStepStatus.EN_ROUTE_TO_STOP,
                                    started_at=current_dt,
                                    expected_arrival_time=itin.arrival_time,
                                    platform=live_res.platform,
                                    live_status=live_res.etd,
                                    delay_minutes=live_res.delay_minutes,
                                    delay_reason=live_res.delay_reason,
                                ),
                            )
                        )

    if matching_candidates:
        matching_candidates.sort(key=lambda c: c[0])
        return matching_candidates[0][1]

    return None


__all__ = [
    "detect_en_route_journey",
]
