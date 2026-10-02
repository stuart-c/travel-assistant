"""Corridor reachability checking and interchange loading for the RAPTOR engine."""

from __future__ import annotations

from typing import Dict, List, Set, Tuple

from app.models.walking import Walking
from app.services.planner.raptor.models import _ParsedTrip
from app.services.planner.transfers import normalise_id


def _load_interchanges_for_stops(
    stop_ids: Set[str],
) -> Dict[str, List[Tuple[str, int]]]:
    """Retrieve walking transfers for relevant transit stops from Walking model."""
    if not stop_ids:
        return {}

    interchanges: Dict[str, List[Tuple[str, int]]] = {}
    candidate_stops = [normalise_id(s) for s in stop_ids]

    for w_start, w_fin, dur in (
        Walking.select(
            Walking.start_id,
            Walking.finish_id,
            Walking.time_needed_minutes,
        )
        .where(
            Walking.start_id.in_(candidate_stops)
            | Walking.finish_id.in_(candidate_stops)
        )
        .tuples()
    ):
        f_norm = normalise_id(w_start)
        t_norm = normalise_id(w_fin)
        walk_min = max(1, int(dur or 1))
        if f_norm in candidate_stops:
            interchanges.setdefault(f_norm, []).append((t_norm, walk_min))
        if t_norm in candidate_stops:
            interchanges.setdefault(t_norm, []).append((f_norm, walk_min))

    return interchanges


def _check_corridor_connectivity(
    origin_walks: List[Tuple[str, str, str, str, int, str]],
    dest_walks: List[Tuple[str, str, str, str, int, str]],
    trips: List[_ParsedTrip],
) -> bool:
    """Fast topological reachability check from origin access stops to destination access stops.

    Performs a BFS across transit stop sequence transitions and walking links
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
