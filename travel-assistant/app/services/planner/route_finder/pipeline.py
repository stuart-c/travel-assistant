"""Main pipeline orchestrating multi-modal route finding and corridor extraction."""

from __future__ import annotations

import datetime
import logging
from typing import List, Optional, Union

from app.services.planner.models import RouteTemplate
from app.services.planner.route_finder.graph_builder import build_transit_graph
from app.services.planner.route_finder.pruning import prune_route_templates
from app.services.planner.route_finder.search import find_candidate_edge_sequences
from app.services.planner.route_finder.template_assembler import (
    assemble_route_templates,
)
from app.services.planner.route_finder.validator import validate_route_request

logger = logging.getLogger(__name__)


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
        max_stages: Maximum number of modal stages allowed (default: 10).
        max_transfers_per_stage: Maximum transfers within a single modal stage (default: 3).
        max_routes: Maximum number of route templates to return (default: 50).

    Returns:
        List of ranked RouteTemplate objects.

    Raises:
        InvalidEndpointError: If origin or destination endpoints cannot be resolved.
        NoAccessStopsError: If origin or destination has no reachable transit stops.
        NoCorridorPathError: If no continuous corridor connects origin and destination.
    """
    validation = validate_route_request(
        from_type=from_type,
        from_id=from_id,
        to_type=to_type,
        to_id=to_id,
        days_of_week=days_of_week,
        target_date=target_date,
        start_time=start_time,
        end_time=end_time,
        timing_mode=timing_mode,
    )

    G, simple_g = build_transit_graph(validation)

    paths = find_candidate_edge_sequences(
        G=G,
        simple_g=simple_g,
        val=validation,
        max_routes=max_routes,
    )

    candidate_templates = assemble_route_templates(
        G=G,
        paths=paths,
        active_days=validation.active_days,
        max_stages=max_stages,
    )

    logger.info(
        "Assembled %d candidate route templates before pruning for %s:%s -> %s:%s",
        len(candidate_templates),
        validation.from_type,
        validation.from_id,
        validation.to_type,
        validation.to_id,
    )

    pruned_templates = prune_route_templates(candidate_templates, max_routes=max_routes)
    return pruned_templates[:max_routes]
