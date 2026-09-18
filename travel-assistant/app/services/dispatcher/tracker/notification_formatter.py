"""User-facing notification message formatting for journey stages and updates."""

import datetime
import os
from typing import Any, Dict, Optional, Tuple

from app.datasources.train_live import TrainLiveClient
from app.models.setting import Setting
from app.services.dispatcher.tracker.models import (
    FOOT_MODES,
    ActiveJourney,
    ItineraryLeg,
    JourneyStepStatus,
)
from app.services.dispatcher.tracker.service_description import (
    _format_departure_timing_with_delay,
    _format_interchange_boarding_clause,
    _format_platform_label,
    _format_transit_service_desc,
    format_next_step_for_departure,
    format_next_step_for_on_transit,
)
from app.utils.transit_time import format_minutes_to_time, parse_time_to_minutes


def format_progress_notification(
    active: ActiveJourney,
    current_dt: Optional[datetime.datetime] = None,
    live_client: Optional[TrainLiveClient] = None,
) -> Tuple[str, str, Dict[str, Any]]:
    """Generate user-facing notification title and message for the current journey step."""
    title = f"Travel Alert: {active.journey_name}"
    current_leg: Optional[ItineraryLeg] = (
        active.legs[active.current_leg_index]
        if active.current_leg_index < len(active.legs)
        else None
    )

    status = active.current_status
    message = ""

    if status == JourneyStepStatus.PRE_DEPARTURE:
        first_transit = next(
            (leg for leg in active.legs if leg.mode not in FOOT_MODES), None
        )
        walk_leg = (
            active.legs[0]
            if active.legs and active.legs[0].mode in FOOT_MODES
            else None
        )
        walk_mins = walk_leg.duration_minutes if walk_leg else 0
        walk_info = f"walk {walk_mins}m" if walk_mins > 0 else "direct departure"

        transit_desc = (
            _format_transit_service_desc(
                first_transit.mode,
                first_transit.line,
                first_transit.operator,
                destination=(first_transit.destination.name if first_transit else None),
            )
            if first_transit
            else "direct departure"
        )
        dep_time = (
            first_transit.dep_time
            if first_transit
            else (active.itinerary.departure_time if active.itinerary else "00:00")
        )
        origin_name = first_transit.origin.name if first_transit else active.from_name

        dep_min = parse_time_to_minutes(dep_time) or 0
        leave_min = dep_min - walk_mins
        leave_time_str = format_minutes_to_time(leave_min)

        plat_note = f" (Platform {active.platform})" if active.platform else ""
        dep_desc = _format_departure_timing_with_delay(
            dep_time=dep_time,
            live_status=active.live_status,
            delay_reason=active.delay_reason,
        )

        next_step_info = ""
        if first_transit:
            next_step_info = format_next_step_for_departure(
                active.legs,
                first_transit,
                only_transit=True,
                live_client=live_client,
            )

        message = (
            f"Leave by {leave_time_str} ({walk_info}) for {transit_desc}{plat_note} "
            f"from {origin_name} departing at {dep_desc}.{next_step_info} "
            f"Estimated arrival at {active.to_name} by {active.expected_arrival_time}."
        )

    elif status == JourneyStepStatus.EN_ROUTE_TO_STOP:
        next_transit = next(
            (
                leg
                for leg in active.legs[active.current_leg_index :]
                if leg.mode not in FOOT_MODES
            ),
            current_leg,
        )
        stop_name = next_transit.origin.name if next_transit else "departure stop"
        line_desc = (
            _format_transit_service_desc(
                next_transit.mode,
                next_transit.line,
                next_transit.operator,
                destination=(next_transit.destination.name if next_transit else None),
            )
            if next_transit
            else "Transit"
        )
        dep_time = next_transit.dep_time if next_transit else ""
        next_step_info = (
            format_next_step_for_departure(
                active.legs,
                next_transit,
                only_transit=True,
                live_client=live_client,
            )
            if next_transit
            else ""
        )
        dep_desc = _format_departure_timing_with_delay(
            dep_time=dep_time,
            live_status=active.live_status,
            delay_reason=active.delay_reason,
        )
        plat_note = f" (Platform {active.platform})" if active.platform else ""
        message = (
            f"On your way to {stop_name}. "
            f"{line_desc}{plat_note} departs at {dep_desc}.{next_step_info} "
            f"Destination: {active.to_name}."
        )

    elif status == JourneyStepStatus.AT_DEPARTURE_STOP:
        active_transit = (
            current_leg
            if (current_leg and current_leg.mode not in FOOT_MODES)
            else next(
                (
                    lg
                    for lg in active.legs[active.current_leg_index :]
                    if lg.mode not in FOOT_MODES
                ),
                None,
            )
        )
        next_step_info = (
            format_next_step_for_departure(
                active.legs,
                active_transit,
                only_transit=False,
                live_client=live_client,
            )
            if active_transit
            else ""
        )
        if active_transit and active_transit.mode == "rail":
            plat_info = (
                f"Platform {active.platform}"
                if active.platform
                else "Platform to be announced"
            )
            dep_desc = _format_departure_timing_with_delay(
                dep_time=active_transit.dep_time,
                live_status=active.live_status,
                delay_reason=active.delay_reason,
            )
            line_desc = _format_transit_service_desc(
                active_transit.mode, active_transit.line, active_transit.operator
            )
            message = (
                f"At {active_transit.origin.name}. "
                f"{line_desc} to {active_transit.destination.name} departs at "
                f"{dep_desc} from {plat_info}.{next_step_info}"
            )
        elif active_transit:
            line_desc = _format_transit_service_desc(
                active_transit.mode, active_transit.line, active_transit.operator
            )
            plat_info = ""
            if active.platform and any(
                w in active.platform.lower() for w in ("stand", "stop")
            ):
                plat_info = f" from {active.platform}"
            dep_desc = _format_departure_timing_with_delay(
                dep_time=active_transit.dep_time,
                live_status=active.live_status,
                delay_reason=active.delay_reason,
            )
            message = (
                f"At {active_transit.origin.name}. "
                f"{line_desc} to {active_transit.destination.name} departs at {dep_desc}{plat_info}.{next_step_info}"
            )
        else:
            message = f"At departure stop for {active.to_name}."

    elif status == JourneyStepStatus.ON_TRANSIT:
        if current_leg:
            line_desc = _format_transit_service_desc(
                current_leg.mode, current_leg.line, current_leg.operator
            )
            next_step_info = format_next_step_for_on_transit(
                active.legs,
                active.current_leg_index,
                current_leg,
                live_client=live_client,
            )
            plat_note = ""
            if current_leg.mode == "rail" and active.platform:
                plat_note = f" (Platform {active.platform})"
            elif (
                current_leg.mode != "rail"
                and active.platform
                and any(w in active.platform.lower() for w in ("stand", "stop"))
            ):
                plat_note = f" ({active.platform})"

            message = (
                f"On board {line_desc}{plat_note} towards {current_leg.destination.name}. "
                f"Expected arrival at {current_leg.arr_time}.{next_step_info}"
            )
        else:
            message = f"In transit towards {active.to_name}."

    elif status == JourneyStepStatus.AT_INTERCHANGE:
        preceding_transit = (
            active.legs[active.current_leg_index - 1]
            if 0 < active.current_leg_index <= len(active.legs)
            else None
        )
        arr_plat = (
            preceding_transit.destination.platform
            if preceding_transit and preceding_transit.destination
            else None
        )

        if current_leg and current_leg.mode in FOOT_MODES:
            arr_plat = arr_plat or current_leg.origin.platform
            next_transit = next(
                (
                    lg
                    for lg in active.legs[active.current_leg_index :]
                    if lg.mode not in FOOT_MODES
                ),
                None,
            )
            if next_transit:
                transfer_desc = _format_transit_service_desc(
                    next_transit.mode,
                    next_transit.line,
                    next_transit.operator,
                    destination=next_transit.destination.name,
                )
                dep_plat = (
                    active.platform
                    or next_transit.origin.platform
                    or current_leg.destination.platform
                )
                dep_desc = _format_departure_timing_with_delay(
                    dep_time=next_transit.dep_time,
                    live_status=(
                        active.live_status if next_transit.mode == "rail" else None
                    ),
                    delay_reason=(
                        active.delay_reason if next_transit.mode == "rail" else None
                    ),
                )
                arr_label = _format_platform_label(
                    arr_plat, preceding_transit.mode if preceding_transit else "rail"
                )
                dep_label = _format_platform_label(dep_plat, next_transit.mode)
                plat_clause = _format_interchange_boarding_clause(
                    arr_label,
                    dep_label,
                    transfer_desc,
                    next_transit.mode,
                    is_walk_transfer=True,
                )
                message = (
                    f"Transfer at {current_leg.origin.name}: "
                    f"{plat_clause} departing at {dep_desc}."
                )
            else:
                message = f"Transfer at {current_leg.origin.name}: Walk to {current_leg.destination.name}."
        elif current_leg:
            line_desc = _format_transit_service_desc(
                current_leg.mode,
                current_leg.line,
                current_leg.operator,
                destination=current_leg.destination.name,
            )
            dep_plat = active.platform or current_leg.origin.platform
            dep_desc = _format_departure_timing_with_delay(
                dep_time=current_leg.dep_time,
                live_status=active.live_status if current_leg.mode == "rail" else None,
                delay_reason=(
                    active.delay_reason if current_leg.mode == "rail" else None
                ),
            )
            arr_label = _format_platform_label(
                arr_plat, preceding_transit.mode if preceding_transit else "rail"
            )
            dep_label = _format_platform_label(dep_plat, current_leg.mode)
            plat_clause = _format_interchange_boarding_clause(
                arr_label,
                dep_label,
                line_desc,
                current_leg.mode,
                is_walk_transfer=False,
            )
            message = (
                f"Transfer at {current_leg.origin.name}: "
                f"{plat_clause} departing at {dep_desc}."
            )
        else:
            message = "Interchange stop: transfer to connecting service."

    elif status == JourneyStepStatus.EN_ROUTE_TO_DESTINATION:
        arr_str = active.expected_arrival_time
        if not arr_str and current_dt and current_leg and current_leg.duration_minutes:
            now_m = current_dt.hour * 60 + current_dt.minute
            arr_str = format_minutes_to_time(now_m + current_leg.duration_minutes)
        message = (
            f"Final leg: Walk to {active.to_name}. Estimated arrival at {arr_str}."
        )

    elif status == JourneyStepStatus.ARRIVED:
        arr_time = (
            current_dt.strftime("%H:%M")
            if current_dt
            else (
                active.expected_arrival_time
                or datetime.datetime.now().strftime("%H:%M")
            )
        )
        is_home = (
            "home" in active.to_name.lower()
            or "home" in active.to_id.lower()
            or "home" in active.journey_name.lower()
        )
        now_hour = (
            current_dt.hour
            if current_dt
            else (
                parse_time_to_minutes(active.expected_arrival_time) // 60
                if active.expected_arrival_time
                and parse_time_to_minutes(active.expected_arrival_time) is not None
                else datetime.datetime.now().hour
            )
        )
        if is_home and now_hour >= 17:
            greeting = "Welcome home! Have a pleasant evening."
        elif is_home:
            greeting = "Welcome home!"
        elif now_hour >= 17:
            greeting = "Have a pleasant evening!"
        else:
            greeting = "Have a great day!"

        message = (
            f"Journey complete: Arrived at {active.to_name} ({arr_time}). {greeting}"
        )

    else:
        message = f"Journey update: en route to {active.to_name}."

    panel_slug = (
        Setting.get_val(
            "ingress_panel_slug",
            os.environ.get("ADDON_PANEL_PATH", ""),
        )
        or ""
    ).strip("/")
    base_path = f"/{panel_slug}" if panel_slug else ""
    nav_url = f"{base_path}/journey?journey_id={active.journey_id}"

    is_persistent = status != JourneyStepStatus.ARRIVED

    data: Dict[str, Any] = {
        "url": nav_url,
        "clickAction": nav_url,
        "tag": f"journey_{active.journey_id}",
        "group": "travel_assistant_journeys",
        "persistent": is_persistent,
        "sticky": is_persistent,
        "actions": [
            {
                "action": "URI",
                "title": "View Journey Plan",
                "uri": nav_url,
            }
        ],
    }

    return title, message, data


__all__ = [
    "format_progress_notification",
]
