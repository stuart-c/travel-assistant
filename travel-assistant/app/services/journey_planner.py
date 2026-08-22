"""Journey Planner Service.

Provides multi-modal route template discovery (Mode 1) and concrete scheduled
itinerary planning (Mode 2) using SQLite database tables, NetworkX topological graph
traversal, and an in-memory RAPTOR trip scheduling solver.
"""

from __future__ import annotations

import datetime
from enum import Enum
import logging
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import networkx as nx
from pydantic import BaseModel as PydanticBaseModel, ConfigDict, Field

from app.models.location import Location
from app.models.timetable import Timetable
from app.models.transfer import PlatformTransfer
from app.models.transit import Stop, StopInterchange
from app.models.walking import Walking

logger = logging.getLogger(__name__)

# Canonical transport days
VALID_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun", "bank_holiday")

DAY_NAME_TO_CODE = {
    "monday": "mon",
    "tuesday": "tue",
    "wednesday": "wed",
    "thursday": "thu",
    "friday": "fri",
    "saturday": "sat",
    "sunday": "sun",
}

CODE_TO_TIMETABLE_ATTR = {
    "mon": "monday",
    "tue": "tuesday",
    "wed": "wednesday",
    "thu": "thursday",
    "fri": "friday",
    "sat": "saturday",
    "sun": "sunday",
    "bank_holiday": "bank_holiday",
}


# ============================================================================
# 1. Error Hierarchy & Diagnostic Enums
# ============================================================================


class JourneyPlanningErrorCode(str, Enum):
    """Machine-readable error codes for journey planning failures."""

    INVALID_ENDPOINT = "INVALID_ENDPOINT"
    SAME_ORIGIN_DESTINATION = "SAME_ORIGIN_DESTINATION"
    NO_ACCESS_STOPS = "NO_ACCESS_STOPS"
    NO_CORRIDOR_PATH = "NO_CORRIDOR_PATH"
    NO_SERVICES_ON_DAY = "NO_SERVICES_ON_DAY"
    NO_TRIPS_IN_WINDOW = "NO_TRIPS_IN_WINDOW"
    UNSATISFIED_ARRIVE_BY = "UNSATISFIED_ARRIVE_BY"


class JourneyPlanningError(Exception):
    """Base domain exception raised when a journey route or plan cannot be computed."""

    def __init__(
        self,
        code: JourneyPlanningErrorCode,
        message: str,
        diagnostics: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.diagnostics = diagnostics or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert error to a structured dictionary representation."""
        return {
            "error_code": self.code.value,
            "message": self.message,
            "diagnostics": self.diagnostics,
        }


class InvalidEndpointError(JourneyPlanningError):
    """Raised when an origin or destination endpoint cannot be resolved."""

    def __init__(
        self, message: str, diagnostics: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(
            JourneyPlanningErrorCode.INVALID_ENDPOINT, message, diagnostics
        )


class NoAccessStopsError(JourneyPlanningError):
    """Raised when origin or destination has no reachable transit stops or walking paths."""

    def __init__(
        self, message: str, diagnostics: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(JourneyPlanningErrorCode.NO_ACCESS_STOPS, message, diagnostics)


class NoCorridorPathError(JourneyPlanningError):
    """Raised when no continuous multi-modal corridor connects origin and destination."""

    def __init__(
        self, message: str, diagnostics: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(
            JourneyPlanningErrorCode.NO_CORRIDOR_PATH, message, diagnostics
        )


class NoServicesOnDayError(JourneyPlanningError):
    """Raised when transit services do not operate on the requested day of the week."""

    def __init__(
        self, message: str, diagnostics: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(
            JourneyPlanningErrorCode.NO_SERVICES_ON_DAY, message, diagnostics
        )


class NoTripsInWindowError(JourneyPlanningError):
    """Raised when corridors exist but no scheduled trips run within the requested time window."""

    def __init__(
        self, message: str, diagnostics: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(
            JourneyPlanningErrorCode.NO_TRIPS_IN_WINDOW, message, diagnostics
        )


# ============================================================================
# 2. Structured Output Data Models
# ============================================================================


class RouteLeg(PydanticBaseModel):
    """A single leg or transit step within a topological RouteTemplate."""

    model_config = ConfigDict(extra="ignore")

    stage_index: int
    step_index: int
    leg_type: str  # "walk", "transit", "interchange", "platform_transfer"
    from_type: str
    from_id: str
    from_name: str
    to_type: str
    to_id: str
    to_name: str
    duration_minutes: int
    distance_m: Optional[int] = None
    transport_mode: Optional[str] = (
        None  # "bus", "rail", "metro", "tram", "ferry", "walk"
    )
    line_name: Optional[str] = None
    operator_name: Optional[str] = None
    stops_count: Optional[int] = None
    timetable_id: Optional[int] = None


class RouteTemplate(PydanticBaseModel):
    """Topological route corridor template discovered connecting origin to destination."""

    model_config = ConfigDict(extra="ignore")

    corridor_id: str
    name: str
    summary_text: str
    primary_mode: str = "bus"
    total_duration_est_minutes: int = 0
    transfer_count: int = 0
    stages_count: int = 1
    active_days: List[str] = Field(default_factory=list)
    legs: List[RouteLeg] = Field(default_factory=list)


class ItineraryEndpoint(PydanticBaseModel):
    """Origin or destination node within a scheduled itinerary leg."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    platform: Optional[str] = None


class ItineraryLeg(PydanticBaseModel):
    """A concrete timed leg within a ScheduledItinerary."""

    model_config = ConfigDict(extra="ignore")

    leg_index: int
    mode: str  # "walk", "bus", "rail", "interchange", "platform_transfer", "shuttle"
    origin: ItineraryEndpoint
    destination: ItineraryEndpoint
    dep_time: str
    arr_time: str
    duration_minutes: int
    line: Optional[str] = None
    operator: Optional[str] = None
    headsign: Optional[str] = None
    stops_count: Optional[int] = None
    timetable_id: Optional[int] = None


class ScheduledItinerary(PydanticBaseModel):
    """A concrete scheduled travel plan matching time and day constraints."""

    model_config = ConfigDict(extra="ignore")

    departure_time: str
    arrival_time: str
    total_duration_minutes: int
    transfers_count: int
    robustness_score: str
    legs: List[ItineraryLeg] = Field(default_factory=list)


# ============================================================================
# 3. Helper & Transfer Resolution Utilities
# ============================================================================


def parse_time_to_minutes(time_str: str) -> Optional[int]:
    """Parse 'HH:MM' or 'HH:MM:SS' time string to minutes past midnight."""
    if not time_str:
        return None
    s = str(time_str).strip()
    if not s:
        return None
    parts = s.split(":")
    try:
        hours = int(parts[0])
        minutes = int(parts[1]) if len(parts) > 1 else 0
        return hours * 60 + minutes
    except (ValueError, IndexError):
        return None


def format_minutes_to_time(minutes: int) -> str:
    """Format minutes past midnight back to 'HH:MM' string."""
    norm = minutes % (24 * 60)
    hours = norm // 60
    mins = norm % 60
    return f"{hours:02d}:{mins:02d}"


def normalise_id(raw_id: str) -> str:
    """Strip standard prefix from identifiers for lookup compatibility."""
    s = str(raw_id).strip()
    for prefix in ("atco:", "naptan:", "ha:", "custom:"):
        if s.startswith(prefix):
            return s[len(prefix) :]
    return s


def resolve_endpoint_name(endpoint_type: str, endpoint_id: str) -> str:
    """Resolve human-readable name for a location, stop, or station endpoint."""
    t = str(endpoint_type).strip().lower()
    raw_id = str(endpoint_id).strip()
    norm = normalise_id(raw_id)

    # Check Location model for HA / Custom places
    if (
        t in ("ha", "custom")
        or raw_id.startswith("ha:")
        or raw_id.startswith("custom:")
    ):
        try:
            loc = Location.get_or_none(Location.id == raw_id) or Location.get_or_none(
                Location.id == norm
            )
            if loc:
                return loc.name
        except Exception:
            pass

    # Check Stop model for Transit stops
    try:
        stop = Stop.get_by_code(raw_id) or Stop.get_by_code(norm)
        if stop:
            indicator_str = f" ({stop.indicator})" if stop.indicator else ""
            return f"{stop.name}{indicator_str}"
    except Exception:
        pass

    return raw_id


def resolve_transfer_duration(
    from_type: str,
    from_id: str,
    to_type: str,
    to_id: str,
    from_platform: Optional[str] = None,
    to_platform: Optional[str] = None,
    default_platform_minutes: int = 5,
) -> Optional[Tuple[int, str, Optional[int]]]:
    """Determine transfer time using strict 3-tier precedence hierarchy.

    Hierarchy:
      1. Explicit match in `walking` or `platform_transfers` table.
      2. Nearby stop interchange in `stop_interchanges` table.
      3. Default fallback of 5 minutes for intra-station platform interchanges.

    Returns:
        Tuple of (duration_minutes, transfer_kind, distance_metres) or None.
    """
    f_type = str(from_type).strip().lower()
    f_id = str(from_id).strip()
    t_type = str(to_type).strip().lower()
    t_id = str(to_id).strip()

    f_norm = normalise_id(f_id)
    t_norm = normalise_id(t_id)

    # Rule 1a: Check PlatformTransfer table if platforms are specified or station match
    if (
        f_type == "rail" and t_type == "rail" and (f_id == t_id or f_norm == t_norm)
    ) or (from_platform is not None and to_platform is not None):
        station_id = f_norm
        if from_platform and to_platform:
            pt = PlatformTransfer.find_transfer(station_id, from_platform, to_platform)
            if pt:
                return (pt.transfer_time_minutes, "platform_transfer", None)

        # Rule 3 Fallback: Platform interchange default buffer
        return (default_platform_minutes, "platform_transfer", None)

    # Rule 1b: Check Walking table for explicit configured connection
    walk_entry = Walking.find_walking_route(f_type, f_id, t_type, t_id)
    if not walk_entry:
        walk_entry = Walking.find_walking_route(f_type, f_norm, t_type, t_norm)
    if walk_entry:
        return (walk_entry.time_needed_minutes, "walk", None)

    # Rule 2: Check StopInterchange table (nearby stops within walking distance)
    interchange = (
        StopInterchange.select()
        .where(
            (
                (StopInterchange.from_stop_atco == f_id)
                | (StopInterchange.from_stop_atco == f_norm)
            )
            & (
                (StopInterchange.to_stop_atco == t_id)
                | (StopInterchange.to_stop_atco == t_norm)
            )
        )
        .first()
    )
    if interchange:
        return (
            interchange.estimated_walk_minutes,
            "interchange",
            interchange.distance_metres,
        )

    # If same transit stop ID
    if (f_id == t_id or f_norm == t_norm) and f_type == t_type:
        return (0, "interchange", 0)

    return None


def resolve_active_days_and_date(
    days_of_week: Optional[List[str]] = None,
    target_date: Optional[Union[datetime.date, str]] = None,
) -> Tuple[List[str], Optional[datetime.date]]:
    """Normalise and resolve active day codes and optional date object."""
    date_obj: Optional[datetime.date] = None

    if target_date is not None:
        if isinstance(target_date, datetime.date):
            date_obj = target_date
        elif isinstance(target_date, str) and target_date.strip():
            try:
                date_obj = datetime.date.fromisoformat(target_date.strip())
            except ValueError:
                pass

    active_days: List[str] = []
    if days_of_week:
        for d in days_of_week:
            clean_d = str(d).strip().lower()
            if clean_d in VALID_DAYS:
                active_days.append(clean_d)
            elif clean_d in DAY_NAME_TO_CODE:
                active_days.append(DAY_NAME_TO_CODE[clean_d])

    if date_obj is not None and not active_days:
        day_name = date_obj.strftime("%A").lower()
        if day_name in DAY_NAME_TO_CODE:
            active_days.append(DAY_NAME_TO_CODE[day_name])

    if not active_days:
        # Default to all weekdays if unspecified
        active_days = ["mon", "tue", "wed", "thu", "fri"]

    return active_days, date_obj


def is_timetable_active(
    timetable: Timetable,
    active_days: List[str],
    target_date: Optional[datetime.date] = None,
) -> bool:
    """Check if a timetable operates on the specified days and date validity range."""
    # Check date validity
    if target_date:
        if timetable.start_date and target_date < timetable.start_date:
            return False
        if timetable.end_date and target_date > timetable.end_date:
            return False

    # Check day masks
    operates_on_day = False
    for code in active_days:
        attr_name = CODE_TO_TIMETABLE_ATTR.get(code)
        if attr_name and getattr(timetable, attr_name, False):
            operates_on_day = True
            break

    return operates_on_day


# ============================================================================
# 4. Mode 1: Topological Route Discovery with NetworkX
# ============================================================================


def _get_access_edges(
    loc_type: str, loc_id: str, is_origin: bool
) -> List[Tuple[str, str, str, str, int, str]]:
    """Retrieve all access/egress walking connections from or to an endpoint.

    Returns list of tuples: (from_type, from_id, to_type, to_id, duration_minutes, kind)
    """
    edges: List[Tuple[str, str, str, str, int, str]] = []
    l_type = str(loc_type).strip().lower()
    l_id = str(loc_id).strip()
    l_norm = normalise_id(l_id)

    if (
        l_type in ("ha", "custom")
        or l_id.startswith("ha:")
        or l_id.startswith("custom:")
    ):
        # Query Walking table for location access
        walks = Walking.select().where(
            (Walking.start_id == l_id)
            | (Walking.start_id == l_norm)
            | (Walking.finish_id == l_id)
            | (Walking.finish_id == l_norm)
        )
        for w in walks:
            w_start_id = w.start_id
            w_finish_id = w.finish_id

            if is_origin:
                if (w_start_id in (l_id, l_norm)) or (
                    w.bidirectional and w_finish_id in (l_id, l_norm)
                ):
                    target_type = (
                        w.finish_type if w_start_id in (l_id, l_norm) else w.start_type
                    )
                    target_id = (
                        w.finish_id if w_start_id in (l_id, l_norm) else w.start_id
                    )
                    edges.append(
                        (
                            l_type,
                            l_id,
                            target_type,
                            target_id,
                            w.time_needed_minutes,
                            "walk",
                        )
                    )
            else:
                if (w_finish_id in (l_id, l_norm)) or (
                    w.bidirectional and w_start_id in (l_id, l_norm)
                ):
                    source_type = (
                        w.start_type if w_finish_id in (l_id, l_norm) else w.finish_type
                    )
                    source_id = (
                        w.start_id if w_finish_id in (l_id, l_norm) else w.finish_id
                    )
                    edges.append(
                        (
                            source_type,
                            source_id,
                            l_type,
                            l_id,
                            w.time_needed_minutes,
                            "walk",
                        )
                    )
    else:
        # Direct transit stop endpoint: 0-minute self walk
        edges.append((l_type, l_id, l_type, l_id, 0, "walk"))

    return edges


def find_routes(
    from_type: str,
    from_id: str,
    to_type: str,
    to_id: str,
    days_of_week: Optional[List[str]] = None,
    target_date: Optional[Union[datetime.date, str]] = None,
    max_stages: int = 6,
    max_transfers_per_stage: int = 3,
    max_routes: int = 5,
) -> List[RouteTemplate]:
    """Discover distinct viable multi-modal topological route templates.

    Builds a NetworkX multi-directed graph from the local SQLite database and extracts
    ranked, non-dominated corridor paths adhering to modal staging and pruning rules.

    Args:
        from_type: Origin location type ("ha", "custom", "rail", "bus", etc.).
        from_id: Origin location identifier.
        to_type: Destination location type ("ha", "custom", "rail", "bus", etc.).
        to_id: Destination location identifier.
        days_of_week: Optional list of active day codes ("mon".."sun", "bank_holiday").
        target_date: Optional target date object or YYYY-MM-DD string.
        max_stages: Maximum number of modal stages allowed (default: 6).
        max_transfers_per_stage: Maximum transfers within a single modal stage (default: 3).
        max_routes: Maximum number of route templates to return (default: 5).

    Returns:
        List of ranked RouteTemplate objects.

    Raises:
        InvalidEndpointError: If origin or destination endpoints cannot be resolved.
        NoAccessStopsError: If origin or destination has no reachable transit stops.
        NoCorridorPathError: If no continuous corridor connects origin and destination.
    """
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

    # 1. Access & Egress Footpaths
    origin_walks = _get_access_edges(f_type, f_id, is_origin=True)
    dest_walks = _get_access_edges(t_type, t_id, is_origin=False)

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

    # 2. Filter Active Timetables
    all_timetables = list(Timetable.select())
    active_timetables = [
        tt for tt in all_timetables if is_timetable_active(tt, active_days, date_obj)
    ]

    # 3. Build NetworkX Transit Graph
    G = nx.MultiDiGraph()
    origin_node = f"{f_type}:{f_id}"
    dest_node = f"{t_type}:{t_id}"
    G.add_node(origin_node, node_type=f_type, id=f_id)
    G.add_node(dest_node, node_type=t_type, id=t_id)

    # Add direct walk if present
    if direct_walk:
        G.add_edge(
            origin_node,
            dest_node,
            key="direct_walk",
            leg_type="walk",
            transport_mode="walk",
            duration=direct_walk.time_needed_minutes,
            distance_m=None,
            timetable_id=None,
            line_name=None,
            operator_name=None,
            stops_count=1,
            from_name=resolve_endpoint_name(f_type, f_id),
            to_name=resolve_endpoint_name(t_type, t_id),
        )

    # Add origin walking access edges
    for _, _, target_type, target_id, walk_min, kind in origin_walks:
        target_node = f"{target_type}:{target_id}"
        G.add_node(target_node, node_type=target_type, id=target_id)
        if target_node != origin_node:
            G.add_edge(
                origin_node,
                target_node,
                key=f"walk_orig_{target_id}",
                leg_type=kind,
                transport_mode="walk",
                duration=walk_min,
                distance_m=None,
                timetable_id=None,
                line_name=None,
                operator_name=None,
                stops_count=1,
                from_name=resolve_endpoint_name(f_type, f_id),
                to_name=resolve_endpoint_name(target_type, target_id),
            )

    # Add destination walking egress edges
    for source_type, source_id, _, _, walk_min, kind in dest_walks:
        source_node = f"{source_type}:{source_id}"
        G.add_node(source_node, node_type=source_type, id=source_id)
        if source_node != dest_node:
            G.add_edge(
                source_node,
                dest_node,
                key=f"walk_dest_{source_id}",
                leg_type=kind,
                transport_mode="walk",
                duration=walk_min,
                distance_m=None,
                timetable_id=None,
                line_name=None,
                operator_name=None,
                stops_count=1,
                from_name=resolve_endpoint_name(source_type, source_id),
                to_name=resolve_endpoint_name(t_type, t_id),
            )

    # Add scheduled timetable transit edges
    for tt in active_timetables:
        content_dict = tt.get_content()
        stops = content_dict.get("stops", [])
        if len(stops) < 2:
            continue

        # Add directed transit segments between all consecutive calling stops
        for i in range(len(stops) - 1):
            s_from = stops[i]
            s_to = stops[i + 1]
            from_st_type = s_from.get("type", tt.transport_type)
            from_st_id = s_from.get("id", "")
            to_st_type = s_to.get("type", tt.transport_type)
            to_st_id = s_to.get("id", "")

            u_node = f"{from_st_type}:{from_st_id}"
            v_node = f"{to_st_type}:{to_st_id}"
            G.add_node(u_node, node_type=from_st_type, id=from_st_id)
            G.add_node(v_node, node_type=to_st_type, id=to_st_id)

            # Estimate run duration between consecutive stops
            est_duration = 3 if tt.transport_type == "bus" else 5
            trips = content_dict.get("trips", [])
            if trips:
                sample_times = trips[0].get("times", [])
                if len(sample_times) > i + 1:
                    t1_val = sample_times[i]
                    t2_val = sample_times[i + 1]
                    dep_s = (
                        t1_val.get("dep") or t1_val.get("arr")
                        if isinstance(t1_val, dict)
                        else t1_val
                    )
                    arr_s = (
                        t2_val.get("arr") or t2_val.get("dep")
                        if isinstance(t2_val, dict)
                        else t2_val
                    )
                    dep_m = parse_time_to_minutes(dep_s)
                    arr_m = parse_time_to_minutes(arr_s)
                    if dep_m is not None and arr_m is not None and arr_m >= dep_m:
                        est_duration = max(1, arr_m - dep_m)

            operator_name = (
                trips[0].get("operator") or trips[0].get("toc") if trips else None
            )

            G.add_edge(
                u_node,
                v_node,
                key=f"tt_{tt.id}_{i}",
                leg_type="transit",
                transport_mode=tt.transport_type,
                duration=est_duration,
                distance_m=None,
                timetable_id=tt.id,
                line_name=tt.name,
                operator_name=operator_name,
                stops_count=1,
                from_name=s_from.get("name")
                or resolve_endpoint_name(from_st_type, from_st_id),
                to_name=s_to.get("name") or resolve_endpoint_name(to_st_type, to_st_id),
            )

    # Add stop interchanges and platform transfers
    stop_interchanges = list(StopInterchange.select())
    for si in stop_interchanges:
        u_node = f"{si.from_stop_type}:{si.from_stop_atco}"
        v_node = f"{si.to_stop_type}:{si.to_stop_atco}"
        if G.has_node(u_node) and G.has_node(v_node):
            G.add_edge(
                u_node,
                v_node,
                key=f"interchange_{si.id}",
                leg_type="interchange",
                transport_mode="walk",
                duration=si.estimated_walk_minutes,
                distance_m=si.distance_metres,
                timetable_id=None,
                line_name=None,
                operator_name=None,
                stops_count=1,
                from_name=si.from_stop_name,
                to_name=si.to_stop_name,
            )

    # Add same-station rail platform transfers for nodes with same ATCO/CRS code
    rail_nodes = [n for n, d in G.nodes(data=True) if d.get("node_type") == "rail"]
    for u in rail_nodes:
        for v in rail_nodes:
            if u != v:
                u_id = G.nodes[u].get("id", "")
                v_id = G.nodes[v].get("id", "")
                if normalise_id(u_id) == normalise_id(v_id):
                    trans_info = resolve_transfer_duration("rail", u_id, "rail", v_id)
                    if trans_info:
                        dur, kind, _ = trans_info
                        G.add_edge(
                            u,
                            v,
                            key=f"plat_{u}_{v}",
                            leg_type=kind,
                            transport_mode="walk",
                            duration=dur,
                            distance_m=None,
                            timetable_id=None,
                            line_name=None,
                            operator_name=None,
                            stops_count=1,
                            from_name=resolve_endpoint_name("rail", u_id),
                            to_name=resolve_endpoint_name("rail", v_id),
                        )

    # 4. Extract Non-cyclic Paths using NetworkX
    if not nx.has_path(G, origin_node, dest_node):
        raise NoCorridorPathError(
            f"No transit corridor exists connecting '{f_id}' to '{t_id}' on {active_days}.",
            {
                "from_id": f_id,
                "to_id": t_id,
                "active_days": active_days,
                "active_timetables_count": len(active_timetables),
            },
        )

    candidate_templates: List[RouteTemplate] = []
    try:
        paths = list(
            nx.all_simple_edge_paths(G, origin_node, dest_node, cutoff=max_stages * 4)
        )
    except Exception as e:
        logger.warning("NetworkX all_simple_edge_paths exception: %s", e)
        paths = []

    # If simple edge paths returned no paths or failed, fallback to shortest simple path
    if not paths:
        try:
            node_path = nx.shortest_path(G, origin_node, dest_node)
            single_edge_path = []
            for i in range(len(node_path) - 1):
                u, v = node_path[i], node_path[i + 1]
                edge_data = list(G.get_edge_data(u, v).keys())[0]
                single_edge_path.append((u, v, edge_data))
            paths = [single_edge_path]
        except Exception:
            paths = []

    if not paths:
        raise NoCorridorPathError(
            f"No viable corridor paths found connecting '{f_id}' to '{t_id}'.",
            {"from_id": f_id, "to_id": t_id},
        )

    # 5. Compress contiguous segments and assemble RouteTemplates
    corridor_idx = 1
    for edge_seq in paths:
        compressed_legs: List[RouteLeg] = []
        stage_idx = 1
        step_idx = 1
        total_duration = 0
        transfers_count = 0
        current_transit_leg: Optional[Dict[str, Any]] = None

        for u, v, k in edge_seq:
            edge_attr = G.edges[u, v, k]
            leg_type = edge_attr.get("leg_type", "walk")
            dur = edge_attr.get("duration", 1)
            total_duration += dur

            if leg_type == "transit":
                tt_id = edge_attr.get("timetable_id")
                line_name = edge_attr.get("line_name")
                op_name = edge_attr.get("operator_name")
                mode = edge_attr.get("transport_mode", "bus")

                if (
                    current_transit_leg is not None
                    and current_transit_leg.get("timetable_id") == tt_id
                ):
                    # Extend current transit leg along the same timetable corridor
                    current_transit_leg["to_type"] = G.nodes[v].get("node_type", "bus")
                    current_transit_leg["to_id"] = G.nodes[v].get("id", "")
                    current_transit_leg["to_name"] = edge_attr.get("to_name", "")
                    current_transit_leg["duration_minutes"] += dur
                    current_transit_leg["stops_count"] += 1
                else:
                    if current_transit_leg is not None:
                        compressed_legs.append(RouteLeg(**current_transit_leg))
                        stage_idx += 1
                        step_idx += 1
                        transfers_count += 1

                    current_transit_leg = {
                        "stage_index": stage_idx,
                        "step_index": step_idx,
                        "leg_type": "transit",
                        "from_type": G.nodes[u].get("node_type", "bus"),
                        "from_id": G.nodes[u].get("id", ""),
                        "from_name": edge_attr.get("from_name", ""),
                        "to_type": G.nodes[v].get("node_type", "bus"),
                        "to_id": G.nodes[v].get("id", ""),
                        "to_name": edge_attr.get("to_name", ""),
                        "duration_minutes": dur,
                        "distance_m": None,
                        "transport_mode": mode,
                        "line_name": line_name,
                        "operator_name": op_name,
                        "stops_count": 1,
                        "timetable_id": tt_id,
                    }
            else:
                # Flush pending transit leg
                if current_transit_leg is not None:
                    compressed_legs.append(RouteLeg(**current_transit_leg))
                    current_transit_leg = None
                    stage_idx += 1
                    step_idx += 1

                compressed_legs.append(
                    RouteLeg(
                        stage_index=stage_idx,
                        step_index=step_idx,
                        leg_type=leg_type,
                        from_type=G.nodes[u].get("node_type", "walk"),
                        from_id=G.nodes[u].get("id", ""),
                        from_name=edge_attr.get("from_name", ""),
                        to_type=G.nodes[v].get("node_type", "walk"),
                        to_id=G.nodes[v].get("id", ""),
                        to_name=edge_attr.get("to_name", ""),
                        duration_minutes=dur,
                        distance_m=edge_attr.get("distance_m"),
                        transport_mode=edge_attr.get("transport_mode", "walk"),
                        line_name=edge_attr.get("line_name"),
                        operator_name=edge_attr.get("operator_name"),
                        stops_count=edge_attr.get("stops_count", 1),
                        timetable_id=edge_attr.get("timetable_id"),
                    )
                )
                stage_idx += 1
                step_idx += 1

        if current_transit_leg is not None:
            compressed_legs.append(RouteLeg(**current_transit_leg))

        # Check stage limits
        if stage_idx > max_stages + 2:
            continue

        transit_legs_count = sum(
            1 for leg in compressed_legs if leg.leg_type == "transit"
        )
        transfers_count = max(0, transit_legs_count - 1)

        # Build Route Template
        transit_modes = [
            leg.transport_mode
            for leg in compressed_legs
            if leg.leg_type == "transit" and leg.transport_mode
        ]
        primary_mode = transit_modes[0] if transit_modes else "walk"

        summary_parts = []
        for leg in compressed_legs:
            if leg.leg_type == "transit":
                summary_parts.append(
                    f"{leg.transport_mode.capitalize()} {leg.line_name or ''}".strip()
                )
            elif leg.leg_type == "walk":
                summary_parts.append(f"Walk ({leg.duration_minutes}m)")
            elif leg.leg_type in ("interchange", "platform_transfer"):
                summary_parts.append(f"Transfer ({leg.duration_minutes}m)")

        summary_text = " → ".join(summary_parts)
        name = f"Via {summary_parts[1]}" if len(summary_parts) > 1 else "Direct Walk"

        candidate_templates.append(
            RouteTemplate(
                corridor_id=f"corridor_{corridor_idx}",
                name=name,
                summary_text=summary_text,
                primary_mode=primary_mode,
                total_duration_est_minutes=total_duration,
                transfer_count=transfers_count,
                stages_count=len(compressed_legs),
                active_days=active_days,
                legs=compressed_legs,
            )
        )
        corridor_idx += 1

    # 6. Apply Route Pruning Rules
    pruned_templates = _prune_route_templates(candidate_templates)
    return pruned_templates[:max_routes]


def _prune_route_templates(
    routes: List[RouteTemplate],
) -> List[RouteTemplate]:
    """Apply the 4 formal pruning and Pareto-optimisation rules."""
    if not routes:
        return []

    # Rule 1 & 2: Deduplication by stop corridor signature
    unique_routes: List[RouteTemplate] = []
    seen_signatures: Set[str] = set()

    for r in routes:
        sig_elements = []
        for leg in r.legs:
            sig_elements.append(
                f"{leg.leg_type}:{leg.from_id}->{leg.to_id}:{leg.timetable_id or ''}"
            )
        signature = "|".join(sig_elements)
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        unique_routes.append(r)

    # Rule 3: Pareto-Frontier Dominance Filtering
    # Route A dominates Route B if Duration(A) <= Duration(B) and Transfers(A) <= Transfers(B) with one strict inequality
    non_dominated: List[RouteTemplate] = []
    for candidate in unique_routes:
        is_dominated = False
        for other in unique_routes:
            if candidate is other:
                continue
            if (
                other.total_duration_est_minutes <= candidate.total_duration_est_minutes
                and other.transfer_count <= candidate.transfer_count
                and (
                    other.total_duration_est_minutes
                    < candidate.total_duration_est_minutes
                    or other.transfer_count < candidate.transfer_count
                )
            ):
                is_dominated = True
                break
        if not is_dominated:
            non_dominated.append(candidate)

    if not non_dominated:
        non_dominated = unique_routes

    # Rule 4: Senseless Detour Threshold (<= 1.5x fastest alternative or <= +30 mins)
    fastest_duration = min(r.total_duration_est_minutes for r in non_dominated)
    filtered = [
        r
        for r in non_dominated
        if r.total_duration_est_minutes
        <= max(fastest_duration * 1.5, fastest_duration + 30)
    ]

    # Sort by duration and transfers
    filtered.sort(key=lambda r: (r.total_duration_est_minutes, r.transfer_count))
    return filtered or non_dominated


# ============================================================================
# 5. Mode 2: Specific Scheduled Itinerary Planning with RAPTOR
# ============================================================================


class _ParsedTrip:
    """Internal representation of a timetable trip for the RAPTOR solver."""

    def __init__(
        self,
        trip_id: str,
        timetable_id: int,
        line_name: str,
        transport_mode: str,
        operator: Optional[str],
        headsign: Optional[str],
        stops: List[str],
        arr_times: List[Optional[int]],
        dep_times: List[Optional[int]],
    ) -> None:
        self.trip_id = trip_id
        self.timetable_id = timetable_id
        self.line_name = line_name
        self.transport_mode = transport_mode
        self.operator = operator
        self.headsign = headsign
        self.stops = stops
        self.arr_times = arr_times
        self.dep_times = dep_times
        self.stop_indices = {s: i for i, s in enumerate(stops)}


def _extract_parsed_trips(timetables: List[Timetable]) -> List[_ParsedTrip]:
    """Convert Peewee Timetable models to structured in-memory trips."""
    parsed_trips: List[_ParsedTrip] = []

    for tt in timetables:
        content_dict = tt.get_content()
        stops_raw = content_dict.get("stops", [])
        trips_raw = content_dict.get("trips", [])

        if not stops_raw or not trips_raw:
            continue

        stop_ids = [str(s.get("id", "")).strip() for s in stops_raw]

        for tr in trips_raw:
            times = tr.get("times", [])
            arr_list: List[Optional[int]] = []
            dep_list: List[Optional[int]] = []

            for t_item in times:
                if isinstance(t_item, dict):
                    arr_s = t_item.get("arr") or ""
                    dep_s = t_item.get("dep") or ""
                else:
                    arr_s = str(t_item or "")
                    dep_s = str(t_item or "")

                arr_m = parse_time_to_minutes(arr_s)
                dep_m = parse_time_to_minutes(dep_s)

                if arr_m is None and dep_m is not None:
                    arr_m = dep_m
                elif dep_m is None and arr_m is not None:
                    dep_m = arr_m

                arr_list.append(arr_m)
                dep_list.append(dep_m)

            # Ensure lengths match stops
            while len(arr_list) < len(stop_ids):
                arr_list.append(None)
                dep_list.append(None)

            parsed_trips.append(
                _ParsedTrip(
                    trip_id=str(tr.get("id", "")),
                    timetable_id=tt.id,
                    line_name=tt.name,
                    transport_mode=tt.transport_type,
                    operator=tr.get("operator") or tr.get("toc"),
                    headsign=tr.get("headsign"),
                    stops=stop_ids,
                    arr_times=arr_list,
                    dep_times=dep_list,
                )
            )

    return parsed_trips


def plan_journey(
    from_type: str,
    from_id: str,
    to_type: str,
    to_id: str,
    timing_mode: str = "depart",  # "depart", "arrive", or "window"
    time_str: str = "08:00",
    time_window_end: Optional[str] = None,
    days_of_week: Optional[List[str]] = None,
    target_date: Optional[Union[datetime.date, str]] = None,
    min_transfer_minutes: int = 3,
    max_transfers: int = 5,
    max_itineraries: int = 5,
) -> List[ScheduledItinerary]:
    """Calculate concrete scheduled travel itineraries matching time and day constraints.

    Uses an in-memory RAPTOR (Round-Based Public Transit Routing) algorithm to find
    Pareto-optimal scheduled travel plans directly from database timetable trips.

    Args:
        from_type: Origin location type ("ha", "custom", "rail", "bus", etc.).
        from_id: Origin location identifier.
        to_type: Destination location type ("ha", "custom", "rail", "bus", etc.).
        to_id: Destination location identifier.
        timing_mode: "depart" (leave after time_str), "arrive" (arrive before time_str), or "window".
        time_str: Target time in "HH:MM" format.
        time_window_end: Window end time in "HH:MM" format if timing_mode == "window".
        days_of_week: Optional list of active day codes ("mon".."sun", "bank_holiday").
        target_date: Optional target date object or YYYY-MM-DD string.
        min_transfer_minutes: Minimum interchange buffer duration in minutes (default: 3).
        max_transfers: Maximum number of transit changes allowed (default: 5).
        max_itineraries: Maximum number of ranked plans to return (default: 5).

    Returns:
        List of ranked ScheduledItinerary objects.

    Raises:
        InvalidEndpointError: If endpoints are invalid.
        NoAccessStopsError: If origin or destination has no reachable transit stops.
        NoCorridorPathError: If no transit path connects the endpoints.
        NoTripsInWindowError: If routes exist but no scheduled trips run in the requested window.
    """
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

    t_mode = str(timing_mode).strip().lower()
    if t_mode not in ("depart", "arrive", "window"):
        t_mode = "depart"

    t_start_min = parse_time_to_minutes(time_str)
    if t_start_min is None:
        t_start_min = 8 * 60  # Default 08:00

    t_end_min = parse_time_to_minutes(time_window_end) if time_window_end else None
    if t_mode == "window" and t_end_min is None:
        t_end_min = t_start_min + 120  # 2-hour window default

    active_days, date_obj = resolve_active_days_and_date(days_of_week, target_date)

    # 1. Access & Egress Footpaths
    origin_walks = _get_access_edges(f_type, f_id, is_origin=True)
    dest_walks = _get_access_edges(t_type, t_id, is_origin=False)

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

    # 2. Extract and Filter Timetables & Trips
    all_timetables = list(Timetable.select())
    active_timetables = [
        tt for tt in all_timetables if is_timetable_active(tt, active_days, date_obj)
    ]

    trips = _extract_parsed_trips(active_timetables)

    # Check if Direct Walk satisfies the plan
    candidate_itineraries: List[ScheduledItinerary] = []
    if direct_walk:
        walk_min = direct_walk.time_needed_minutes
        if t_mode == "arrive":
            dep_min = t_start_min - walk_min
            arr_min = t_start_min
        else:
            dep_min = t_start_min
            arr_min = t_start_min + walk_min

        orig_name = resolve_endpoint_name(f_type, f_id)
        dest_name = resolve_endpoint_name(t_type, t_id)

        candidate_itineraries.append(
            ScheduledItinerary(
                departure_time=format_minutes_to_time(dep_min),
                arrival_time=format_minutes_to_time(arr_min),
                total_duration_minutes=walk_min,
                transfers_count=0,
                robustness_score="Optimal (Direct Walk)",
                legs=[
                    ItineraryLeg(
                        leg_index=1,
                        mode="walk",
                        origin=ItineraryEndpoint(id=f_id, name=orig_name),
                        destination=ItineraryEndpoint(id=t_id, name=dest_name),
                        dep_time=format_minutes_to_time(dep_min),
                        arr_time=format_minutes_to_time(arr_min),
                        duration_minutes=walk_min,
                    )
                ],
            )
        )

    if not trips and not candidate_itineraries:
        raise NoServicesOnDayError(
            f"No transit services operate on the requested day(s) {active_days}.",
            {"days": active_days},
        )

    # 3. Execute RAPTOR for departure sweeps
    # Determine departure evaluation points based on timing mode
    eval_departures: List[int] = []
    if t_mode == "depart":
        eval_departures = [t_start_min]
    elif t_mode == "window":
        eval_departures = list(range(t_start_min, (t_end_min or t_start_min) + 1, 10))
    elif t_mode == "arrive":
        # Scan backward departure candidates up to 4 hours prior
        earliest_dep = max(0, t_start_min - 240)
        eval_departures = list(range(earliest_dep, t_start_min, 10))

    for dep_t in eval_departures:
        itinerary = _run_raptor_forward(
            dep_time_min=dep_t,
            origin_walks=origin_walks,
            dest_walks=dest_walks,
            trips=trips,
            f_type=f_type,
            f_id=f_id,
            t_type=t_type,
            t_id=t_id,
            min_transfer_min=min_transfer_minutes,
            max_rounds=max_transfers + 1,
        )
        if itinerary:
            # Check timing constraints
            if t_mode == "arrive":
                arr_m = parse_time_to_minutes(itinerary.arrival_time)
                if arr_m is not None and arr_m <= t_start_min:
                    candidate_itineraries.append(itinerary)
            elif t_mode == "window":
                dep_m = parse_time_to_minutes(itinerary.departure_time)
                if (
                    dep_m is not None
                    and dep_m >= t_start_min
                    and dep_m <= (t_end_min or t_start_min)
                ):
                    candidate_itineraries.append(itinerary)
            else:
                candidate_itineraries.append(itinerary)

    if not candidate_itineraries:
        # Check if corridor exists topologically
        try:
            find_routes(f_type, f_id, t_type, t_id, days_of_week, target_date)
            raise NoTripsInWindowError(
                f"Corridor exists, but no trips operate in the time window '{time_str}'.",
                {
                    "timing_mode": t_mode,
                    "time_str": time_str,
                    "active_days": active_days,
                },
            )
        except (NoAccessStopsError, NoCorridorPathError):
            raise

    # 4. Deduplicate and Pareto-Rank Itineraries
    unique_itineraries: List[ScheduledItinerary] = []
    seen_itineraries: Set[str] = set()

    for it in candidate_itineraries:
        sig = f"{it.departure_time}-{it.arrival_time}-{it.transfers_count}"
        if sig not in seen_itineraries:
            seen_itineraries.add(sig)
            unique_itineraries.append(it)

    # Sort based on timing mode
    if t_mode == "arrive":
        # Latest departure arriving before deadline
        unique_itineraries.sort(
            key=lambda it: (
                -(parse_time_to_minutes(it.departure_time) or 0),
                it.total_duration_minutes,
                it.transfers_count,
            )
        )
    else:
        # Earliest departure / shortest duration
        unique_itineraries.sort(
            key=lambda it: (
                parse_time_to_minutes(it.departure_time) or 0,
                it.total_duration_minutes,
                it.transfers_count,
            )
        )

    return unique_itineraries[:max_itineraries]


def _run_raptor_forward(
    dep_time_min: int,
    origin_walks: List[Tuple[str, str, str, str, int, str]],
    dest_walks: List[Tuple[str, str, str, str, int, str]],
    trips: List[_ParsedTrip],
    f_type: str,
    f_id: str,
    t_type: str,
    t_id: str,
    min_transfer_min: int = 3,
    max_rounds: int = 5,
) -> Optional[ScheduledItinerary]:
    """Execute a single forward RAPTOR run from dep_time_min."""
    infinity = 99999

    # State arrays: tau[k][stop] = arrival time at stop in round k
    tau: Dict[int, Dict[str, int]] = {}
    tau_star: Dict[str, int] = {}
    leg_pointer: Dict[int, Dict[str, Any]] = {}

    for k in range(max_rounds + 1):
        tau[k] = {}
        leg_pointer[k] = {}

    # Round 0: Origin Access Footpaths
    marked_stops: Set[str] = set()
    orig_name = resolve_endpoint_name(f_type, f_id)

    for _, _, target_type, target_id, walk_min, kind in origin_walks:
        target_norm = normalise_id(target_id)
        arr_t = dep_time_min + walk_min
        tau[0][target_norm] = arr_t
        tau_star[target_norm] = arr_t
        leg_pointer[0][target_norm] = {
            "mode": "walk",
            "from_type": f_type,
            "from_id": f_id,
            "from_name": orig_name,
            "to_type": target_type,
            "to_id": target_id,
            "to_name": resolve_endpoint_name(target_type, target_id),
            "dep_time": dep_time_min,
            "arr_time": arr_t,
            "duration": walk_min,
        }
        marked_stops.add(target_norm)

    # Pre-index trips serving stops
    stop_to_trips: Dict[str, List[_ParsedTrip]] = {}
    for tr in trips:
        for s in tr.stops:
            s_norm = normalise_id(s)
            stop_to_trips.setdefault(s_norm, []).append(tr)

    # Pre-fetch spatial footpaths
    stop_interchanges = list(StopInterchange.select())
    interchanges_by_stop: Dict[str, List[Tuple[str, int]]] = {}
    for si in stop_interchanges:
        f_st = normalise_id(si.from_stop_atco)
        t_st = normalise_id(si.to_stop_atco)
        interchanges_by_stop.setdefault(f_st, []).append(
            (t_st, si.estimated_walk_minutes)
        )

    # RAPTOR Round Loop: k = 1 to max_rounds
    for k in range(1, max_rounds + 1):
        # Step A: Copy previous round values
        for s, arr_t in tau[k - 1].items():
            tau[k][s] = arr_t

        routes_to_scan: Set[_ParsedTrip] = set()
        for s in marked_stops:
            for tr in stop_to_trips.get(s, []):
                routes_to_scan.add(tr)

        marked_stops.clear()

        # Step B: Scan trips along routes
        for tr in routes_to_scan:
            boarding_idx: Optional[int] = None
            boarding_dep_t: Optional[int] = None

            for i, stop_id in enumerate(tr.stops):
                s_norm = normalise_id(stop_id)
                arr_t = tr.arr_times[i]
                dep_t = tr.dep_times[i]

                # Check if we can alight here
                if boarding_idx is not None and arr_t is not None:
                    prev_best = tau_star.get(s_norm, infinity)
                    if arr_t < prev_best:
                        tau[k][s_norm] = arr_t
                        tau_star[s_norm] = arr_t
                        boarding_stop_id = tr.stops[boarding_idx]
                        leg_pointer[k][s_norm] = {
                            "mode": tr.transport_mode,
                            "trip": tr,
                            "from_stop": boarding_stop_id,
                            "from_name": resolve_endpoint_name(
                                tr.transport_mode, boarding_stop_id
                            ),
                            "to_stop": stop_id,
                            "to_name": resolve_endpoint_name(
                                tr.transport_mode, stop_id
                            ),
                            "dep_time": boarding_dep_t,
                            "arr_time": arr_t,
                            "duration": arr_t - (boarding_dep_t or arr_t),
                            "stops_count": i - boarding_idx,
                            "timetable_id": tr.timetable_id,
                            "line": tr.line_name,
                            "operator": tr.operator,
                            "headsign": tr.headsign,
                        }
                        marked_stops.add(s_norm)

                # Check if we can board or transfer here
                prev_arr = tau[k - 1].get(s_norm, infinity)
                if prev_arr < infinity and dep_t is not None:
                    transfer_slack = min_transfer_min if k > 1 else 0
                    if dep_t >= prev_arr + transfer_slack:
                        if boarding_idx is None or dep_t < (boarding_dep_t or infinity):
                            boarding_idx = i
                            boarding_dep_t = dep_t

        # Step C: Relax spatial footpaths and platform transfers
        for stop_norm in list(marked_stops):
            curr_arr = tau[k][stop_norm]

            # 1. Nearby stop interchanges
            for target_norm, walk_min in interchanges_by_stop.get(stop_norm, []):
                trans_arr = curr_arr + walk_min
                if trans_arr < tau_star.get(target_norm, infinity):
                    tau[k][target_norm] = trans_arr
                    tau_star[target_norm] = trans_arr
                    leg_pointer[k][target_norm] = {
                        "mode": "interchange",
                        "from_stop": stop_norm,
                        "from_name": resolve_endpoint_name("bus", stop_norm),
                        "to_stop": target_norm,
                        "to_name": resolve_endpoint_name("bus", target_norm),
                        "dep_time": curr_arr,
                        "arr_time": trans_arr,
                        "duration": walk_min,
                    }
                    marked_stops.add(target_norm)

            # 2. Intra-station platform transfers
            trans_info = resolve_transfer_duration("rail", stop_norm, "rail", stop_norm)
            if trans_info:
                dur, kind, _ = trans_info
                plat_arr = curr_arr + dur
                if plat_arr < tau_star.get(stop_norm, infinity):
                    tau[k][stop_norm] = plat_arr
                    tau_star[stop_norm] = plat_arr

        if not marked_stops:
            break

    # Reconstruct best path reaching destination
    best_final_arrival = infinity
    best_egress_info: Optional[Tuple[int, str, str, int]] = (
        None  # (round_k, stop_norm, dest_id, walk_min)
    )

    for k in range(1, max_rounds + 1):
        for source_type, source_id, _, _, walk_min, _ in dest_walks:
            s_norm = normalise_id(source_id)
            if s_norm in tau[k]:
                total_arr = tau[k][s_norm] + walk_min
                if total_arr < best_final_arrival:
                    best_final_arrival = total_arr
                    best_egress_info = (k, s_norm, source_id, walk_min)

    if best_egress_info is None or best_final_arrival >= infinity:
        return None

    # Backtrack legs
    target_round, curr_stop, egress_stop_id, egress_walk_min = best_egress_info
    dest_name = resolve_endpoint_name(t_type, t_id)
    legs_backtracked: List[ItineraryLeg] = []

    # Add egress walk leg if non-zero
    if egress_walk_min > 0 or normalise_id(egress_stop_id) != normalise_id(t_id):
        arr_s = format_minutes_to_time(best_final_arrival)
        dep_s = format_minutes_to_time(best_final_arrival - egress_walk_min)
        legs_backtracked.append(
            ItineraryLeg(
                leg_index=999,
                mode="walk",
                origin=ItineraryEndpoint(
                    id=egress_stop_id,
                    name=resolve_endpoint_name(t_type, egress_stop_id),
                ),
                destination=ItineraryEndpoint(id=t_id, name=dest_name),
                dep_time=dep_s,
                arr_time=arr_s,
                duration_minutes=egress_walk_min,
            )
        )

    # Trace backward through rounds
    r = target_round
    curr = curr_stop
    slack_minutes_list: List[int] = []

    while r >= 0 and curr:
        p = leg_pointer[r].get(curr)
        if not p:
            break

        mode = p.get("mode", "walk")
        dep_t = p.get("dep_time", 0)
        arr_t = p.get("arr_time", 0)
        dur = p.get("duration", 0)

        if mode == "walk":
            # Origin walk leg
            if dur > 0 or normalise_id(p.get("from_id", "")) != normalise_id(
                p.get("to_id", "")
            ):
                legs_backtracked.append(
                    ItineraryLeg(
                        leg_index=0,
                        mode="walk",
                        origin=ItineraryEndpoint(
                            id=p.get("from_id", ""), name=p.get("from_name", "")
                        ),
                        destination=ItineraryEndpoint(
                            id=p.get("to_id", ""), name=p.get("to_name", "")
                        ),
                        dep_time=format_minutes_to_time(dep_t),
                        arr_time=format_minutes_to_time(arr_t),
                        duration_minutes=dur,
                    )
                )
            break
        elif mode == "interchange":
            legs_backtracked.append(
                ItineraryLeg(
                    leg_index=0,
                    mode="interchange",
                    origin=ItineraryEndpoint(
                        id=p.get("from_stop", ""), name=p.get("from_name", "")
                    ),
                    destination=ItineraryEndpoint(
                        id=p.get("to_stop", ""), name=p.get("to_name", "")
                    ),
                    dep_time=format_minutes_to_time(dep_t),
                    arr_time=format_minutes_to_time(arr_t),
                    duration_minutes=dur,
                )
            )
            curr = normalise_id(p.get("from_stop", ""))
        else:
            # Transit leg
            legs_backtracked.append(
                ItineraryLeg(
                    leg_index=0,
                    mode=mode,
                    origin=ItineraryEndpoint(
                        id=p.get("from_stop", ""), name=p.get("from_name", "")
                    ),
                    destination=ItineraryEndpoint(
                        id=p.get("to_stop", ""), name=p.get("to_name", "")
                    ),
                    dep_time=format_minutes_to_time(dep_t),
                    arr_time=format_minutes_to_time(arr_t),
                    duration_minutes=dur,
                    line=p.get("line"),
                    operator=p.get("operator"),
                    headsign=p.get("headsign"),
                    stops_count=p.get("stops_count"),
                    timetable_id=p.get("timetable_id"),
                )
            )
            curr = normalise_id(p.get("from_stop", ""))
            r -= 1

    legs_backtracked.reverse()

    # Re-index legs and compute slack
    final_legs: List[ItineraryLeg] = []
    for idx, leg in enumerate(legs_backtracked, start=1):
        leg.leg_index = idx
        final_legs.append(leg)

    if not final_legs:
        return None

    # Calculate transfer slack
    for i in range(len(final_legs) - 1):
        l1 = final_legs[i]
        l2 = final_legs[i + 1]
        l1_arr = parse_time_to_minutes(l1.arr_time) or 0
        l2_dep = parse_time_to_minutes(l2.dep_time) or 0
        slack = l2_dep - l1_arr
        if l1.mode != "walk" or l2.mode != "walk":
            slack_minutes_list.append(slack)

    min_slack = min(slack_minutes_list) if slack_minutes_list else 10
    if min_slack >= 6:
        robustness = f"High (+{min_slack} min transfer slack)"
    elif min_slack >= 2:
        robustness = f"Moderate (+{min_slack} min transfer slack)"
    else:
        robustness = f"Tight (+{min_slack} min transfer slack)"

    initial_dep_str = final_legs[0].dep_time
    final_arr_str = final_legs[-1].arr_time
    dep_m = parse_time_to_minutes(initial_dep_str) or 0
    arr_m = parse_time_to_minutes(final_arr_str) or 0
    total_dur = max(1, arr_m - dep_m)
    transfers = (
        sum(
            1
            for leg in final_legs
            if leg.mode in ("bus", "rail", "metro", "tram", "ferry")
        )
        - 1
    )

    return ScheduledItinerary(
        departure_time=initial_dep_str,
        arrival_time=final_arr_str,
        total_duration_minutes=total_dur,
        transfers_count=max(0, transfers),
        robustness_score=robustness,
        legs=final_legs,
    )
