"""Pre-departure missed departure checks and candidate rollover handling."""

import datetime
import logging
from typing import Any, Dict, Optional, Set, Tuple

import app.services.dispatcher.tracker as tracker_pkg
from app.datasources.homeassistant import HomeAssistantClient
from app.datasources.train_live import TrainLiveClient
from app.models.journey import Journey
from app.services.dispatcher.proximity import is_person_near_origin
from app.services.dispatcher.tracker.models import (
    FOOT_MODES,
    ActiveJourney,
    JourneyStepStatus,
)
from app.utils.transit_time import parse_time_to_minutes

logger = logging.getLogger(__name__)


def _handle_pre_departure_rollover(
    active: ActiveJourney,
    person_state: Dict[str, Any],
    current_dt: datetime.datetime,
    ha_client: HomeAssistantClient,
    live_client: Optional[TrainLiveClient],
    max_proximity_metres: float,
    sent_keys: Optional[Set[str]],
    target_notify_service: str,
) -> Tuple[bool, bool]:
    """Check if Stuart missed departure while at origin and roll over to next candidate.

    Returns (was_handled, notification_dispatched).
    """
    if active.current_status != JourneyStepStatus.PRE_DEPARTURE:
        return False, False

    current_minutes = current_dt.hour * 60 + current_dt.minute
    first_transit = next(
        (leg for leg in active.legs if leg.mode not in FOOT_MODES), None
    )
    walk_mins = (
        active.legs[0].duration_minutes
        if (active.legs and active.legs[0].mode in FOOT_MODES)
        else 0
    )
    dep_time = (
        first_transit.dep_time
        if first_transit
        else (active.itinerary.departure_time if active.itinerary else "00:00")
    )
    dep_m = parse_time_to_minutes(dep_time)
    if dep_m is None or current_minutes <= dep_m - walk_mins + 2:
        return False, False

    # Check if Stuart is still at origin
    still_at_origin = is_person_near_origin(
        person_state=person_state,
        from_type=active.from_type,
        from_id=active.from_id,
        max_distance_metres=max_proximity_metres,
    )
    if not still_at_origin:
        return False, False

    try:
        journey = Journey.get_by_id(active.journey_id)
    except Exception:
        journey = None

    exclude_keys = set(sent_keys) if sent_keys else set()
    if first_transit and first_transit.dep_time:
        curr_key = (
            f"j{active.journey_id}_{first_transit.mode}_{first_transit.line or 'direct'}_"
            f"{first_transit.dep_time}_{current_dt.date().isoformat()}"
        )
        exclude_keys.add(curr_key)

    next_candidate = (
        tracker_pkg.find_next_departure_candidate(
            journey=journey,
            dt=current_dt,
            exclude_service_keys=exclude_keys,
            live_client=live_client,
        )
        if journey
        else None
    )

    if next_candidate:
        active.itinerary = next_candidate.itinerary
        active.legs = list(next_candidate.itinerary.legs)
        active.expected_arrival_time = next_candidate.arrival_time
        active.current_leg_index = 0
        active.platform = next_candidate.platform
        active.live_status = None

        title, new_msg, data = tracker_pkg.format_departure_notification(next_candidate)
        try:
            ha_client.send_mobile_notification(
                title=title,
                message=new_msg,
                service_name=target_notify_service,
                data=data,
            )
            active.last_notification_message = new_msg
            active.last_notification_time = current_dt
            active.last_notified_status = active.current_status
            active.last_notified_platform = active.platform
            active.last_notified_delay_minutes = active.delay_minutes
            if sent_keys is not None:
                sent_keys.add(next_candidate.service_key)
            logger.info(
                "Stuart remained at origin past leave time for journey %d (%s). "
                "Rolled over to next departure at %s: %s",
                active.journey_id,
                active.journey_name,
                next_candidate.transit_dep_time,
                new_msg,
            )
            return True, True
        except Exception as exc:
            active.last_notification_time = current_dt
            logger.error(
                "Failed to dispatch rollover departure notification for journey %d (%s): %s",
                active.journey_id,
                active.journey_name,
                exc,
            )
            return True, False
    else:
        is_active = False
        if journey:
            is_active, _ = tracker_pkg.is_journey_active_for_datetime(
                journey, current_dt
            )

        any_remaining = (
            tracker_pkg.find_next_departure_candidate(
                journey=journey,
                dt=current_dt,
                exclude_service_keys=None,
                live_client=live_client,
            )
            if journey
            else None
        )

        if not is_active or not any_remaining:
            active.current_status = JourneyStepStatus.EXPIRED
            try:
                ha_client.clear_mobile_notification(
                    tag=f"journey_{active.journey_id}",
                    service_name=target_notify_service,
                )
                logger.info(
                    "Commute window closed for journey %d (%s); no further viable departures. Cleared notification.",
                    active.journey_id,
                    active.journey_name,
                )
            except Exception as exc:
                logger.debug(
                    "Failed to clear mobile notification on expiry for journey %d: %s",
                    active.journey_id,
                    exc,
                )
            return True, False
        else:
            logger.info(
                "No new departure candidate for journey %d (%s) at %s, but commute window remains active. Retaining pre-departure tracking.",
                active.journey_id,
                active.journey_name,
                current_dt.strftime("%H:%M"),
            )
            return True, False


__all__ = [
    "_handle_pre_departure_rollover",
]
