"""Helper functions and sequence validators for route finding."""

from __future__ import annotations

import logging
from typing import List, Optional, Set

from app.models.timetable import Timetable
from app.services.planner.models import RouteLeg
from app.services.planner.transfers import (
    normalise_id,
    parse_time_to_minutes,
)

logger = logging.getLogger(__name__)


def make_node_key(node_type: str, raw_id: str) -> str:
    """Create standardised graph node identifier formatted as '{type}:{normalised_id}'."""
    t = str(node_type).strip().lower()
    return f"{t}:{normalise_id(raw_id)}"


def extract_route_base_name(line_name: Optional[str]) -> str:
    """Extract normalised base route identifier from a line or service name.

    Examples:
        "Bus SB1: Woodcock Road to Bus Station" -> "sb1"
        "Bus 37X: The Crown Inn to Bus Station" -> "37x"
        "Route 73" -> "73"
        "Bus 73" -> "73"
        "Rail: London to Cambridge" -> "london to cambridge"
    """
    if not line_name:
        return ""
    name = str(line_name).strip()
    for mode_prefix in ("rail:", "train:", "bus:", "coach:"):
        if name.lower().startswith(mode_prefix):
            name = name[len(mode_prefix) :].strip()

    if ":" in name:
        prefix_part = name.split(":", 1)[0].strip()
        for p in ("bus ", "route ", "line "):
            if prefix_part.lower().startswith(p):
                prefix_part = prefix_part[len(p) :].strip()
        if (
            prefix_part
            and len(prefix_part) <= 20
            and prefix_part.lower() not in ("rail", "train")
            and " to " not in prefix_part.lower()
        ):
            return prefix_part.lower()
        name = name.split(":", 1)[1].strip()

    for prefix in ("bus ", "route ", "line "):
        if name.lower().startswith(prefix):
            name = name[len(prefix) :].strip()
    return name.lower()


def timetable_operates_in_window(
    timetable: Timetable,
    window_start_min: int,
    window_end_min: int,
) -> bool:
    """Determine if a timetable contains any scheduled trip operating within the time window."""
    content = timetable.get_content()
    trips = content.get("trips", [])
    if not trips:
        return False
    for tr in trips:
        times = tr.get("times", [])
        for t_item in times:
            if isinstance(t_item, dict):
                t_str = t_item.get("dep") or t_item.get("arr") or ""
            else:
                t_str = str(t_item or "")
            t_min = parse_time_to_minutes(t_str)
            if t_min is not None:
                if window_start_min <= t_min <= window_end_min:
                    return True
                if window_end_min > 1440 and (t_min + 1440) <= window_end_min:
                    return True
    return False


def get_leg_mode(leg: RouteLeg) -> str:
    """Determine the effective transport mode of a route leg."""
    if leg.leg_type in ("walk", "interchange", "platform_transfer"):
        return "walk"
    if leg.transport_mode:
        m = leg.transport_mode.strip().lower()
        if m in ("walk", "walking", "foot", "interchange", "platform_transfer"):
            return "walk"
        return m
    return "walk" if leg.leg_type == "walk" else "transit"


def is_valid_leg_sequence(legs: List[RouteLeg]) -> bool:
    """Validate that a sequence of route legs satisfies modal sequence rules:

    1. Walking cannot be followed by more walking (no consecutive walking legs).
    2. A maximum of 4 legs of the same transport mode may occur consecutively in a row
       (up to 3 intra-modal transfers per stage).
    3. No reverse loops or transfers between opposite directions of the same transit line.
    4. No spatial turnaround loops (transit leg returning to a previously departed stop).

    Args:
        legs: Ordered list of RouteLeg objects.

    Returns:
        True if the sequence complies with all rules, False otherwise.
    """
    if not legs:
        return False

    consecutive_count = 0
    previous_mode: Optional[str] = None
    previous_transit_base: Optional[str] = None
    departed_transit_stop_ids: Set[str] = set()

    for leg in legs:
        mode = get_leg_mode(leg)

        if mode == "walk" and previous_mode == "walk":
            # Rule 1: Walking cannot be followed by more walking
            return False

        if mode == previous_mode:
            consecutive_count += 1
            if consecutive_count > 4:
                # Rule 2: Maximum of 4 of the same mode in a row (up to 3 transfers per stage)
                return False
        else:
            previous_mode = mode
            consecutive_count = 1

        if leg.leg_type == "transit":
            curr_base = extract_route_base_name(leg.line_name)
            # Rule 3: Reject consecutive transit legs sharing the same base line (turnaround / reverse loop)
            if (
                curr_base
                and previous_transit_base
                and curr_base == previous_transit_base
            ):
                return False

            # Rule 4: Reject spatial turnaround loops where a transit leg ends at a stop previously departed from
            norm_from = normalise_id(leg.from_id)
            norm_to = normalise_id(leg.to_id)
            if norm_to and norm_to in departed_transit_stop_ids:
                return False

            if norm_from:
                departed_transit_stop_ids.add(norm_from)
            previous_transit_base = curr_base
        elif leg.leg_type not in ("interchange", "platform_transfer", "walk"):
            previous_transit_base = None

    return True
