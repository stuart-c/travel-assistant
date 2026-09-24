"""Schematic route diagram and step guidance builders for journey live tracking."""

from typing import Any, Dict, List, Optional

from app.services.dispatcher.tracker.models import (
    FOOT_MODES,
    JourneyStepStatus,
)
from app.utils.transit_time import parse_time_to_minutes

STATUS_METADATA: Dict[JourneyStepStatus, Dict[str, str]] = {
    JourneyStepStatus.PRE_DEPARTURE: {
        "label": "Preparing to leave",
        "icon": "schedule",
        "badge_colour": "sky",
    },
    JourneyStepStatus.EN_ROUTE_TO_STOP: {
        "label": "Walking to departure stop",
        "icon": "directions_walk",
        "badge_colour": "amber",
    },
    JourneyStepStatus.AT_DEPARTURE_STOP: {
        "label": "At departure stop",
        "icon": "pin_drop",
        "badge_colour": "indigo",
    },
    JourneyStepStatus.ON_TRANSIT: {
        "label": "On board transit",
        "icon": "directions_transit",
        "badge_colour": "emerald",
    },
    JourneyStepStatus.AT_INTERCHANGE: {
        "label": "At transfer station",
        "icon": "transfer_within_a_station",
        "badge_colour": "purple",
    },
    JourneyStepStatus.EN_ROUTE_TO_DESTINATION: {
        "label": "Walking to destination",
        "icon": "directions_walk",
        "badge_colour": "teal",
    },
    JourneyStepStatus.ARRIVED: {
        "label": "Arrived at destination",
        "icon": "check_circle",
        "badge_colour": "emerald",
    },
    JourneyStepStatus.EXPIRED: {
        "label": "Journey completed",
        "icon": "done_all",
        "badge_colour": "slate",
    },
}


def _build_next_step_instruction(
    current_leg_index: int,
    serialized_legs: List[Dict[str, Any]],
    current_status: JourneyStepStatus,
    from_name: str,
    to_name: str,
    departure_time: str,
    expected_arrival_time: str,
    platform: Optional[str],
) -> str:
    """Format step-by-step action guidance in British English."""
    if current_leg_index >= len(serialized_legs):
        return f"Journey from {from_name} to {to_name}."

    c_leg = serialized_legs[current_leg_index]
    mode_str = c_leg["mode"].title()
    line_str = c_leg.get("line") or ""
    if line_str and mode_str.lower() in line_str.lower():
        line_display = line_str
    elif line_str:
        line_display = f"{mode_str} {line_str}"
    else:
        line_display = mode_str

    if current_status == JourneyStepStatus.PRE_DEPARTURE:
        if departure_time:
            return f"Prepare to depart {from_name} for the {departure_time} departure."
        return f"Scheduled route from {from_name} to {to_name}."
    if current_status == JourneyStepStatus.EN_ROUTE_TO_STOP:
        return f"Walk to {c_leg['destination']['name']} for connection."
    if current_status == JourneyStepStatus.AT_DEPARTURE_STOP:
        plat_str = ""
        if c_leg.get("mode") == "rail":
            plat_str = f" from Platform {platform}" if platform else ""
        elif platform and any(w in platform.lower() for w in ("stand", "stop")):
            plat_str = f" from {platform}"
        return (
            f"Board {line_display} departing at {c_leg['dep_time']}{plat_str} "
            f"towards {c_leg['destination']['name']}."
        )
    if current_status == JourneyStepStatus.ON_TRANSIT:
        return f"Alight at {c_leg['destination']['name']} (ETA: {c_leg['arr_time']})."
    if current_status == JourneyStepStatus.AT_INTERCHANGE:
        plat_str = ""
        if c_leg.get("mode") == "rail":
            plat_str = f" from Platform {platform}" if platform else ""
        elif platform and any(w in platform.lower() for w in ("stand", "stop")):
            plat_str = f" from {platform}"
        return f"Transfer to {line_display} departing at {c_leg['dep_time']}{plat_str}."
    if current_status == JourneyStepStatus.EN_ROUTE_TO_DESTINATION:
        return f"Walk to final destination {to_name} (ETA: {expected_arrival_time})."
    if current_status == JourneyStepStatus.ARRIVED:
        return f"You have reached your destination: {to_name}."

    return f"Journey from {from_name} to {to_name}."


def _build_schematic_stages(
    serialized_legs: List[Dict[str, Any]],
    is_active: bool,
    current_status: JourneyStepStatus,
    current_leg_index: int,
) -> List[Dict[str, Any]]:
    """Build schematic route diagram elements."""
    schematic_stages: List[Dict[str, Any]] = []
    for idx, s_leg in enumerate(serialized_legs):
        is_first = idx == 0
        is_last = idx == len(serialized_legs) - 1

        is_stuart_at_origin_node = False
        if is_active:
            if is_first and current_status == JourneyStepStatus.PRE_DEPARTURE:
                is_stuart_at_origin_node = True
            elif (
                idx > 0
                and current_leg_index == idx
                and current_status
                in (
                    JourneyStepStatus.AT_DEPARTURE_STOP,
                    JourneyStepStatus.AT_INTERCHANGE,
                )
            ):
                is_stuart_at_origin_node = True

        is_stuart_on_this_leg = False
        stuart_stage_text = ""
        if is_active:
            if is_first and current_status == JourneyStepStatus.EN_ROUTE_TO_STOP:
                is_stuart_on_this_leg = True
                stuart_stage_text = "Stuart walking to departure stop"
            elif (
                current_status == JourneyStepStatus.ON_TRANSIT
                and current_leg_index == idx
            ):
                is_stuart_on_this_leg = True
                stuart_stage_text = (
                    f"Stuart on board {s_leg['line'] or s_leg['mode'].title()}"
                )
            elif (
                is_last and current_status == JourneyStepStatus.EN_ROUTE_TO_DESTINATION
            ):
                is_stuart_on_this_leg = True
                stuart_stage_text = "Stuart walking to final destination"

        mode = s_leg["mode"].lower()
        if mode == "rail":
            line_colour = "indigo"
            line_style = "solid"
        elif mode == "bus":
            line_colour = "rose"
            line_style = "solid"
        elif mode in FOOT_MODES:
            line_colour = "amber"
            line_style = "dashed"
        elif mode in ("metro", "subway", "tube"):
            line_colour = "sky"
            line_style = "solid"
        elif mode == "tram":
            line_colour = "emerald"
            line_style = "solid"
        else:
            line_colour = "slate"
            line_style = "solid"

        interchange_info = None
        if not is_last and idx + 1 < len(serialized_legs):
            next_l = serialized_legs[idx + 1]
            interchange_info = {
                "station_name": s_leg["destination"]["name"],
                "transfer_from": s_leg.get("line") or s_leg["mode"].title(),
                "transfer_to": next_l.get("line") or next_l["mode"].title(),
                "arrival_platform": s_leg["destination"].get("platform"),
                "next_dep_time": next_l["dep_time"],
                "next_platform": next_l["origin"]["platform"],
                "duration_minutes": max(
                    1,
                    (parse_time_to_minutes(next_l["dep_time"]) or 0)
                    - (parse_time_to_minutes(s_leg["arr_time"]) or 0),
                ),
                "is_stuart_here": (
                    is_active
                    and current_leg_index == idx + 1
                    and current_status == JourneyStepStatus.AT_INTERCHANGE
                ),
            }

        stage_data = {
            "stage_index": idx,
            "from_node": {
                "name": s_leg["origin"]["name"],
                "time": s_leg["dep_time"],
                "type": "origin" if is_first else "interchange",
                "platform": s_leg["origin"]["platform"],
                "is_stuart_here": is_stuart_at_origin_node,
            },
            "to_node": {
                "name": s_leg["destination"]["name"],
                "time": s_leg["arr_time"],
                "type": "destination" if is_last else "interchange",
                "platform": s_leg["destination"].get("platform"),
                "is_stuart_here": (
                    is_active
                    and is_last
                    and current_status == JourneyStepStatus.ARRIVED
                ),
            },
            "leg": s_leg,
            "line_colour": line_colour,
            "line_style": line_style,
            "is_stuart_on_leg": is_stuart_on_this_leg,
            "stuart_status_text": stuart_stage_text,
            "interchange": interchange_info,
        }
        schematic_stages.append(stage_data)

    return schematic_stages


__all__ = [
    "STATUS_METADATA",
    "_build_next_step_instruction",
    "_build_schematic_stages",
]
