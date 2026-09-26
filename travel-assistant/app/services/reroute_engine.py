"""Dynamic two-tier rerouting engine for transit delays and service disruptions."""

import datetime
import logging
from typing import List, Optional, Tuple

from app.datasources.google_maps import GoogleMapsClient
from app.datasources.train_live import TrainLiveClient
from app.models.journey import Journey
from app.models.journey_route import JourneyRoute
from app.models.route_query_log import RouteQueryLog
from app.services.corridor_learner import CorridorLearner
from app.services.dispatcher.tracker.models import ActiveJourney
from app.services.dispatcher.tracker.session_store import save_active_journey_session

logger = logging.getLogger(__name__)

DELAY_REROUTE_THRESHOLD_MINUTES = 10


class RerouteEngine:
    """Evaluates and executes two-tier reroutes when transit delays or disruptions occur."""

    def __init__(
        self,
        google_client: Optional[GoogleMapsClient] = None,
        live_client: Optional[TrainLiveClient] = None,
    ) -> None:
        self.google_client = google_client
        self.live_client = live_client
        self.corridor_learner = CorridorLearner(client=google_client)

    def check_disruption_requires_reroute(
        self,
        delay_minutes: int = 0,
        is_cancelled: bool = False,
        connection_severed: bool = False,
    ) -> Tuple[bool, str]:
        """Check whether current delay or disruption metrics satisfy the rerouting threshold.

        Returns:
            Tuple of (requires_reroute, reason_string).
        """
        if is_cancelled:
            return True, "Service cancelled"
        if connection_severed:
            return True, "Transfer connection severed"
        if delay_minutes >= DELAY_REROUTE_THRESHOLD_MINUTES:
            return (
                True,
                f"Delay of {delay_minutes}m exceeds {DELAY_REROUTE_THRESHOLD_MINUTES}m threshold",
            )
        return False, ""

    def evaluate_and_reroute(
        self,
        journey: Journey,
        trigger_reason: str = "delay_ge_10m",
        current_route_id: Optional[int] = None,
        departure_time: Optional[datetime.datetime] = None,
        active_session: Optional[ActiveJourney] = None,
    ) -> Tuple[Optional[JourneyRoute], str]:
        """Execute a two-tier rerouting sequence.

        Tier 1: Check existing secondary JourneyRoute templates for this journey that are not disrupted.
        Tier 2: Invoke Google Routes API for an immediate alternative detour (departure_time=now),
                persist the call to RouteQueryLog, and learn the new detour template into SQLite.

        Args:
            journey: Journey model instance being evaluated.
            trigger_reason: Reason for the reroute (e.g. 'Delay of 14m', 'Service cancelled').
            current_route_id: Optional ID of the currently disrupted route to avoid.
            departure_time: Departure time to evaluate (defaults to now).
            active_session: Optional active in-progress journey tracking session to update.

        Returns:
            Tuple of (selected_journey_route, strategy_used) where strategy is
            'local_failover', 'google_reroute', or 'none'.
        """
        logger.info(
            "Evaluating reroute for journey %d ('%s') due to: %s",
            journey.id,
            journey.name,
            trigger_reason,
        )

        dep_dt = departure_time or datetime.datetime.utcnow()

        # --- Tier 1: Local Failover to Secondary Route Template ---
        local_routes = list(
            JourneyRoute.select().where(
                (JourneyRoute.journey_id == journey.id)
                & (JourneyRoute.is_enabled == True)  # noqa: E712
            )
        )

        candidates: List[JourneyRoute] = [
            r
            for r in local_routes
            if current_route_id is None or r.id != current_route_id
        ]

        if candidates:
            # Pick preferred candidate or first available alternative
            candidates.sort(
                key=lambda r: (not r.is_preferred, r.total_duration_est_minutes)
            )
            selected_local = candidates[0]

            # Mark selected route as preferred
            for r in local_routes:
                r.is_preferred = r.id == selected_local.id
                r.save()

            RouteQueryLog.create(
                journey_id=journey.id,
                query_type="local_failover",
                trigger_reason=trigger_reason,
                origin_lat=0.0,
                origin_lng=0.0,
                dest_lat=0.0,
                dest_lng=0.0,
                departure_time=dep_dt.isoformat(),
                raw_response={"selected_local_route_id": selected_local.id},
                parsed_summary=[
                    {
                        "route_id": selected_local.id,
                        "name": selected_local.name,
                        "strategy": "local_failover",
                    }
                ],
                selected_route_id=selected_local.id,
            )

            self._update_active_session_if_present(active_session, selected_local)
            logger.info(
                "Tier 1 local failover activated route %d ('%s') for journey %d.",
                selected_local.id,
                selected_local.name,
                journey.id,
            )
            return selected_local, "local_failover"

        # --- Tier 2: Dynamic Live Google Routes API Reroute ---
        logger.info(
            "No local alternative routes available for journey %d. Querying Google Routes API for live detour...",
            journey.id,
        )

        new_routes = self.corridor_learner.discover_and_persist_corridors(
            journey=journey,
            query_type="delay_reroute",
            trigger_reason=trigger_reason,
            departure_time=dep_dt,
            replace_existing=False,
        )

        if new_routes:
            chosen_route = new_routes[0]
            chosen_route.is_preferred = True
            chosen_route.save()

            self._update_active_session_if_present(active_session, chosen_route)
            logger.info(
                "Tier 2 Google Routes API detour discovered and activated route %d ('%s') for journey %d.",
                chosen_route.id,
                chosen_route.name,
                journey.id,
            )
            return chosen_route, "google_reroute"

        logger.warning(
            "Reroute evaluation found no viable alternatives for journey %d.",
            journey.id,
        )
        return None, "none"

    def _update_active_session_if_present(
        self,
        active_session: Optional[ActiveJourney],
        new_route: JourneyRoute,
    ) -> None:
        """Update in-progress ActiveJourney session and flush to SQLite database."""
        if not active_session:
            return

        try:
            active_session.delay_reason = f"Rerouted: {new_route.name}"
            active_session.delay_minutes = 0
            # Save updated active session back to settings table in SQLite
            save_active_journey_session(active_session)
        except Exception as exc:
            logger.warning(
                "Could not update active tracking session %d after reroute: %s",
                active_session.journey_id,
                exc,
            )


__all__ = ["DELAY_REROUTE_THRESHOLD_MINUTES", "RerouteEngine"]
