"""Transit service description and departure timing text formatters."""

import re
from typing import List, Optional

from app.datasources.train_live import TrainLiveClient
from app.services.dispatcher.tracker.models import (
    FOOT_MODES,
    ItineraryLeg,
)
from app.services.dispatcher.tracker.platform_service import (
    resolve_live_rail_arrival_platform,
    resolve_live_rail_platform,
)


def _format_platform_label(plat: Optional[str], mode: str) -> Optional[str]:
    """Format a platform or stand label in British English."""
    if not plat:
        return None
    plat_str = str(plat).strip()
    if not plat_str:
        return None
    if mode == "rail":
        if "platform" not in plat_str.lower():
            return f"Platform {plat_str}"
        return plat_str
    if any(w in plat_str.lower() for w in ("stand", "stop", "bay")):
        return plat_str
    return None


def _format_upcoming_change_platforms(
    arr_plat: Optional[str],
    dep_plat: Optional[str],
    arr_mode: str = "rail",
    dep_mode: str = "rail",
) -> str:
    """Format platform transfer details between arriving and departing services."""
    arr_label = _format_platform_label(arr_plat, arr_mode)
    dep_label = _format_platform_label(dep_plat, dep_mode)

    if arr_label and dep_label:
        return f"arrive {arr_label}, depart {dep_label}"
    elif arr_label and not dep_label:
        unannounced = (
            "Platform to be announced"
            if dep_mode == "rail"
            else "stand to be announced"
        )
        return f"arrive {arr_label}, depart {unannounced}"
    elif not arr_label and dep_label:
        unannounced = (
            "Platform to be announced"
            if arr_mode == "rail"
            else "stand to be announced"
        )
        return f"arrive {unannounced}, depart {dep_label}"
    else:
        if arr_mode != "rail" and dep_mode != "rail":
            return "stands to be announced"
        return "platforms to be announced"


def _format_transit_service_desc(
    mode: str,
    line: Optional[str] = None,
    operator: Optional[str] = None,
    destination: Optional[str] = None,
) -> str:
    """Format transit service description preventing duplicate mode keywords and handling route titles."""
    if (mode or "").lower() in FOOT_MODES:
        return "Transfer"

    mode_label = mode.title() if mode else "Transit"
    op_clean = (operator or "").strip()
    dest_clean = (destination or "").strip()
    line_clean = (line or "").strip()

    if line_clean:
        # Strip trailing operational day suffixes like (Mon-Fri), (Mon-Sat), (Sunday)
        line_clean = re.sub(r"\s*\([A-Za-z0-9\-,\s]+\)$", "", line_clean).strip()

        # Check if line_clean is an endpoint-to-endpoint route descriptor (e.g. "A to B" or "A - B")
        if " to " in line_clean or " - " in line_clean:
            sep = " to " if " to " in line_clean else " - "
            prefix = line_clean.split(sep, 1)[0].strip()

            # Check if there is a route number/code prefix before a colon, e.g. "Bus SB1: Woodcock Road to Bus Station"
            if ":" in prefix:
                route_code = prefix.split(":", 1)[0].strip()
                if op_clean and op_clean.lower() not in route_code.lower():
                    return f"{op_clean} {route_code}"
                return route_code

            # For rail legs with origin-to-destination titles
            if mode == "rail":
                veh = f"{op_clean} train" if op_clean else "Rail service"
                if dest_clean:
                    return f"{veh} towards {dest_clean}"
                return veh

            # For bus or other modes with origin-to-destination titles
            veh = f"{op_clean} {mode_label}" if op_clean else f"{mode_label} service"
            if dest_clean:
                return f"{veh} towards {dest_clean}"
            return veh

        # Standard line/route names (e.g. "73", "Bus 73", "Thameslink", "Piccadilly")
        if mode_label.lower() in line_clean.lower():
            return line_clean
        return f"{mode_label} {line_clean}"

    # If line is empty or None
    if op_clean:
        veh = "train" if mode == "rail" else mode_label
        if dest_clean:
            return f"{op_clean} {veh} towards {dest_clean}"
        return f"{op_clean} {veh}"

    if dest_clean:
        veh = "Train" if mode == "rail" else mode_label
        return f"{veh} towards {dest_clean}"

    return mode_label


def format_next_step_for_departure(
    legs: List[ItineraryLeg],
    current_transit_leg: Optional[ItineraryLeg] = None,
    only_transit: bool = False,
    live_client: Optional[TrainLiveClient] = None,
) -> str:
    """Format next step instruction or connecting transit details for departure notifications.

    When the current transit leg is followed by a subsequent transit service (e.g. a shuttle
    bus connecting into mainline rail), details the next service's mode, line, operator,
    origin, destination, departure time, and arrival/departure platforms in British English.
    If followed by a final walk to destination, details the walking distance and destination
    when only_transit is False.
    """
    if not legs:
        return ""

    start_idx = 0
    if current_transit_leg:
        found_idx = None
        for i, lg in enumerate(legs):
            if lg is current_transit_leg or (
                lg.mode == current_transit_leg.mode
                and lg.origin.id == current_transit_leg.origin.id
                and lg.destination.id == current_transit_leg.destination.id
                and lg.dep_time == current_transit_leg.dep_time
            ):
                found_idx = i
                break
            if (
                hasattr(lg, "leg_index")
                and hasattr(current_transit_leg, "leg_index")
                and lg.leg_index == current_transit_leg.leg_index
            ):
                found_idx = i
                break
        if found_idx is not None:
            start_idx = found_idx

    remaining_legs = legs[start_idx + 1 :]
    if not remaining_legs:
        return ""

    following_transit = next(
        (lg for lg in remaining_legs if lg.mode not in FOOT_MODES),
        None,
    )

    if following_transit:
        transfer_desc = _format_transit_service_desc(
            following_transit.mode,
            following_transit.line,
            following_transit.operator,
        )
        orig_name = (
            following_transit.origin.name
            if following_transit.origin and following_transit.origin.name
            else ""
        )
        dest_name = (
            following_transit.destination.name
            if following_transit.destination and following_transit.destination.name
            else ""
        )

        arr_plat = (
            current_transit_leg.destination.platform
            if current_transit_leg and current_transit_leg.destination
            else None
        )
        if (
            not arr_plat
            and current_transit_leg
            and current_transit_leg.mode == "rail"
            and live_client
        ):
            arr_plat = resolve_live_rail_arrival_platform(
                current_transit_leg.origin.id,
                current_transit_leg.destination.id,
                current_transit_leg.arr_time,
                live_client,
            )

        dep_plat = (
            following_transit.origin.platform if following_transit.origin else None
        )
        conn_live_status = None
        conn_delay_reason = None
        if not dep_plat and following_transit.mode == "rail" and live_client:
            conn_live = resolve_live_rail_platform(
                following_transit.origin.id,
                following_transit.destination.id,
                following_transit.dep_time,
                live_client,
            )
            dep_plat = conn_live.platform
            conn_live_status = conn_live.live_status
            conn_delay_reason = conn_live.delay_reason

        dep_desc = _format_departure_timing_with_delay(
            dep_time=following_transit.dep_time or "",
            live_status=conn_live_status,
            delay_reason=conn_delay_reason,
        )

        interchange_station = (
            current_transit_leg.destination.name
            if current_transit_leg and current_transit_leg.destination
            else orig_name
        )

        curr_dest = (
            current_transit_leg.destination.name
            if current_transit_leg and current_transit_leg.destination
            else ""
        )
        if curr_dest and orig_name and curr_dest != orig_name:
            arr_label = _format_platform_label(
                arr_plat, current_transit_leg.mode if current_transit_leg else "rail"
            )
            dep_label = _format_platform_label(dep_plat, following_transit.mode)
            arr_note = f" ({arr_label})" if arr_label else ""
            dep_note = f" ({dep_label})" if dep_label else ""

            walk_inter = next(
                (lg for lg in remaining_legs if lg.mode in FOOT_MODES),
                None,
            )
            walk_mins = walk_inter.duration_minutes if walk_inter else 0
            walk_part = f"walk {walk_mins}m to " if walk_mins > 0 else "walk to "
            dest_clause = f" to {dest_name}" if dest_name else ""
            return (
                f" Next step: Arrive at {curr_dest}{arr_note}, {walk_part}{orig_name}{dep_note} "
                f"to board {transfer_desc}{dest_clause} departing at {dep_desc}."
            )

        plat_clause = _format_upcoming_change_platforms(
            arr_plat,
            dep_plat,
            arr_mode=current_transit_leg.mode if current_transit_leg else "rail",
            dep_mode=following_transit.mode,
        )

        dest_clause = f" to {dest_name}" if dest_name else ""
        return (
            f" Next step: Transfer at {interchange_station} ({plat_clause}) "
            f"to board {transfer_desc}{dest_clause} departing at {dep_desc}."
        )

    if not only_transit:
        final_walk = next(
            (lg for lg in remaining_legs if lg.mode in FOOT_MODES),
            None,
        )
        if final_walk and final_walk.destination and final_walk.destination.name:
            mins = final_walk.duration_minutes
            walk_str = f"Walk {mins}m" if mins > 0 else "Walk"
            return f" Next step: {walk_str} to {final_walk.destination.name}."

    return ""


def _format_departure_timing_with_delay(
    dep_time: str,
    live_status: Optional[str] = None,
    delay_reason: Optional[str] = None,
    sched_time: Optional[str] = None,
) -> str:
    """Format scheduled departure time alongside live expected timing and delay reasons."""
    scheduled = sched_time or dep_time
    reason_clause = f" due to {delay_reason}" if delay_reason else ""

    if not live_status:
        return f"{scheduled} (scheduled)"

    if live_status == "On time":
        return f"{scheduled} (scheduled {scheduled}, expected {scheduled} - on time)"

    if live_status == "Delayed":
        return f"{scheduled} (scheduled {scheduled}, delayed{reason_clause})"

    if live_status == "Cancelled":
        return f"{scheduled} (scheduled {scheduled}, cancelled{reason_clause})"

    # When live_status is an expected departure time string (e.g. "08:38")
    if ":" in live_status:
        return f"{live_status} (scheduled {scheduled}, expected {live_status}{reason_clause})"

    return f"{scheduled} (scheduled {scheduled}, expected {live_status}{reason_clause})"


def _format_interchange_boarding_clause(
    arr_label: Optional[str],
    dep_label: Optional[str],
    service_desc: str,
    target_mode: str,
    is_walk_transfer: bool = False,
) -> str:
    """Format platform transfer and boarding instruction for an interchange station."""
    unann = (
        "Platform to be announced" if target_mode == "rail" else "stand to be announced"
    )
    verb = "Transfer to board" if is_walk_transfer else "Board"
    if arr_label and dep_label:
        action = (
            f"Transfer to {dep_label} to board {service_desc}"
            if is_walk_transfer
            else f"Board {service_desc} from {dep_label}"
        )
        return f"Arrived at {arr_label}. {action}"
    if arr_label:
        return f"Arrived at {arr_label}. {verb} {service_desc} ({unann})"
    if dep_label:
        return f"{verb} {service_desc} from {dep_label}"
    if target_mode == "rail":
        return f"{verb} {service_desc} from Platform to be announced"
    return f"Board {service_desc}"


def format_next_step_for_on_transit(
    legs: List[ItineraryLeg],
    current_leg_index: int,
    current_leg: ItineraryLeg,
    live_client: Optional[TrainLiveClient] = None,
) -> str:
    """Format next step or transfer instruction while passenger is currently in transit."""
    if current_leg_index + 1 >= len(legs):
        return ""
    next_leg = legs[current_leg_index + 1]
    if next_leg.mode in FOOT_MODES and current_leg_index + 1 == len(legs) - 1:
        return (
            f" Next step: Walk {next_leg.duration_minutes}m to {next_leg.destination.name}."
            if next_leg.destination
            else ""
        )

    following_transit = next(
        (lg for lg in legs[current_leg_index + 1 :] if lg.mode not in FOOT_MODES),
        None,
    )
    if not following_transit:
        if next_leg.mode in FOOT_MODES:
            return (
                f" Next step: Walk {next_leg.duration_minutes}m to {next_leg.destination.name}."
                if next_leg.destination
                else ""
            )
        return ""

    transfer_desc = _format_transit_service_desc(
        following_transit.mode,
        following_transit.line,
        following_transit.operator,
        destination=(
            following_transit.destination.name
            if following_transit.destination
            else None
        ),
    )
    arr_plat = current_leg.destination.platform if current_leg.destination else None
    if not arr_plat and current_leg.mode == "rail" and live_client:
        arr_plat = resolve_live_rail_arrival_platform(
            current_leg.origin.id,
            current_leg.destination.id,
            current_leg.arr_time,
            live_client,
        )

    dep_plat = following_transit.origin.platform if following_transit.origin else None
    conn_live_status = None
    conn_delay_reason = None
    if not dep_plat and following_transit.mode == "rail" and live_client:
        conn_live = resolve_live_rail_platform(
            following_transit.origin.id,
            following_transit.destination.id,
            following_transit.dep_time,
            live_client,
        )
        dep_plat = conn_live.platform
        conn_live_status = conn_live.live_status
        conn_delay_reason = conn_live.delay_reason

    dep_desc = _format_departure_timing_with_delay(
        following_transit.dep_time or "",
        conn_live_status,
        conn_delay_reason,
    )
    plat_clause = _format_upcoming_change_platforms(
        arr_plat,
        dep_plat,
        arr_mode=current_leg.mode,
        dep_mode=following_transit.mode,
    )
    dest_name = (
        current_leg.destination.name
        if current_leg.destination and current_leg.destination.name
        else ""
    )
    return (
        f" Transfer at {dest_name} ({plat_clause}) "
        f"to {transfer_desc} departing at {dep_desc}."
    )


__all__ = [
    "_format_departure_timing_with_delay",
    "_format_interchange_boarding_clause",
    "_format_platform_label",
    "_format_transit_service_desc",
    "_format_upcoming_change_platforms",
    "format_next_step_for_departure",
    "format_next_step_for_on_transit",
]
