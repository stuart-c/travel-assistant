"""Leg advancement, future leg bypassing, and current leg stage transitions."""

import datetime
import logging
from typing import Any, Dict, Optional

from app.datasources.train_live import TrainLiveClient
from app.services.dispatcher.proximity import is_person_near_origin
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
from app.services.planner.models import ItineraryEndpoint
from app.utils.geo import (
    distance_to_polyline_m,
    haversine_distance_m,
    resolve_endpoint_coordinates,
)
from app.utils.transit_time import format_minutes_to_time, parse_time_to_minutes

logger = logging.getLogger(__name__)


def _is_commuter_at_distinct_origin(
    active: ActiveJourney,
    person_state: Optional[Dict[str, Any]],
    max_proximity_metres: float = 200.0,
) -> bool:
    """Check if commuter is at a distinct origin location separate from transit departure stop."""
    if not person_state:
        return False

    if not is_person_near_origin(
        person_state=person_state,
        from_type=active.from_type,
        from_id=active.from_id,
        max_distance_metres=max_proximity_metres,
    ):
        return False

    # If the first leg is transit and starts directly at the journey origin entity,
    # the commuter at that station/stop is at the departure stop, not at home.
    if active.legs:
        first_leg = active.legs[0]
        if first_leg.mode not in FOOT_MODES:
            orig_id = (first_leg.origin.id or "").lower()
            from_id = (active.from_id or "").lower()
            if orig_id and from_id:
                clean_orig = orig_id.split(":")[-1]
                clean_from = from_id.split(":")[-1]
                if clean_orig == clean_from and active.from_type not in (
                    "ha",
                    "custom",
                ):
                    return False

    return True


def _should_revert_to_pre_departure(
    active: ActiveJourney,
    person_state: Optional[Dict[str, Any]],
    max_proximity_metres: float = 200.0,
) -> bool:
    """Evaluate whether an active journey at departure stop should revert to pre-departure."""
    if active.current_status != JourneyStepStatus.AT_DEPARTURE_STOP:
        return False
    return _is_commuter_at_distinct_origin(
        active=active,
        person_state=person_state,
        max_proximity_metres=max_proximity_metres,
    )


def _check_and_realign_rail_interchange(
    active: ActiveJourney,
    person_lat: Optional[float],
    person_lon: Optional[float],
    live_client: Optional[TrainLiveClient],
) -> bool:
    """Detect if commuter bypassed a planned rail interchange for another station along the corridor."""
    if person_lat is None or person_lon is None:
        return False
    if active.current_leg_index >= len(active.legs) - 1:
        return False

    curr_leg = active.legs[active.current_leg_index]
    next_leg = active.legs[active.current_leg_index + 1]

    if curr_leg.mode != "rail" or next_leg.mode != "rail":
        return False

    try:
        from app.models.transit import Stop
        from app.services.planner.transfers import resolve_stop_id_aliases

        # Find nearby rail stations within 400m
        nearby_stations = list(
            Stop.select().where(
                (Stop.latitude.is_null(False))
                & (Stop.latitude >= person_lat - 0.004)
                & (Stop.latitude <= person_lat + 0.004)
                & (Stop.longitude >= person_lon - 0.006)
                & (Stop.longitude <= person_lon + 0.006)
                & (Stop.stop_type == "rail")
            )
        )
        if not nearby_stations:
            return False

        nearby_stations.sort(
            key=lambda s: haversine_distance_m(
                person_lat,
                person_lon,
                float(s.latitude or 0.0),
                float(s.longitude or 0.0),
            )
        )
        st = nearby_stations[0]
        dist = haversine_distance_m(
            person_lat,
            person_lon,
            float(st.latitude or 0.0),
            float(st.longitude or 0.0),
        )
        if dist > 400.0:
            return False

        st_aliases = resolve_stop_id_aliases(st.atco_code, st.name)
        curr_dest_aliases = resolve_stop_id_aliases(
            curr_leg.destination.id, curr_leg.destination.name
        )

        if st_aliases & curr_dest_aliases:
            return False

        curr_orig_aliases = resolve_stop_id_aliases(
            curr_leg.origin.id, curr_leg.origin.name
        )
        if st_aliases & curr_orig_aliases:
            return False

        logger.info(
            "Realigning rail interchange from %s to nearby station %s (%s)",
            curr_leg.destination.name,
            st.name,
            st.atco_code,
        )
        curr_leg.destination = ItineraryEndpoint(id=st.atco_code, name=st.name)
        next_leg.origin = ItineraryEndpoint(id=st.atco_code, name=st.name)
        return True
    except Exception as exc:
        logger.debug("Rail interchange check failed: %s", exc)
        return False


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
    _check_and_realign_rail_interchange(active, person_lat, person_lon, live_client)
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

        f_prox_orig = max_proximity_metres
        f_prox_dest = max_proximity_metres
        if f_leg.mode == "rail":
            f_prox_orig = max(max_proximity_metres, 400.0)
            f_prox_dest = max(max_proximity_metres, 400.0)
        else:
            if f_idx > 0 and active.legs[f_idx - 1].mode == "rail":
                f_prox_orig = max(max_proximity_metres, 400.0)
            if f_idx + 1 < len(active.legs) and active.legs[f_idx + 1].mode == "rail":
                f_prox_dest = max(max_proximity_metres, 400.0)

        # 1. At the destination of future leg
        if f_dist_dest is not None and f_dist_dest <= f_prox_dest:
            active.current_leg_index = f_idx + 1
            if active.current_leg_index >= len(active.legs):
                active.current_status = JourneyStepStatus.ARRIVED
                active.expected_arrival_time = current_dt.strftime("%H:%M")
            else:
                active.current_status = _determine_transit_arrival_status(active)
            _realign_active_journey_timings(active, current_dt, live_client)
            return True

        # 2. At the origin of future leg
        if f_dist_orig is not None and f_dist_orig <= f_prox_orig:
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

            f_poly = getattr(f_leg, "polyline", None)
            min_f_dep_dist = (
                max(f_prox_orig * 1.5, 300.0) if f_leg.mode == "bus" else f_prox_orig
            )
            if f_poly:
                poly_dist = distance_to_polyline_m(person_lat, person_lon, f_poly)
                corridor_buf = (
                    min(f_prox_dest, 150.0)
                    if f_leg.mode == "bus"
                    else max(f_prox_dest, 1000.0)
                )
                is_between = (
                    poly_dist is not None
                    and poly_dist <= corridor_buf
                    and f_dist_orig > min_f_dep_dist
                    and f_dist_dest < (span + f_prox_dest)
                )
            else:
                max_dev = min(
                    max(span * 0.2, 1000.0 if f_leg.mode == "bus" else 3000.0), 8000.0
                )
                is_between = (
                    f_dist_dest < (span + f_prox_dest)
                    and f_dist_orig > min_f_dep_dist
                    and (f_dist_orig + f_dist_dest) <= (span + max_dev)
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
            f_poly = getattr(f_leg, "polyline", None)
            if f_poly:
                poly_dist = distance_to_polyline_m(person_lat, person_lon, f_poly)
                is_between = (
                    poly_dist is not None
                    and poly_dist <= max(f_prox_dest, 300.0)
                    and f_dist_orig > f_prox_orig
                    and f_dist_dest < (span + f_prox_dest)
                )
            else:
                max_dev = min(max(span * 0.2, 500.0), 1000.0)
                is_between = (
                    f_dist_dest < (span + f_prox_dest)
                    and f_dist_orig > f_prox_orig
                    and (f_dist_orig + f_dist_dest) <= (span + max_dev)
                )
            if is_between:
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
    person_state: Optional[Dict[str, Any]] = None,
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

    curr_prox_orig = max_proximity_metres
    curr_prox_dest = max_proximity_metres
    if leg.mode == "rail":
        curr_prox_orig = max(max_proximity_metres, 400.0)
        curr_prox_dest = max(max_proximity_metres, 400.0)
    else:
        if (
            active.current_leg_index > 0
            and active.legs[active.current_leg_index - 1].mode == "rail"
        ):
            curr_prox_orig = max(max_proximity_metres, 400.0)
        if (
            active.current_leg_index + 1 < len(active.legs)
            and active.legs[active.current_leg_index + 1].mode == "rail"
        ):
            curr_prox_dest = max(max_proximity_metres, 400.0)

    # Check if commuter at departure stop returned to origin
    if _should_revert_to_pre_departure(
        active=active,
        person_state=person_state,
        max_proximity_metres=curr_prox_orig,
    ):
        active.current_status = JourneyStepStatus.PRE_DEPARTURE
        if (
            active.current_leg_index == 1
            and active.legs
            and active.legs[0].mode in FOOT_MODES
        ):
            active.current_leg_index = 0
        return True

    dep_min = parse_time_to_minutes(leg.dep_time)

    if leg.mode in FOOT_MODES:
        if active.current_leg_index == 0:
            # First walking leg (origin -> departure stop)
            is_at_origin = _is_commuter_at_distinct_origin(
                active=active,
                person_state=person_state,
                max_proximity_metres=curr_prox_orig,
            )
            if is_at_origin or (
                dist_to_orig is not None and dist_to_orig <= curr_prox_orig
            ):
                active.current_status = JourneyStepStatus.PRE_DEPARTURE
            elif dist_to_dest is not None and dist_to_dest <= curr_prox_dest:
                active.current_leg_index += 1
                active.current_status = JourneyStepStatus.AT_DEPARTURE_STOP
            else:
                leg_dist = (
                    haversine_distance_m(orig_lat, orig_lon, dest_lat, dest_lon)
                    if (orig_lat is not None and dest_lat is not None)
                    else 1000.0
                )
                max_allowed = max(leg_dist * 1.5, leg_dist + curr_prox_dest, 500.0)
                if dist_to_dest is not None and dist_to_dest <= max_allowed:
                    active.current_status = JourneyStepStatus.EN_ROUTE_TO_STOP
                elif dist_to_dest is None:
                    # Missing coordinates or temporary GPS drop: preserve status rather than expiring
                    active.current_status = (
                        old_status
                        if old_status != JourneyStepStatus.EXPIRED
                        else JourneyStepStatus.EN_ROUTE_TO_STOP
                    )
                else:
                    active.current_status = JourneyStepStatus.EXPIRED
                    return False
        else:
            # Egress or intermediate walking transfer
            if active.current_leg_index == len(active.legs) - 1:
                # Final walking egress
                if dist_to_dest is not None and dist_to_dest <= curr_prox_dest:
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
                if dist_to_dest is not None and dist_to_dest <= curr_prox_dest:
                    active.current_leg_index += 1
                    active.current_status = _determine_transit_arrival_status(active)
                    _realign_active_journey_timings(active, current_dt, live_client)
                else:
                    active.current_status = JourneyStepStatus.AT_INTERCHANGE
    else:
        # Transit leg (rail, bus, metro, tram)
        is_at_origin = _is_commuter_at_distinct_origin(
            active=active,
            person_state=person_state,
            max_proximity_metres=curr_prox_orig,
        )
        if is_at_origin and (
            active.current_leg_index == 0
            or (active.current_leg_index == 1 and active.legs[0].mode in FOOT_MODES)
        ):
            active.current_status = JourneyStepStatus.PRE_DEPARTURE
            if active.current_leg_index == 1:
                active.current_leg_index = 0
        elif dist_to_orig is not None and dist_to_orig <= curr_prox_orig:
            if active.current_leg_index == 0 or (
                active.current_leg_index == 1 and active.legs[0].mode in FOOT_MODES
            ):
                active.current_status = JourneyStepStatus.AT_DEPARTURE_STOP
            else:
                active.current_status = JourneyStepStatus.AT_INTERCHANGE
        elif dist_to_dest is not None and dist_to_dest <= curr_prox_dest:
            active.current_leg_index += 1
            active.current_status = _determine_transit_arrival_status(active)
            _realign_active_journey_timings(active, current_dt, live_client)
        elif old_status == JourneyStepStatus.ON_TRANSIT:
            # Maintain ON_TRANSIT status if commuter was already moving along the leg
            active.current_status = JourneyStepStatus.ON_TRANSIT
        elif (
            dep_min is not None
            and current_minutes >= dep_min
            and (
                dist_to_orig is None
                or dist_to_orig
                > (
                    max(curr_prox_orig * 1.5, 300.0)
                    if leg.mode == "bus"
                    else curr_prox_orig
                )
            )
        ):
            active.current_status = JourneyStepStatus.ON_TRANSIT
        else:
            # Commuter is before departure time and not yet detected on transit
            span = (
                haversine_distance_m(orig_lat, orig_lon, dest_lat, dest_lon)
                if (orig_lat is not None and dest_lat is not None)
                else None
            )
            # Check if commuter has departed and is en route along the transit corridor
            is_on_way = False
            if (
                span
                and dist_to_dest is not None
                and dist_to_orig is not None
                and person_lat is not None
                and person_lon is not None
            ):
                min_dep_dist = (
                    max(curr_prox_orig * 1.5, 300.0)
                    if leg.mode == "bus"
                    else curr_prox_orig
                )
                leg_poly = getattr(leg, "polyline", None)
                if leg_poly:
                    poly_dist = distance_to_polyline_m(person_lat, person_lon, leg_poly)
                    corridor_buf = (
                        min(curr_prox_dest, 150.0)
                        if leg.mode == "bus"
                        else max(curr_prox_dest, 1000.0)
                    )
                    is_on_way = (
                        poly_dist is not None
                        and poly_dist <= corridor_buf
                        and dist_to_dest < (span + curr_prox_dest)
                        and dist_to_orig > min_dep_dist
                    )
                else:
                    max_dev = min(
                        max(span * 0.2, 1000.0 if leg.mode == "bus" else 3000.0),
                        8000.0,
                    )
                    is_on_way = (
                        dist_to_dest < (span + curr_prox_dest)
                        and dist_to_orig > min_dep_dist
                        and (dist_to_orig + dist_to_dest) <= (span + max_dev)
                    )

            if is_on_way:
                active.current_status = JourneyStepStatus.ON_TRANSIT
            elif active.current_leg_index == 0 or (
                active.current_leg_index == 1 and active.legs[0].mode in FOOT_MODES
            ):
                if is_at_origin:
                    active.current_status = JourneyStepStatus.PRE_DEPARTURE
                    if active.current_leg_index == 1:
                        active.current_leg_index = 0
                else:
                    active.current_status = JourneyStepStatus.AT_DEPARTURE_STOP
            else:
                active.current_status = JourneyStepStatus.AT_INTERCHANGE

    return True


__all__ = [
    "_advance_current_leg",
    "_advance_future_legs",
    "_should_revert_to_pre_departure",
]
