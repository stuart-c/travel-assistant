"""Journey route calculation synchronisation manager.

Identifies configured journeys without calculated routes, executes multi-modal
topological route discovery (Mode 1), and persists discovered route templates.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from flask import Flask

from app.models import Journey
from app.services.planner import (
    JourneyPlanningError,
    RouteTemplate,
    VALID_DAYS,
    find_routes,
    prune_route_templates,
)
from app.sync.common import run_sync_task

logger = logging.getLogger(__name__)


def calculate_routes_for_journey(journey: Journey) -> Optional[List[RouteTemplate]]:
    """Discover viable multi-modal route templates for a single configured journey.

    Evaluates configured time-setting windows separately if present, or evaluates
    across all standard operating days. Candidate routes across windows are merged
    and pruned.

    Args:
        journey: The Journey model instance to compute routes for.

    Returns:
        List of non-dominated RouteTemplate instances, or None if no routes exist.
    """
    time_windows = journey.get_time_settings()
    candidate_routes: List[RouteTemplate] = []

    if time_windows:
        for tw in time_windows:
            days = tw.get("days", [])
            if not days:
                days = list(VALID_DAYS)
            try:
                routes = find_routes(
                    from_type=journey.from_type,
                    from_id=journey.from_id,
                    to_type=journey.to_type,
                    to_id=journey.to_id,
                    days_of_week=days,
                )
                candidate_routes.extend(routes)
            except JourneyPlanningError as err:
                logger.warning(
                    "No route corridor for journey %d ('%s') on days %s: %s",
                    journey.id,
                    journey.name,
                    days,
                    err.message,
                )
    else:
        try:
            routes = find_routes(
                from_type=journey.from_type,
                from_id=journey.from_id,
                to_type=journey.to_type,
                to_id=journey.to_id,
                days_of_week=list(VALID_DAYS),
            )
            candidate_routes.extend(routes)
        except JourneyPlanningError as err:
            logger.warning(
                "No route corridor for journey %d ('%s') across all days: %s",
                journey.id,
                journey.name,
                err.message,
            )

    if not candidate_routes:
        return None

    pruned = prune_route_templates(candidate_routes, max_routes=50)
    return pruned if pruned else None


def sync_journey_routes(app: Optional[Flask] = None) -> Dict[str, Any]:
    """Discover and populate calculated route templates for all pending journeys.

    Queries all journeys where ``calculated_routes`` is NULL, performs topological
    route discovery, and saves the serialised route templates.

    Args:
        app: Optional Flask application context.

    Returns:
        Standardised sync telemetry dictionary.
    """

    def _perform_sync() -> int:
        pending_journeys = list(
            Journey.select().where(Journey.calculated_routes.is_null())
        )
        if not pending_journeys:
            logger.info("No pending journeys requiring route calculation.")
            return 0

        logger.info(
            "Evaluating multi-modal topological route corridors for %d pending journey(s)...",
            len(pending_journeys),
        )
        calculated_count = 0
        for journey in pending_journeys:
            try:
                routes = calculate_routes_for_journey(journey)
                if routes:
                    serialized_routes = [r.model_dump() for r in routes]
                    journey.set_calculated_routes(serialized_routes)
                    journey.save()
                    calculated_count += 1
                    logger.info(
                        "Successfully calculated %d route(s) for journey %d ('%s').",
                        len(routes),
                        journey.id,
                        journey.name,
                    )
                else:
                    orig_str = (
                        journey.from_id
                        if str(journey.from_id).startswith(f"{journey.from_type}:")
                        else f"{journey.from_type}:{journey.from_id}"
                    )
                    dest_str = (
                        journey.to_id
                        if str(journey.to_id).startswith(f"{journey.to_type}:")
                        else f"{journey.to_type}:{journey.to_id}"
                    )
                    logger.warning(
                        "No viable routes could be calculated for journey %d ('%s') between %s and %s.",
                        journey.id,
                        journey.name,
                        orig_str,
                        dest_str,
                    )
            except Exception as exc:
                logger.warning(
                    "Unexpected error calculating routes for journey %d ('%s'): %s",
                    journey.id,
                    journey.name,
                    exc,
                )

        return calculated_count

    return run_sync_task(
        table_name="journey_routes",
        sync_operation=_perform_sync,
        success_message_factory=lambda cnt: (
            f"Successfully calculated routes for {cnt} journey(s)."
        ),
        app=app,
    )


__all__ = [
    "calculate_routes_for_journey",
    "sync_journey_routes",
]
