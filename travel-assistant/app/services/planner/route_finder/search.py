"""Corridor path discovery and transit continuity edge resolution."""

from __future__ import annotations

import itertools
import logging
from typing import Any, List, Set, Tuple

import networkx as nx

from app.services.planner.exceptions import NoCorridorPathError
from app.services.planner.route_finder.helpers import make_node_key
from app.services.planner.route_finder.validator import RouteValidationResult

logger = logging.getLogger(__name__)


def resolve_edge_sequences_for_path(
    G: nx.MultiDiGraph,
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


def find_candidate_edge_sequences(
    G: nx.MultiDiGraph,
    simple_g: nx.DiGraph,
    val: RouteValidationResult,
    max_routes: int = 50,
) -> List[List[Tuple[str, str, Any]]]:
    """Discover candidate edge paths through transit network between origin and destination.

    Args:
        G: Complete multi-modal MultiDiGraph.
        simple_g: Simplified weighted DiGraph.
        val: Validated route request container.
        max_routes: Maximum number of route templates to target.

    Returns:
        List of edge sequences represented as (u, v, edge_key) tuples.

    Raises:
        NoCorridorPathError: When no graph path connects origin to destination.
    """
    origin_node = val.origin_node
    dest_node = val.dest_node

    if not nx.has_path(G, origin_node, dest_node):
        raise NoCorridorPathError(
            f"No transit corridor exists connecting '{val.from_id}' to '{val.to_id}' on {val.active_days}.",
            {
                "from_id": val.from_id,
                "to_id": val.to_id,
                "active_days": val.active_days,
                "active_timetables_count": len(val.active_timetables),
            },
        )

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
    origin_targets = {
        make_node_key(w[2], w[3]) for w in val.origin_walks if len(w) >= 4
    }
    dest_sources = {make_node_key(w[0], w[1]) for w in val.dest_walks if len(w) >= 2}

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
            f"No viable corridor paths found connecting '{val.from_id}' to '{val.to_id}'.",
            {"from_id": val.from_id, "to_id": val.to_id},
        )

    logger.info(
        "Corridor search found %d raw candidate paths (%d unique node sequences) for %s:%s -> %s:%s",
        len(raw_node_paths),
        len(node_paths),
        val.from_type,
        val.from_id,
        val.to_type,
        val.to_id,
    )

    paths: List[List[Tuple[str, str, Any]]] = []
    for np in node_paths:
        seqs = resolve_edge_sequences_for_path(G, np)
        paths.extend(seqs)

    return paths
