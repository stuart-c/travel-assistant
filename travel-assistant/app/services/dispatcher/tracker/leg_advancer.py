"""Leg advancement, future leg bypassing, and current leg stage transitions."""

import datetime
import logging
from typing import Optional

from app.datasources.train_live import TrainLiveClient
from app.services.dispatcher.tracker.models import (
    FOOT_MODES,
    ActiveJourney,
    JourneyStepStatus,
)
from app.services.dispatcher.tracker.schedule_aligner import (
    _realign_active_journey_timings,
)
from app.services.dispatcher.tracker.significance import (
    _determine_transit_arrival_status,
)
from app.utils.geo import haversine_distance_m, resolve_endpoint_coordinates
from app.utils.transit_time import format_minutes_to_time, parse_time_to_minutes

logger = logging.getLogger(__name__)


def _advance_future_legs(
    active: ActiveJourney,
    person_lat: float,
    person_lon: float,
    current_minutes: int,
    current_dt: datetime.datetime,
    live_client: Optional[TrainLiveClient],
    max_proximity_metres: float,
) -> bool:
    """Scan subsequent legs backwards to detect if Stuart bypassed or moved ahead.

    Returns True if an advancement to a future leg was made.
    """
    for f_idx in range(len(active.legs) - 1, active.current_leg_index, -1):
        f_leg = active.legs[f_idx]
        f_orig_lat, f_orig_lon, _ = resolve_endpoint_coordinates(
            f_leg.mode, f_leg.origin.id
        )
        f_dest_lat, f_dest_lon, _ = resolve_endpoint_coordinates(
            f_leg.mode, f_leg.destination.id
        )

        f_dist_orig = (
            haversine_distance_m(person_lat, person_lon, f_orig_lat, f_orig_lon)
            if (f_orig_lat is not None and f_orig_lon is not None)
            else None
        )
        f_dist_dest = (
            haversine_distance_m(person_lat, person_lon, f_dest_lat, f_dest_lon)
            if (f_dest_lat is not None and f_dest_lon is not None)
            else None
        )

        # 1. At the destination of future leg
        if f_dist_dest is not None and f_dist_dest <= max_proximity_metres:
            active.current_leg_index = f_idx + 1
            if active.current_leg_index >= len(active.legs):
                active.current_status = JourneyStepStatus.ARRIVED
                active.expected_arrival_time = current_dt.strftime("%H:%M")
            else:
                active.current_status = _determine_transit_arrival_status(active)
            _realign_active_journey_timings(active, current_dt, live_client)
            return True

        # 2. At the origin of future leg
        if f_dist_orig is not None and f_dist_orig <= max_proximity_metres:
            active.current_leg_index = f_idx
            if f_idx == 0 or (f_idx == 1 and active.legs[0].mode in FOOT_MODES):
                active.current_status = JourneyStepStatus.AT_DEPARTURE_STOP
            elif f_idx == len(active.legs) - 1 and f_leg.mode in FOOT_MODES:
                active.current_status = JourneyStepStatus.EN_ROUTE_TO_DESTINATION
            else:
                active.current_status = JourneyStepStatus.AT_INTERCHANGE
            _realign_active_journey_timings(active, current_dt, live_client)
            return True

        # 3. En route on board a future transit leg corridor
        if (
            f_leg.mode not in FOOT_MODES
            and f_orig_lat is not None
            and f_dest_lat is not None
            and f_dist_orig is not None
            and f_dist_dest is not None
        ):
            span = haversine_distance_m(f_orig_lat, f_orig_lon, f_dest_lat, f_dest_lon)
            f_dep_m = parse_time_to_minutes(f_leg.dep_time)
            cur_eff = (
                current_minutes + 1440
                if (f_dep_m is not None and current_minutes < 120 and f_dep_m > 1200)
                else current_minutes
            )
            is_time_valid = f_dep_m is None or cur_eff >= (f_dep_m - 2)
            is_between = (
                f_dist_dest < (span + max_proximity_metres)
                and f_dist_orig > max_proximity_metres
                and (f_dist_orig + f_dist_dest) <= max(span * 1.5, span + 1000.0)
            )
            if is_time_valid and is_between:
                active.current_leg_index = f_idx
                active.current_status = JourneyStepStatus.ON_TRANSIT
                return True

        # 4. En route on final walking leg corridor
        if (
            f_idx == len(active.legs) - 1
            and f_leg.mode in FOOT_MODES
            and f_orig_lat is not None
            and f_dest_lat is not None
            and f_dist_orig is not None
            and f_dist_dest is not None
        ):
            span = haversine_distance_m(f_orig_lat, f_orig_lon, f_dest_lat, f_dest_lon)
            if (
                f_dist_dest < (span + max_proximity_metres)
                and f_dist_orig > max_proximity_metres
                and (f_dist_orig + f_dist_dest) <= max(span * 1.5, span + 1000.0)
            ):
                active.current_leg_index = f_idx
                active.current_status = JourneyStepStatus.EN_ROUTE_TO_DESTINATION
                return True

    return False


def _advance_current_leg(
    active: ActiveJourney,
    person_lat: Optional[float],
    person_lon: Optional[float],
    current_minutes: int,
    current_dt: datetime.datetime,
    live_client: Optional[TrainLiveClient],
    max_proximity_metres: float,
    old_status: JourneyStepStatus,
) -> bool:
    """Evaluate progress along the current leg.

    Returns False if Stuart wandered far away and journey expired, True otherwise.
    """
    if active.current_leg_index >= len(active.legs):
        active.current_status = JourneyStepStatus.EN_ROUTE_TO_DESTINATION
        return True

    leg = active.legs[active.current_leg_index]
    orig_lat, orig_lon, _ = resolve_endpoint_coordinates(leg.mode, leg.origin.id)
    dest_lat, dest_lon, _ = resolve_endpoint_coordinates(leg.mode, leg.destination.id)

    dist_to_orig = (
        haversine_distance_m(person_lat, person_lon, orig_lat, orig_lon)
        if (person_lat is not None and orig_lat is not None)
        else None
    )
    dist_to_dest = (
        haversine_distance_m(person_lat, person_lon, dest_lat, dest_lon)
        if (person_lat is not None and dest_lat is not None)
        else None
    )

    dep_min = parse_time_to_minutes(leg.dep_time)

    if leg.mode in FOOT_MODES:
        if active.current_leg_index == 0:
            # First walking leg (origin -> departure stop)
            if dist_to_orig is not None and dist_to_orig <= max_proximity_metres:
                active.current_status = JourneyStepStatus.PRE_DEPARTURE
            elif dist_to_dest is not None and dist_to_dest <= max_proximity_metres:
                active.current_leg_index += 1
                active.current_status = JourneyStepStatus.AT_DEPARTURE_STOP
            else:
                leg_dist = (
                    haversine_distance_m(orig_lat, orig_lon, dest_lat, dest_lon)
                    if (orig_lat is not None and dest_lat is not None)
                    else 1000.0
                )
                max_allowed = max(
                    leg_dist * 1.5, leg_dist + max_proximity_metres, 500.0
                )
                if dist_to_dest is not None and dist_to_dest <= max_allowed:
                    active.current_status = JourneyStepStatus.EN_ROUTE_TO_STOP
                else:
                    active.current_status = JourneyStepStatus.EXPIRED
                    return False
        else:
            # Egress or intermediate walking transfer
            if active.current_leg_index == len(active.legs) - 1:
                # Final walking egress
                if dist_to_dest is not None and dist_to_dest <= max_proximity_metres:
                    active.current_leg_index += 1
                    active.current_status = JourneyStepStatus.ARRIVED
                    active.expected_arrival_time = current_dt.strftime("%H:%M")
                else:
                    active.current_status = JourneyStepStatus.EN_ROUTE_TO_DESTINATION
                    walk_dur = (
                        active.legs[active.current_leg_index].duration_minutes
                        if active.current_leg_index < len(active.legs)
                        else 5
                    )
                    if (
                        not active.expected_arrival_time
                        or old_status != JourneyStepStatus.EN_ROUTE_TO_DESTINATION
                    ):
                        active.expected_arrival_time = format_minutes_to_time(
                            current_minutes + walk_dur
                        )
            else:
                # Intermediate transfer
                if dist_to_dest is not None and dist_to_dest <= max_proximity_metres:
                    active.current_leg_index += 1
                    active.current_status = _determine_transit_arrival_status(active)
                    _realign_active_journey_timings(active, current_dt, live_client)
                else:
                    active.current_status = JourneyStepStatus.AT_INTERCHANGE
    else:
        # Transit leg (rail, bus, metro, tram)
        if dist_to_orig is not None and dist_to_orig <= max_proximity_metres:
            if active.current_leg_index == 0 or (
                active.current_leg_index == 1 and active.legs[0].mode in FOOT_MODES
            ):
                active.current_status = JourneyStepStatus.AT_DEPARTURE_STOP
            else:
                active.current_status = JourneyStepStatus.AT_INTERCHANGE
        elif dep_min is not None and current_minutes >= dep_min:
            if dist_to_dest is not None and dist_to_dest <= max_proximity_metres:
                active.current_leg_index += 1
                active.current_status = _determine_transit_arrival_status(active)
                _realign_active_journey_timings(active, current_dt, live_client)
            else:
                active.current_status = JourneyStepStatus.ON_TRANSIT
        else:
            if active.current_leg_index == 0 or (
                active.current_leg_index == 1 and active.legs[0].mode in FOOT_MODES
            ):
                active.current_status = JourneyStepStatus.AT_DEPARTURE_STOP
            else:
                active.current_status = JourneyStepStatus.AT_INTERCHANGE

    return True


__all__ = [
    "_advance_current_leg",
    "_advance_future_legs",
]
