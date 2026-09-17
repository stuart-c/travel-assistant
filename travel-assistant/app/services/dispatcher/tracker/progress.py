"""Journey progression tracking, state transitions, and notification dispatch."""

import datetime
import logging
from typing import Any, Dict, Optional, Set, Tuple

from app.datasources.homeassistant import HomeAssistantClient
from app.datasources.train_live import TrainLiveClient
from app.services.dispatcher.proximity import is_person_near_origin
import app.services.dispatcher.tracker as tracker_pkg
from app.services.dispatcher.tracker.leg_advancer import (
    _advance_current_leg,
    _advance_future_legs,
)
from app.services.dispatcher.tracker.models import (
    FOOT_MODES,
    ActiveJourney,
    JourneyStepStatus,
)
from app.services.dispatcher.tracker.pre_departure import (
    _handle_pre_departure_rollover,
)
from app.services.dispatcher.tracker.schedule_aligner import (
    _realign_active_journey_timings,
)
from app.services.dispatcher.tracker.significance import (
    is_significant_progress_update,
)
from app.utils.transit_time import parse_time_to_minutes

logger = logging.getLogger(__name__)


def _check_journey_expired(active: ActiveJourney, current_minutes: int) -> bool:
    """Check whether journey has expired (90 minutes past expected arrival)."""
    arr_minutes = parse_time_to_minutes(active.expected_arrival_time)
    if arr_minutes is not None and current_minutes > arr_minutes + 90:
        active.current_status = JourneyStepStatus.EXPIRED
        return True
    return False


def _check_destination_arrival(
    active: ActiveJourney,
    person_state: Dict[str, Any],
    current_dt: datetime.datetime,
    ha_client: HomeAssistantClient,
    max_proximity_metres: float,
    target_notify_service: str,
) -> Tuple[bool, bool]:
    """Check if Stuart arrived at final destination once journey has begun.

    Returns (is_arrived, notification_dispatched).
    """
    if active.current_status == JourneyStepStatus.PRE_DEPARTURE:
        return False, False

    is_at_final_dest = is_person_near_origin(
        person_state=person_state,
        from_type=active.to_type,
        from_id=active.to_id,
        max_distance_metres=max_proximity_metres,
    )
    if not is_at_final_dest:
        return False, False

    if active.current_status != JourneyStepStatus.ARRIVED:
        active.current_status = JourneyStepStatus.ARRIVED
        active.expected_arrival_time = current_dt.strftime("%H:%M")
        title, msg, data = tracker_pkg.format_progress_notification(
            active, current_dt=current_dt
        )
        try:
            ha_client.send_mobile_notification(
                title=title,
                message=msg,
                service_name=target_notify_service,
                data=data,
            )
            active.last_notification_message = msg
            active.last_notification_time = current_dt
            active.last_notified_status = active.current_status
            active.last_notified_platform = active.platform
            active.last_notified_delay_minutes = active.delay_minutes
            logger.info(
                "Dispatched journey arrival notification for journey %d (%s): %s",
                active.journey_id,
                active.journey_name,
                msg,
            )
            return True, True
        except Exception as exc:
            active.last_notification_time = current_dt
            logger.error(
                "Failed to send arrival notification for journey %d: %s",
                active.journey_id,
                exc,
            )
            return True, False

    return True, False


def _refresh_live_platform_status(
    active: ActiveJourney,
    live_client: Optional[TrainLiveClient],
) -> None:
    """Check Darwin for live platform announcements or delays."""
    current_leg = (
        active.legs[active.current_leg_index]
        if active.current_leg_index < len(active.legs)
        else None
    )
    target_rail_leg = None
    if current_leg and current_leg.mode == "rail":
        target_rail_leg = current_leg
    else:
        target_rail_leg = next(
            (lg for lg in active.legs[active.current_leg_index :] if lg.mode == "rail"),
            None,
        )

    if target_rail_leg and live_client:
        live_res = tracker_pkg.resolve_live_rail_platform(
            origin_id=target_rail_leg.origin.id,
            dest_id=target_rail_leg.destination.id,
            scheduled_time=target_rail_leg.dep_time,
            live_client=live_client,
        )
        if live_res.platform:
            target_rail_leg.origin.platform = live_res.platform
            if (
                current_leg
                and (current_leg.mode == "rail" or current_leg.mode in FOOT_MODES)
                and live_res.platform != active.platform
            ):
                active.platform = live_res.platform
        if live_res.etd:
            if current_leg and (
                current_leg.mode == "rail" or current_leg.mode in FOOT_MODES
            ):
                active.live_status = live_res.etd
                active.delay_minutes = live_res.delay_minutes
                active.delay_reason = live_res.delay_reason
    elif (
        current_leg
        and current_leg.mode not in FOOT_MODES
        and current_leg.mode != "rail"
    ):
        active.live_status = None
        active.delay_minutes = 0
        active.delay_reason = None
        if active.platform and not any(
            w in active.platform.lower() for w in ("stand", "stop")
        ):
            active.platform = None


def update_journey_progress(
    active: ActiveJourney,
    person_state: Optional[Dict[str, Any]],
    current_dt: datetime.datetime,
    ha_client: HomeAssistantClient,
    live_client: Optional[TrainLiveClient] = None,
    max_proximity_metres: float = 200.0,
    sent_keys: Optional[Set[str]] = None,
    target_notify_service: str = "mobile_app_stuart_mobile",
) -> bool:
    """Evaluate Stuart's location against journey stages and dispatch notification updates.

    Returns True if a notification update was dispatched, False otherwise.
    """
    if not person_state or not isinstance(person_state, dict):
        return False

    current_minutes = current_dt.hour * 60 + current_dt.minute

    # 1. Realign upcoming transit legs if connecting departure times have elapsed
    _realign_active_journey_timings(active, current_dt, live_client)

    # 2. Check journey expiration timeout (90 minutes past expected arrival)
    if _check_journey_expired(active, current_minutes):
        return False

    # 3. Check if Stuart missed departure time while still in PRE_DEPARTURE
    handled, dispatched = _handle_pre_departure_rollover(
        active=active,
        person_state=person_state,
        current_dt=current_dt,
        ha_client=ha_client,
        live_client=live_client,
        max_proximity_metres=max_proximity_metres,
        sent_keys=sent_keys,
        target_notify_service=target_notify_service,
    )
    if handled:
        return dispatched

    # 4. Check if Stuart has arrived at the final destination
    arrived, dispatched = _check_destination_arrival(
        active=active,
        person_state=person_state,
        current_dt=current_dt,
        ha_client=ha_client,
        max_proximity_metres=max_proximity_metres,
        target_notify_service=target_notify_service,
    )
    if arrived:
        return dispatched

    # 5. Extract GPS coordinates
    attrs = person_state.get("attributes", {}) or {}
    raw_lat = attrs.get("latitude")
    raw_lon = attrs.get("longitude")
    person_lat = float(raw_lat) if raw_lat is not None else None
    person_lon = float(raw_lon) if raw_lon is not None else None

    # Track pre-update state for significance evaluation
    old_status = active.current_status
    old_leg_idx = active.current_leg_index
    old_platform = active.platform
    old_delay = active.delay_minutes
    old_live_status = active.live_status

    # 6. Step through leg progression
    if active.current_leg_index >= len(active.legs):
        active.current_status = JourneyStepStatus.EN_ROUTE_TO_DESTINATION
    else:
        advanced_to_future = False
        is_still_near_origin = (
            active.current_status == JourneyStepStatus.PRE_DEPARTURE
            and is_person_near_origin(person_state, active.from_type, active.from_id)
        )

        if (
            not is_still_near_origin
            and person_lat is not None
            and person_lon is not None
            and active.current_leg_index < len(active.legs) - 1
        ):
            advanced_to_future = _advance_future_legs(
                active=active,
                person_lat=person_lat,
                person_lon=person_lon,
                current_minutes=current_minutes,
                current_dt=current_dt,
                live_client=live_client,
                max_proximity_metres=max_proximity_metres,
            )

        if not advanced_to_future and active.current_leg_index < len(active.legs):
            is_valid = _advance_current_leg(
                active=active,
                person_lat=person_lat,
                person_lon=person_lon,
                current_minutes=current_minutes,
                current_dt=current_dt,
                live_client=live_client,
                max_proximity_metres=max_proximity_metres,
                old_status=old_status,
            )
            if not is_valid:
                return False

    # 7. Check for live platform update if rail leg or transferring to rail leg
    _refresh_live_platform_status(active, live_client)

    # 8. Notification formatting and debouncing
    title, new_msg, data = tracker_pkg.format_progress_notification(
        active, current_dt=current_dt, live_client=live_client
    )

    is_significant = is_significant_progress_update(
        active=active,
        old_status=old_status,
        old_leg_idx=old_leg_idx,
        old_platform=old_platform,
        old_delay=old_delay,
        old_live_status=old_live_status,
    )

    should_send = False
    if is_significant:
        should_send = (
            active.current_status != old_status
            or active.current_leg_index != old_leg_idx
            or new_msg != active.last_notification_message
        )
    elif new_msg != active.last_notification_message:
        # Low priority / minor telemetry update: apply 120-second (2-minute) cooldown
        if active.last_notification_time is None:
            should_send = True
        else:
            elapsed_seconds = (
                current_dt - active.last_notification_time
            ).total_seconds()
            if elapsed_seconds >= 120.0:
                should_send = True
            else:
                logger.debug(
                    "Suppressing minor progress update for journey %d (%s) due to active cooldown (%.1fs < 120s): %s",
                    active.journey_id,
                    active.journey_name,
                    elapsed_seconds,
                    new_msg,
                )

    if should_send:
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
            logger.info(
                "Updated journey progress notification for journey %d (%s) [%s]: %s",
                active.journey_id,
                active.journey_name,
                active.current_status.value,
                new_msg,
            )
            return True
        except Exception as exc:
            active.last_notification_time = current_dt
            logger.error(
                "Failed to send progress notification update for journey %d: %s",
                active.journey_id,
                exc,
            )
            return False

    return False


__all__ = [
    "update_journey_progress",
]
