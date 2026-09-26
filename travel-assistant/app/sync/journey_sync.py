"""Journey route calculation synchronisation manager.

Identifies configured journeys without calculated routes, executes multi-modal
topological route discovery (Mode 1), and persists discovered route templates.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from flask import Flask

from app.models import Journey
from app.services.corridor_learner import CorridorLearner
from app.sync.common import run_sync_task

logger = logging.getLogger(__name__)


def sync_journey_routes(
    app: Optional[Flask] = None, force: bool = False
) -> Dict[str, Any]:
    """Discover and populate calculated route templates for pending journeys.

    Queries journeys where ``calculated_routes`` is NULL (or all journeys if ``force=True``),
    performs corridor discovery via Google Routes API, and persists discovered templates.

    Args:
        app: Optional Flask application context.
        force: If True, recalculates routes for all journeys regardless of existing routes.

    Returns:
        Standardised sync telemetry dictionary.
    """

    def _perform_sync() -> int:
        if force:
            pending_journeys = list(Journey.select())
        else:
            pending_journeys = list(
                Journey.select().where(Journey.calculated_routes.is_null())
            )
        if not pending_journeys:
            logger.info("No pending journeys requiring route calculation.")
            return 0

        logger.info(
            "Evaluating multi-modal transit corridors for %d pending journey(s)...",
            len(pending_journeys),
        )
        calculated_count = 0
        learner = CorridorLearner()
        for journey in pending_journeys:
            try:
                discovered_routes = learner.discover_and_persist_corridors(
                    journey,
                    query_type="initial_discovery",
                    trigger_reason="automated_journey_sync",
                    replace_existing=force,
                )
                if discovered_routes:
                    calculated_count += 1
                    logger.info(
                        "Successfully discovered %d corridor(s) for journey %d ('%s').",
                        len(discovered_routes),
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
                        "No viable corridors could be discovered for journey %d ('%s') between %s and %s.",
                        journey.id,
                        journey.name,
                        orig_str,
                        dest_str,
                    )
            except Exception as exc:
                logger.warning(
                    "Unexpected error discovering corridors for journey %d ('%s'): %s",
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
    "sync_journey_routes",
]
