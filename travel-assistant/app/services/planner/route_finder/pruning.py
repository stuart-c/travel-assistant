"""Corridor diversity pruning, Pareto filtering, and ranking for route templates."""

from __future__ import annotations

import logging
from typing import Dict, List, Set, Tuple

from app.services.planner.models import RouteTemplate
from app.services.planner.route_finder.helpers import is_valid_leg_sequence
from app.services.planner.transfers import normalise_id

logger = logging.getLogger(__name__)


def prune_route_templates(
    routes: List[RouteTemplate],
    max_routes: int = 50,
) -> List[RouteTemplate]:
    """Apply Pareto optimisation, modal sequence validation, and corridor diversity rules.

    Preserves distinct viable route options while pruning dominated, overly slow, or
    redundant paths.

    Args:
        routes: List of candidate RouteTemplate instances.
        max_routes: Maximum number of route templates to return.

    Returns:
        List of filtered and ranked RouteTemplate instances.
    """
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
        "Route pruning results: %d raw options -> %d unique -> %d corridor options "
        "(%d excluded by duration threshold <= %dm) -> returning %d best options (limit: %d)",
        len(routes),
        len(unique_routes),
        len(diverse_candidates),
        excluded_count,
        int(max_acceptable_duration),
        len(final_routes),
        max_routes,
    )

    return final_routes
