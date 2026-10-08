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
from app.services.dispatcher.tracker.service_description import format_leg_line
from app.utils.transit_time import format_minutes_to_time, parse_time_to_minutes


def _resolve_expected_arrival_time(
    active: ActiveJourney,
    current_dt: Optional[datetime.datetime] = None,
) -> str:
    """Resolve expected arrival time at the journey's final destination in HH:MM format."""
    candidate = ""
    if active.expected_arrival_time:
        candidate = active.expected_arrival_time
    elif active.itinerary and active.itinerary.arrival_time:
        candidate = active.itinerary.arrival_time
    elif active.legs:
        last_leg = active.legs[-1]
        if last_leg.arr_time:
            candidate = last_leg.arr_time

    # Calculate dynamic arrival time from current time and remaining durations
    now_m = (current_dt.hour * 60 + current_dt.minute) if current_dt else None
    projected = ""
    if now_m is not None and active.legs:
        rem_dur = sum(
            (lg.duration_minutes or 0) for lg in active.legs[active.current_leg_index :]
        )
        if rem_dur > 0:
            projected = format_minutes_to_time(now_m + rem_dur)

    if not candidate:
        return projected

    # If candidate arrival time is in the past, dynamically advance it
    if now_m is not None and candidate:
        cand_m = parse_time_to_minutes(candidate)
        if cand_m is not None and cand_m < now_m:
            if projected:
                active.expected_arrival_time = projected
                return projected
            return format_minutes_to_time(now_m + 1)

    return candidate


def _format_arrival_clause(
    to_name: str,
    expected_arr: str,
) -> str:
    """Format expected arrival line in British English."""
    if not expected_arr:
        return ""
    if to_name:
        return f"🏁 Arrive {to_name} by {expected_arr}"
    return f"🏁 Arrive by {expected_arr}"


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
    arr_str = _resolve_expected_arrival_time(active, current_dt)
    arr_clause = _format_arrival_clause(active.to_name, arr_str)

    lines = []

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

        dep_time = (
            first_transit.dep_time
            if first_transit
            else (active.itinerary.departure_time if active.itinerary else "00:00")
        )
        dep_min = parse_time_to_minutes(dep_time) or 0
        leave_min = dep_min - walk_mins
        leave_time_str = format_minutes_to_time(leave_min)

        lines.append(f"Depart by {leave_time_str} ({walk_info})")

        # Add all transit legs
        transit_legs = [lg for lg in active.legs if lg.mode not in FOOT_MODES]
        if not transit_legs and active.legs:
            # Entire journey is walking
            for lg in active.legs:
                lines.append(format_leg_line(lg))
        else:
            for i, lg in enumerate(transit_legs):
                is_first = i == 0
                plat = (
                    active.platform
                    if (is_first and lg.mode == "rail")
                    else lg.origin.platform
                )
                liv_st = active.live_status if is_first else None
                del_reas = active.delay_reason if is_first else None
                lines.append(
                    format_leg_line(
                        lg,
                        platform=plat,
                        live_status=liv_st,
                        delay_reason=del_reas,
                    )
                )

        if arr_clause:
            lines.append(arr_clause)

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
        lines.append(f"🚶 On your way to {stop_name}")

        remaining_transit = [
            lg
            for lg in active.legs[active.current_leg_index :]
            if lg.mode not in FOOT_MODES
        ]
        for i, lg in enumerate(remaining_transit):
            is_first = i == 0
            plat = (
                active.platform
                if (is_first and lg.mode == "rail")
                else lg.origin.platform
            )
            liv_st = active.live_status if is_first else None
            del_reas = active.delay_reason if is_first else None
            lines.append(
                format_leg_line(
                    lg,
                    platform=plat,
                    live_status=liv_st,
                    delay_reason=del_reas,
                )
            )

        if arr_clause:
            lines.append(arr_clause)

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
        stop_name = active_transit.origin.name if active_transit else "departure stop"
        lines.append(f"📍 At {stop_name}")

        if active_transit:
            plat = (
                active.platform
                if active_transit.mode == "rail"
                else active_transit.origin.platform
            )
            lines.append(
                format_leg_line(
                    active_transit,
                    platform=plat,
                    live_status=active.live_status,
                    delay_reason=active.delay_reason,
                    is_current_at_stop=True,
                )
            )

        # Show subsequent transit connections
        if active_transit:
            idx = (
                active.legs.index(active_transit)
                if active_transit in active.legs
                else active.current_leg_index
            )
            subsequent_transit = [
                lg for lg in active.legs[idx + 1 :] if lg.mode not in FOOT_MODES
            ]
            for lg in subsequent_transit:
                lines.append(format_leg_line(lg, platform=lg.origin.platform))

        if arr_clause:
            lines.append(arr_clause)

    elif status == JourneyStepStatus.ON_TRANSIT:
        if current_leg:
            plat = (
                active.platform
                if current_leg.mode == "rail"
                else current_leg.origin.platform
            )
            lines.append(
                format_leg_line(
                    current_leg,
                    platform=plat,
                    live_status=active.live_status,
                    delay_reason=active.delay_reason,
                    is_current_on_transit=True,
                )
            )
            # Show subsequent transit connections
            subsequent_transit = [
                lg
                for lg in active.legs[active.current_leg_index + 1 :]
                if lg.mode not in FOOT_MODES
            ]
            for lg in subsequent_transit:
                lines.append(format_leg_line(lg, platform=lg.origin.platform))
        else:
            lines.append(f"In transit towards {active.to_name}")

        if arr_clause:
            lines.append(arr_clause)

    elif status == JourneyStepStatus.AT_INTERCHANGE:
        interchange_name = current_leg.origin.name if current_leg else "Interchange"
        lines.append(f"📍 At {interchange_name}")

        next_transit = (
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
        if next_transit:
            plat = active.platform or next_transit.origin.platform
            lines.append(
                format_leg_line(
                    next_transit,
                    platform=plat,
                    live_status=(
                        active.live_status if next_transit.mode == "rail" else None
                    ),
                    delay_reason=(
                        active.delay_reason if next_transit.mode == "rail" else None
                    ),
                    is_current_at_stop=True,
                )
            )
            idx = (
                active.legs.index(next_transit)
                if next_transit in active.legs
                else active.current_leg_index
            )
            subsequent_transit = [
                lg for lg in active.legs[idx + 1 :] if lg.mode not in FOOT_MODES
            ]
            for lg in subsequent_transit:
                lines.append(format_leg_line(lg, platform=lg.origin.platform))
        elif current_leg and current_leg.mode in FOOT_MODES:
            lines.append(format_leg_line(current_leg))

        if arr_clause:
            lines.append(arr_clause)

    elif status == JourneyStepStatus.EN_ROUTE_TO_DESTINATION:
        arr_final = arr_str or (
            format_minutes_to_time(
                current_dt.hour * 60
                + current_dt.minute
                + (current_leg.duration_minutes or 0)
            )
            if current_dt and current_leg and current_leg.duration_minutes
            else ""
        )
        arr_part = f" • ETA {arr_final}" if arr_final else ""
        lines.append(f"🏁 Final leg: Walk to {active.to_name}{arr_part}")

    elif status == JourneyStepStatus.ARRIVED:
        arr_time = (
            current_dt.strftime("%H:%M")
            if current_dt
            else (arr_str or datetime.datetime.now().strftime("%H:%M"))
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
                parse_time_to_minutes(arr_str) // 60
                if arr_str and parse_time_to_minutes(arr_str) is not None
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

        lines.append(
            f"Journey complete: Arrived at {active.to_name} ({arr_time}). {greeting}"
        )

    else:
        lines.append(f"Journey update: en route to {active.to_name}")
        if arr_clause:
            lines.append(arr_clause)

    message = "\n".join(lines).strip()

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
        "alert_once": False,
        "importance": "high",
        "priority": "high",
        "channel": "Travel Assistant",
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
    "_format_arrival_clause",
    "_resolve_expected_arrival_time",
    "format_progress_notification",
]
