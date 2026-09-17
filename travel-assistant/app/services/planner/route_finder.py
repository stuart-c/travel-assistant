"""Topological multi-modal route finder and corridor pruning engine (Mode 1)."""

from __future__ import annotations

import datetime
import itertools
import logging
from typing import Any, Dict, List, Optional, Set, Tuple, Union

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
    get_active_timetables,
    normalise_id,
    parse_time_to_minutes,
    resolve_active_days_and_date,
    resolve_endpoint_name,
    resolve_transfer_duration,
)

logger = logging.getLogger(__name__)


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


def find_routes(
    from_type: str,
    from_id: str,
    to_type: str,
    to_id: str,
    days_of_week: Optional[List[str]] = None,
    target_date: Optional[Union[datetime.date, str]] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    timing_mode: Optional[str] = None,
    max_stages: int = 10,
    max_transfers_per_stage: int = 3,
    max_routes: int = 50,
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
        start_time: Optional journey start time ("HH:MM").
        end_time: Optional journey end time ("HH:MM").
        timing_mode: Optional journey timing mode ("depart", "arrive", "window").
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

    # 1. Filter Active Timetables
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

    # 2. Access & Egress Footpaths
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

    def make_node_key(node_type: str, raw_id: str) -> str:
        """Create standardised graph node identifier formatted as '{type}:{normalised_id}'."""
        t = str(node_type).strip().lower()
        return f"{t}:{normalise_id(raw_id)}"

    # 3. Build NetworkX Transit Graph
    G = nx.MultiDiGraph()
    origin_node = make_node_key(f_type, f_id)
    dest_node = make_node_key(t_type, t_id)
    G.add_node(origin_node, node_type=f_type, id=normalise_id(f_id))
    G.add_node(dest_node, node_type=t_type, id=normalise_id(t_id))

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
        norm_target_id = normalise_id(target_id)
        target_node = make_node_key(target_type, target_id)
        G.add_node(target_node, node_type=target_type, id=norm_target_id)
        if target_node != origin_node:
            G.add_edge(
                origin_node,
                target_node,
                key=f"walk_orig_{norm_target_id}",
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
        norm_source_id = normalise_id(source_id)
        source_node = make_node_key(source_type, source_id)
        G.add_node(source_node, node_type=source_type, id=norm_source_id)
        if source_node != dest_node:
            G.add_edge(
                source_node,
                dest_node,
                key=f"walk_dest_{norm_source_id}",
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

            u_node = make_node_key(from_st_type, from_st_id)
            v_node = make_node_key(to_st_type, to_st_id)
            G.add_node(u_node, node_type=from_st_type, id=normalise_id(from_st_id))
            G.add_node(v_node, node_type=to_st_type, id=normalise_id(to_st_id))

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
    stops_in_g = {d.get("id") for _, d in G.nodes(data=True) if d.get("id")}
    all_stop_keys = set()
    for sid in stops_in_g:
        if sid:
            all_stop_keys.add(sid)
            all_stop_keys.add(normalise_id(sid))
            all_stop_keys.add(f"atco:{normalise_id(sid)}")
            all_stop_keys.add(f"naptan:{normalise_id(sid)}")

    stop_keys_list = list(all_stop_keys)
    chunk_size = 400
    for i in range(0, len(stop_keys_list), chunk_size):
        chunk = stop_keys_list[i : i + chunk_size]
        interchanges = list(
            StopInterchange.select().where(
                StopInterchange.from_stop_atco.in_(chunk)
                & StopInterchange.to_stop_atco.in_(stop_keys_list)
            )
        )
        for si in interchanges:
            u_node = make_node_key(si.from_stop_type, si.from_stop_atco)
            v_node = make_node_key(si.to_stop_type, si.to_stop_atco)
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
    rail_nodes_by_norm: Dict[str, List[Tuple[Any, str]]] = {}
    for n, d in G.nodes(data=True):
        if d.get("node_type") == "rail":
            node_id = d.get("id", "")
            norm = normalise_id(node_id)
            if norm:
                rail_nodes_by_norm.setdefault(norm, []).append((n, node_id))

    for norm, group in rail_nodes_by_norm.items():
        if len(group) > 1:
            for (u, u_id), (v, v_id) in itertools.permutations(group, 2):
                trans_info = resolve_transfer_duration("rail", u_id, "rail", v_id)
                if trans_info:
                    dur, kind, dist_m = trans_info
                    G.add_edge(
                        u,
                        v,
                        key=f"plat_{u}_{v}",
                        leg_type=kind,
                        transport_mode="walk",
                        duration=dur,
                        distance_m=dist_m,
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

    # Build simple graph with minimum duration weights for shortest path discovery
    simple_g = nx.DiGraph()
    for u, v, k, data in G.edges(keys=True, data=True):
        dur = data.get("duration", 1)
        leg_type = data.get("leg_type", "walk")
        mode = data.get("transport_mode", "walk")
        if leg_type == "transit":
            # In-vehicle transit travel carries fractional weight plus small duration slope
            # Micro-bus hops within an interchange/station complex are heavily penalised to favour walking
            from_nm = (data.get("from_name") or "").lower()
            to_nm = (data.get("to_name") or "").lower()
            is_micro_hop = (
                mode == "bus"
                and dur <= 3
                and (
                    ("bus station" in from_nm and "bus station" in to_nm)
                    or (
                        G.has_node(u)
                        and G.has_node(v)
                        and any(
                            e.get("leg_type") in ("interchange", "platform_transfer")
                            for e in (G.get_edge_data(u, v) or {}).values()
                        )
                    )
                )
            )
            if is_micro_hop:
                w = float(dur) + 30.0
            else:
                w = 0.01 + float(dur) * 0.001
        elif leg_type in ("interchange", "platform_transfer"):
            # Vehicle and station changes carry duration plus a transfer penalty
            w = float(dur) + 12.0
        else:
            w = float(dur)

        if simple_g.has_edge(u, v):
            if w < simple_g[u][v].get("weight", 9999):
                simple_g[u][v]["weight"] = w
        else:
            simple_g.add_edge(u, v, weight=w)

    raw_node_paths: List[List[str]] = []
    try:
        raw_node_paths.extend(
            list(
                itertools.islice(
                    nx.shortest_simple_paths(
                        simple_g, origin_node, dest_node, weight="weight"
                    ),
                    max_routes * 25,
                )
            )
        )
    except Exception as e:
        logger.debug("shortest_simple_paths main exception: %s", e)

    # Dedicated path discovery across each reachable origin access node to destination egress nodes
    origin_targets = {make_node_key(w[2], w[3]) for w in origin_walks if len(w) >= 4}
    dest_sources = {make_node_key(w[0], w[1]) for w in dest_walks if len(w) >= 2}

    if len(raw_node_paths) < max_routes:
        for o_target in origin_targets:
            if len(raw_node_paths) >= max_routes * 5:
                break
            if o_target == origin_node or not simple_g.has_node(o_target):
                continue
            # Search directly from access stop to dest_node
            if nx.has_path(simple_g, o_target, dest_node):
                try:
                    sub_paths = list(
                        itertools.islice(
                            nx.shortest_simple_paths(
                                simple_g, o_target, dest_node, weight="weight"
                            ),
                            25,
                        )
                    )
                    for sp in sub_paths:
                        raw_node_paths.append([origin_node] + sp)
                except Exception:
                    pass
            # Search from access stop to destination access stops
            for d_source in dest_sources:
                if len(raw_node_paths) >= max_routes * 5:
                    break
                if d_source in (dest_node, o_target) or not simple_g.has_node(d_source):
                    continue
                if nx.has_path(simple_g, o_target, d_source):
                    try:
                        sub_paths = list(
                            itertools.islice(
                                nx.shortest_simple_paths(
                                    simple_g, o_target, d_source, weight="weight"
                                ),
                                15,
                            )
                        )
                        for sp in sub_paths:
                            raw_node_paths.append([origin_node] + sp + [dest_node])
                    except Exception:
                        pass

    # Deduplicate node paths
    seen_node_paths: Set[Tuple[str, ...]] = set()
    node_paths: List[List[str]] = []
    for np in raw_node_paths:
        t_np = tuple(np)
        if t_np not in seen_node_paths:
            seen_node_paths.add(t_np)
            node_paths.append(np)

    if not node_paths:
        try:
            node_path = nx.shortest_path(G, origin_node, dest_node)
            node_paths = [node_path]
        except Exception:
            node_paths = []

    if not node_paths:
        raise NoCorridorPathError(
            f"No viable corridor paths found connecting '{f_id}' to '{t_id}'.",
            {"from_id": f_id, "to_id": t_id},
        )

    logger.info(
        "Corridor search found %d raw candidate paths (%d unique node sequences) for %s:%s -> %s:%s",
        len(raw_node_paths),
        len(node_paths),
        f_type,
        f_id,
        t_type,
        t_id,
    )

    def _resolve_edge_sequences_for_path(
        np: List[str],
    ) -> List[List[Tuple[str, str, Any]]]:
        """Expand a node path into candidate edge sequences preserving transit continuity."""
        resolved_sequences: List[List[Tuple[str, str, Any]]] = [[]]

        for i in range(len(np) - 1):
            u, v = np[i], np[i + 1]
            edge_data_dict = G.get_edge_data(u, v) or {}
            if not edge_data_dict:
                return []

            next_sequences: List[List[Tuple[str, str, Any]]] = []
            for seq in resolved_sequences:
                prev_tt_id = None
                if seq:
                    last_u, last_v, last_k = seq[-1]
                    last_edge_attr = G.edges[last_u, last_v, last_k]
                    if last_edge_attr.get("leg_type") == "transit":
                        prev_tt_id = last_edge_attr.get("timetable_id")

                matching_tt_keys = [
                    k
                    for k, attr in edge_data_dict.items()
                    if prev_tt_id is not None and attr.get("timetable_id") == prev_tt_id
                ]

                if matching_tt_keys:
                    chosen_key = matching_tt_keys[0]
                    next_sequences.append(seq + [(u, v, chosen_key)])
                else:
                    distinct_edge_keys = []
                    seen_line_keys = set()
                    for k, attr in edge_data_dict.items():
                        tt_id = attr.get("timetable_id")
                        line = attr.get("line_name")
                        mode = attr.get("transport_mode")
                        l_key = (attr.get("leg_type"), mode, tt_id, line)
                        if l_key not in seen_line_keys:
                            seen_line_keys.add(l_key)
                            distinct_edge_keys.append(k)

                    def _forward_coverage(key: Any) -> int:
                        attr = edge_data_dict[key]
                        target_tt = attr.get("timetable_id")
                        if target_tt is None:
                            return 0
                        cov = 0
                        for f_idx in range(i + 1, len(np) - 1):
                            f_u, f_v = np[f_idx], np[f_idx + 1]
                            f_edges = G.get_edge_data(f_u, f_v) or {}
                            if any(
                                e_attr.get("timetable_id") == target_tt
                                for e_attr in f_edges.values()
                            ):
                                cov += 1
                            else:
                                break
                        return cov

                    distinct_edge_keys.sort(key=_forward_coverage, reverse=True)

                    for k in distinct_edge_keys[:2]:
                        next_sequences.append(seq + [(u, v, k)])

            resolved_sequences = next_sequences[:10]

        return resolved_sequences

    paths: List[List[Tuple[str, str, Any]]] = []
    for np in node_paths:
        seqs = _resolve_edge_sequences_for_path(np)
        paths.extend(seqs)

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

                is_same_service = (
                    current_transit_leg is not None
                    and current_transit_leg.get("transport_mode") == mode
                    and current_transit_leg.get("timetable_id") == tt_id
                    and (
                        line_name is None
                        or current_transit_leg.get("line_name") == line_name
                    )
                )

                if is_same_service:
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
            logger.debug(
                "Rejected candidate path due to stage_idx %d > %d",
                stage_idx,
                max_stages + 2,
            )
            continue

        if not is_valid_leg_sequence(compressed_legs):
            logger.debug(
                "Rejected candidate path due to is_valid_leg_sequence: %s",
                [(leg.leg_type, leg.transport_mode) for leg in compressed_legs],
            )
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

    logger.info(
        "Assembled %d candidate route templates before pruning for %s:%s -> %s:%s",
        len(candidate_templates),
        f_type,
        f_id,
        t_type,
        t_id,
    )

    pruned_templates = prune_route_templates(candidate_templates, max_routes=max_routes)
    return pruned_templates[:max_routes]


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
    2. A maximum of 4 legs of the same transport mode may occur consecutively in a row (up to 3 intra-modal transfers per stage).
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


def prune_route_templates(
    routes: List[RouteTemplate],
    max_routes: int = 50,
) -> List[RouteTemplate]:
    """Apply Pareto optimisation, modal sequence validation, and corridor diversity rules to preserve distinct viable route options."""
    if not routes:
        return []

    valid_routes = [r for r in routes if is_valid_leg_sequence(r.legs)]
    if not valid_routes:
        return []

    unique_routes: List[RouteTemplate] = []
    seen_signatures: Set[str] = set()

    for r in valid_routes:
        sig_elements = []
        for leg in r.legs:
            sig_elements.append(
                f"{leg.leg_type}:{leg.from_id}->{leg.to_id}:{leg.timetable_id or leg.line_name or ''}"
            )
        signature = "|".join(sig_elements)
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        unique_routes.append(r)

    # Group by corridor fingerprint: (access_stop, first_transit, rail_corridor, last_transit, egress_stop)
    corridor_best: Dict[Tuple[str, str, str, str, str], RouteTemplate] = {}
    for r in unique_routes:
        transit_legs = [leg for leg in r.legs if leg.leg_type == "transit"]
        first_transit = (
            transit_legs[0].line_name or str(transit_legs[0].timetable_id)
            if transit_legs
            else "walk"
        )
        last_transit = (
            transit_legs[-1].line_name or str(transit_legs[-1].timetable_id)
            if transit_legs
            else "walk"
        )
        rail_legs = [leg for leg in transit_legs if leg.transport_mode == "rail"]
        rail_corridor = (
            " -> ".join(f"{leg.from_name} to {leg.to_name}" for leg in rail_legs)
            if rail_legs
            else "no_rail"
        )
        access_stop = (
            normalise_id(r.legs[0].to_id)
            if len(r.legs) > 1 and r.legs[0].leg_type == "walk"
            else "direct"
        )
        egress_stop = (
            normalise_id(r.legs[-1].from_id)
            if len(r.legs) > 1 and r.legs[-1].leg_type == "walk"
            else "direct"
        )
        fp = (access_stop, first_transit, rail_corridor, last_transit, egress_stop)

        if fp not in corridor_best or (
            r.transfer_count,
            r.total_duration_est_minutes,
        ) < (
            corridor_best[fp].transfer_count,
            corridor_best[fp].total_duration_est_minutes,
        ):
            corridor_best[fp] = r

    diverse_candidates = list(corridor_best.values())

    fastest_duration = min(r.total_duration_est_minutes for r in unique_routes)
    max_acceptable_duration = max(fastest_duration * 1.6, fastest_duration + 45)

    filtered = [
        r
        for r in diverse_candidates
        if r.total_duration_est_minutes <= max_acceptable_duration
    ]

    excluded_count = len(diverse_candidates) - len(filtered)

    filtered.sort(
        key=lambda r: (
            r.transfer_count,
            r.total_duration_est_minutes,
            r.stages_count,
        )
    )

    final_routes = (filtered or unique_routes)[:max_routes]

    logger.info(
        "Route pruning results: %d raw options -> %d unique -> %d corridor options (%d excluded by duration threshold <= %dm) -> returning %d best options (limit: %d)",
        len(routes),
        len(unique_routes),
        len(diverse_candidates),
        excluded_count,
        int(max_acceptable_duration),
        len(final_routes),
        max_routes,
    )

    return final_routes


__all__ = [
    "extract_route_base_name",
    "find_routes",
    "get_leg_mode",
    "is_valid_leg_sequence",
    "prune_route_templates",
    "timetable_operates_in_window",
]
