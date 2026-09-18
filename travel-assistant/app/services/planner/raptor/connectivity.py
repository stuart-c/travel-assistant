"""Corridor reachability checking and interchange loading for the RAPTOR engine."""

from __future__ import annotations

from typing import Dict, List, Set, Tuple

from app.models.transit import StopInterchange
from app.models.walking import Walking
from app.services.planner.raptor.models import _ParsedTrip
from app.services.planner.transfers import normalise_id


def _load_interchanges_for_stops(
    stop_ids: Set[str],
) -> Dict[str, List[Tuple[str, int]]]:
    """Retrieve nearby stop interchanges for relevant transit stops using indexed queries.

    Queries StopInterchange in chunked batches to respect SQLite parameter limits and
    yields raw tuples to avoid instantiating Peewee model objects across millions of rows.
    """
    if not stop_ids:
        return {}

    interchanges: Dict[str, List[Tuple[str, int]]] = {}
    candidate_stops = list(stop_ids)
    batch_size = 500

    for i in range(0, len(candidate_stops), batch_size):
        chunk = candidate_stops[i : i + batch_size]
        for f_st, t_st, walk_min in (
            StopInterchange.select(
                StopInterchange.from_stop_atco,
                StopInterchange.to_stop_atco,
                StopInterchange.estimated_walk_minutes,
            )
            .where(StopInterchange.from_stop_atco.in_(chunk))
            .tuples()
        ):
            f_norm = normalise_id(f_st)
            t_norm = normalise_id(t_st)
            interchanges.setdefault(f_norm, []).append((t_norm, walk_min))

    return interchanges


def _check_corridor_connectivity(
    origin_walks: List[Tuple[str, str, str, str, int, str]],
    dest_walks: List[Tuple[str, str, str, str, int, str]],
    trips: List[_ParsedTrip],
) -> bool:
    """Fast topological reachability check from origin access stops to destination access stops.

    Performs a BFS across transit stop sequence transitions, interchanges, and walking links
    to determine if a topological corridor exists without running expensive Yen shortest path routing.
    """
    origin_stops = {normalise_id(w[3]) for w in origin_walks if len(w) >= 4}
    dest_stops = {normalise_id(w[1]) for w in dest_walks if len(w) >= 2}

    if not origin_stops or not dest_stops:
        return False

    # Check for direct overlap (e.g. starting directly at destination stop)
    if origin_stops & dest_stops:
        return True

    # Build adjacency list across all active trips
    adj: Dict[str, Set[str]] = {}
    trip_stops: Set[str] = set()
    for tr in trips:
        for i in range(len(tr.stops) - 1):
            u = normalise_id(tr.stops[i])
            v = normalise_id(tr.stops[i + 1])
            trip_stops.add(u)
            trip_stops.add(v)
            if u != v:
                adj.setdefault(u, set()).add(v)

    # Interchanges for active corridor stops
    relevant_stops = trip_stops | origin_stops | dest_stops
    if relevant_stops:
        rel_list = list(relevant_stops)
        batch_size = 500
        for i in range(0, len(rel_list), batch_size):
            chunk = rel_list[i : i + batch_size]
            for f_st, t_st in (
                StopInterchange.select(
                    StopInterchange.from_stop_atco,
                    StopInterchange.to_stop_atco,
                )
                .where(StopInterchange.from_stop_atco.in_(chunk))
                .tuples()
            ):
                u = normalise_id(f_st)
                v = normalise_id(t_st)
                if u != v:
                    adj.setdefault(u, set()).add(v)

    # Walking links (e.g. transfer between stations)
    for w_start, w_fin, is_bi in Walking.select(
        Walking.start_id, Walking.finish_id, Walking.bidirectional
    ).tuples():
        u = normalise_id(w_start)
        v = normalise_id(w_fin)
        if u != v:
            adj.setdefault(u, set()).add(v)
            if is_bi:
                adj.setdefault(v, set()).add(u)

    # BFS from all origin stops
    queue = list(origin_stops)
    visited = set(origin_stops)

    while queue:
        curr = queue.pop(0)
        for nxt in adj.get(curr, ()):
            if nxt in dest_stops:
                return True
            if nxt not in visited:
                visited.add(nxt)
                queue.append(nxt)

    return False
