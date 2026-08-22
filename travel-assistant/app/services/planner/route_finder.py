"""Topological multi-modal route finder and corridor pruning engine (Mode 1)."""

from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Optional, Set, Union

import networkx as nx

from app.models.timetable import Timetable
from app.models.transit import StopInterchange
from app.models.walking import Walking
from app.services.planner.exceptions import (
    InvalidEndpointError,
    JourneyPlanningError,
    JourneyPlanningErrorCode,
    NoAccessStopsError,
    NoCorridorPathError,
)
from app.services.planner.models import RouteLeg, RouteTemplate
from app.services.planner.transfers import (
    get_access_edges,
    is_timetable_active,
    normalise_id,
    parse_time_to_minutes,
    resolve_active_days_and_date,
    resolve_endpoint_name,
    resolve_transfer_duration,
)

logger = logging.getLogger(__name__)


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
    origin_walks = get_access_edges(f_type, f_id, is_origin=True)
    dest_walks = get_access_edges(t_type, t_id, is_origin=False)

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

        if stage_idx > max_stages + 2:
            continue

        transit_legs_count = sum(
            1 for leg in compressed_legs if leg.leg_type == "transit"
        )
        transfers_count = max(0, transit_legs_count - 1)

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

    pruned_templates = prune_route_templates(candidate_templates)
    return pruned_templates[:max_routes]


def prune_route_templates(
    routes: List[RouteTemplate],
) -> List[RouteTemplate]:
    """Apply the 4 formal pruning and Pareto-optimisation rules."""
    if not routes:
        return []

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

    fastest_duration = min(r.total_duration_est_minutes for r in non_dominated)
    filtered = [
        r
        for r in non_dominated
        if r.total_duration_est_minutes
        <= max(fastest_duration * 1.5, fastest_duration + 30)
    ]

    filtered.sort(key=lambda r: (r.total_duration_est_minutes, r.transfer_count))
    return filtered or non_dominated


__all__ = [
    "find_routes",
    "prune_route_templates",
]
