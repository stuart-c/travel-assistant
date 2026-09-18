"""NetworkX transit graph and simplified routing graph construction."""

from __future__ import annotations

import itertools
import logging
from typing import Any, Dict, List, Set, Tuple

import networkx as nx

from app.models.transit import StopInterchange
from app.services.planner.route_finder.helpers import make_node_key
from app.services.planner.route_finder.validator import RouteValidationResult
from app.services.planner.transfers import (
    normalise_id,
    parse_time_to_minutes,
    resolve_endpoint_name,
    resolve_transfer_duration,
)

logger = logging.getLogger(__name__)


def build_transit_graph(
    val: RouteValidationResult,
) -> Tuple[nx.MultiDiGraph, nx.DiGraph]:
    """Construct multi-modal transit graph and weighted simplified search graph.

    Args:
        val: Validated route request container.

    Returns:
        Tuple containing:
            - G: Complete NetworkX MultiDiGraph with detailed leg attributes.
            - simple_g: NetworkX DiGraph with shortest-path heuristic edge weights.
    """
    G = nx.MultiDiGraph()
    origin_node = val.origin_node
    dest_node = val.dest_node

    G.add_node(origin_node, node_type=val.from_type, id=normalise_id(val.from_id))
    G.add_node(dest_node, node_type=val.to_type, id=normalise_id(val.to_id))

    # Add direct walk if present
    if val.direct_walk:
        G.add_edge(
            origin_node,
            dest_node,
            key="direct_walk",
            leg_type="walk",
            transport_mode="walk",
            duration=val.direct_walk.time_needed_minutes,
            distance_m=None,
            timetable_id=None,
            line_name=None,
            operator_name=None,
            stops_count=1,
            from_name=resolve_endpoint_name(val.from_type, val.from_id),
            to_name=resolve_endpoint_name(val.to_type, val.to_id),
        )

    # Add origin walking access edges
    for _, _, target_type, target_id, walk_min, kind in val.origin_walks:
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
                from_name=resolve_endpoint_name(val.from_type, val.from_id),
                to_name=resolve_endpoint_name(target_type, target_id),
            )

    # Add destination walking egress edges
    for source_type, source_id, _, _, walk_min, kind in val.dest_walks:
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
                to_name=resolve_endpoint_name(val.to_type, val.to_id),
            )

    # Add scheduled timetable transit edges
    for tt in val.active_timetables:
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
    all_stop_keys: Set[str] = set()
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

    return G, simple_g
