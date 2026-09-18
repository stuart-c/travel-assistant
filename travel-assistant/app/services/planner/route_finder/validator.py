"""Request validation and endpoint resolution for route finding."""

from __future__ import annotations

from dataclasses import dataclass
import datetime
import logging
from typing import List, Optional, Tuple, Union

from app.models.timetable import Timetable
from app.models.walking import Walking
from app.services.planner.exceptions import (
    InvalidEndpointError,
    JourneyPlanningError,
    JourneyPlanningErrorCode,
    NoAccessStopsError,
)
from app.services.planner.route_finder.helpers import (
    make_node_key,
    timetable_operates_in_window,
)
from app.services.planner.transfers import (
    get_access_edges,
    get_active_timetables,
    normalise_id,
    parse_time_to_minutes,
    resolve_active_days_and_date,
)

logger = logging.getLogger(__name__)


@dataclass
class RouteValidationResult:
    """Structured container for validated route query endpoints and active timetables."""

    from_type: str
    from_id: str
    to_type: str
    to_id: str
    origin_node: str
    dest_node: str
    active_days: List[str]
    target_date: Optional[datetime.date]
    active_timetables: List[Timetable]
    origin_walks: List[Tuple[str, str, str, str, int, str]]
    dest_walks: List[Tuple[str, str, str, str, int, str]]
    direct_walk: Optional[Walking]


def validate_route_request(
    from_type: str,
    from_id: str,
    to_type: str,
    to_id: str,
    days_of_week: Optional[List[str]] = None,
    target_date: Optional[Union[datetime.date, str]] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    timing_mode: Optional[str] = None,
) -> RouteValidationResult:
    """Validate query endpoints, resolve operational windows, and retrieve active timetables."""
    f_type = str(from_type).strip().lower()
    f_id = str(from_id).strip()
    t_type = str(to_type).strip().lower()
    t_id = str(to_id).strip()

    if not f_id or not t_id:
        raise InvalidEndpointError(
            "Both origin and destination identifiers must be provided.",
            {"from_id": f_id, "to_id": t_id},
        )

    if f_type == t_type and normalise_id(f_id) == normalise_id(t_id):
        raise JourneyPlanningError(
            JourneyPlanningErrorCode.SAME_ORIGIN_DESTINATION,
            "Origin and destination endpoints cannot be identical.",
            {"origin": f_id, "destination": t_id},
        )

    active_days, date_obj = resolve_active_days_and_date(days_of_week, target_date)
    logger.info(
        "Searching multi-modal route corridors from %s:%s to %s:%s (days: %s, window: %s-%s)...",
        f_type,
        f_id,
        t_type,
        t_id,
        active_days,
        start_time,
        end_time,
    )

    # Filter Active Timetables
    active_timetables = get_active_timetables(active_days, date_obj)

    # Filter active timetables by journey time window when provided
    if start_time or end_time:
        start_min = parse_time_to_minutes(start_time) if start_time else None
        end_min = parse_time_to_minutes(end_time) if end_time else None
        if start_min is not None or end_min is not None:
            if start_min is None:
                start_min = max(0, (end_min or 0) - 120)
            if end_min is None:
                end_min = min(1440, (start_min or 0) + 120)
            if start_min > end_min:
                start_min, end_min = end_min, start_min

            t_mode = (timing_mode or "depart").strip().lower()
            if t_mode == "arrive":
                eval_start = max(0, start_min - 120)
                eval_end = end_min + 30
            else:
                eval_start = max(0, start_min - 30)
                eval_end = end_min + 90

            window_timetables = [
                tt
                for tt in active_timetables
                if timetable_operates_in_window(tt, eval_start, eval_end)
            ]
            if window_timetables:
                logger.info(
                    "Filtered active timetables from %d to %d for journey window %s-%s (%s)",
                    len(active_timetables),
                    len(window_timetables),
                    start_time,
                    end_time,
                    t_mode,
                )
                active_timetables = window_timetables

    # Access & Egress Footpaths
    origin_walks = get_access_edges(f_type, f_id, is_origin=True)
    dest_walks = get_access_edges(t_type, t_id, is_origin=False)

    # Check if origin or destination endpoint is directly served by active timetables
    timetable_stop_ids = {
        normalise_id(s.get("id", ""))
        for tt in active_timetables
        for s in tt.get_content().get("stops", [])
    }
    if normalise_id(f_id) in timetable_stop_ids and not any(
        w[2] == f_type and normalise_id(w[3]) == normalise_id(f_id)
        for w in origin_walks
    ):
        origin_walks.append((f_type, f_id, f_type, f_id, 0, "direct"))
    if normalise_id(t_id) in timetable_stop_ids and not any(
        w[0] == t_type and normalise_id(w[1]) == normalise_id(t_id) for w in dest_walks
    ):
        dest_walks.append((t_type, t_id, t_type, t_id, 0, "direct"))

    # Check Direct Walking Connection First
    direct_walk = Walking.find_walking_route(f_type, f_id, t_type, t_id)
    if not direct_walk:
        direct_walk = Walking.find_walking_route(
            f_type, normalise_id(f_id), t_type, normalise_id(t_id)
        )

    if not origin_walks and not direct_walk:
        raise NoAccessStopsError(
            f"No reachable transit stops found within walking distance of origin '{f_id}'.",
            {"endpoint": f_id, "type": f_type},
        )

    if not dest_walks and not direct_walk:
        raise NoAccessStopsError(
            f"No reachable transit stops found within walking distance of destination '{t_id}'.",
            {"endpoint": t_id, "type": t_type},
        )

    origin_node = make_node_key(f_type, f_id)
    dest_node = make_node_key(t_type, t_id)

    return RouteValidationResult(
        from_type=f_type,
        from_id=f_id,
        to_type=t_type,
        to_id=t_id,
        origin_node=origin_node,
        dest_node=dest_node,
        active_days=active_days,
        target_date=date_obj,
        active_timetables=active_timetables,
        origin_walks=origin_walks,
        dest_walks=dest_walks,
        direct_walk=direct_walk,
    )
