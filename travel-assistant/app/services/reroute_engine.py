"""Dynamic rerouting engine for transit delays and service disruptions."""

from __future__ import annotations

import datetime
import logging
from typing import Optional, Tuple

from app.datasources.bus_live import BodsLiveClient
from app.datasources.google_maps import GoogleMapsClient
from app.datasources.train_live import TrainLiveClient
from app.models.journey import Journey
from app.models.route_query_log import RouteQueryLog
from app.services.dispatcher.tracker.models import ActiveJourney
from app.services.dispatcher.tracker.session_store import save_active_journey_session
from app.services.planner.dynamic_planner import DynamicRoutePlanner
from app.services.planner.models import ScheduledItinerary
from app.utils.geo import resolve_endpoint_coordinates

logger = logging.getLogger(__name__)

DELAY_REROUTE_THRESHOLD_MINUTES = 10
CONNECTION_BREAK_THRESHOLD_MINUTES = 5


class RerouteEngine:
    """Evaluates and executes dynamic real-time reroutes when transit delays or disruptions occur."""

    def __init__(
        self,
        google_client: Optional[GoogleMapsClient] = None,
        live_client: Optional[TrainLiveClient] = None,
        bus_live_client: Optional[BodsLiveClient] = None,
        dynamic_planner: Optional[DynamicRoutePlanner] = None,
    ) -> None:
        self.google_client = google_client
        self.live_client = live_client
        self.bus_live_client = bus_live_client
        self.planner = dynamic_planner or DynamicRoutePlanner(
            google_client=google_client,
            train_live_client=live_client,
            bus_live_client=bus_live_client,
        )

    def get_thresholds(self) -> Tuple[int, int]:
        """Return (delay_threshold, connection_threshold) factoring in reroute_sensitivity setting."""
        try:
            from app.models.setting import Setting

            sens = Setting.get_val("reroute_sensitivity", "medium")
        except Exception:
            sens = "medium"

        sens = str(sens or "medium").lower().strip()
        if sens == "high":
            return 5, 3
        elif sens == "low":
            return 15, 10
        return DELAY_REROUTE_THRESHOLD_MINUTES, CONNECTION_BREAK_THRESHOLD_MINUTES

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
        delay_thresh, conn_thresh = self.get_thresholds()
        if is_cancelled:
            return True, "Service cancelled"
        if connection_severed:
            return True, "Transfer connection severed"
        if delay_minutes >= delay_thresh:
            return (
                True,
                f"Delay of {delay_minutes}m exceeds {delay_thresh}m threshold",
            )
        if delay_minutes >= conn_thresh and connection_severed:
            return (
                True,
                f"Delay of {delay_minutes}m breaks transfer connection",
            )
        return False, ""

    def evaluate_and_reroute(
        self,
        journey: Journey,
        trigger_reason: str = "delay_ge_10m",
        current_route_id: Optional[int] = None,
        departure_time: Optional[datetime.datetime] = None,
        active_session: Optional[ActiveJourney] = None,
        current_lat: Optional[float] = None,
        current_lon: Optional[float] = None,
    ) -> Tuple[Optional[ScheduledItinerary], str]:
        """Execute a dynamic live reroute via Google Routes API and live feeds.

        Args:
            journey: Journey model instance being evaluated.
            trigger_reason: Reason for the reroute (e.g. 'Delay of 14m', 'Service cancelled').
            current_route_id: Unused parameter kept for compatibility.
            departure_time: Departure time to evaluate (defaults to now).
            active_session: Optional active in-progress journey tracking session to update.
            current_lat: Optional commuter latitude if en route.
            current_lon: Optional commuter longitude if en route.

        Returns:
            Tuple of (selected_itinerary, strategy_used) where strategy is
            'dynamic_reroute' or 'none'.
        """
        logger.info(
            "Evaluating dynamic reroute for journey %d ('%s') due to: %s",
            journey.id,
            journey.name,
            trigger_reason,
        )

        dep_dt = departure_time or datetime.datetime.now()

        # Determine origin coordinates
        if current_lat is not None and current_lon is not None:
            orig_lat, orig_lng = current_lat, current_lon
        else:
            orig_lat, orig_lng, _ = resolve_endpoint_coordinates(
                journey.from_type, journey.from_id
            )
        dest_lat, dest_lng, _ = resolve_endpoint_coordinates(
            journey.to_type, journey.to_id
        )

        itineraries = self.planner.plan_transit(
            journey=journey,
            departure_time=dep_dt,
            current_lat=current_lat,
            current_lon=current_lon,
            enrich_live=True,
        )

        if itineraries:
            chosen = itineraries[0]

            # Audit log the routing query
            RouteQueryLog.create(
                journey_id=journey.id,
                query_type="delay_reroute",
                trigger_reason=trigger_reason,
                origin_lat=orig_lat or 0.0,
                origin_lng=orig_lng or 0.0,
                dest_lat=dest_lat or 0.0,
                dest_lng=dest_lng or 0.0,
                departure_time=dep_dt.isoformat(),
                raw_response={"itinerary_departure": chosen.departure_time},
                parsed_summary=[
                    {
                        "departure_time": chosen.departure_time,
                        "arrival_time": chosen.arrival_time,
                        "legs_count": len(chosen.legs),
                        "strategy": "dynamic_reroute",
                    }
                ],
                selected_route_id=None,
            )

            self._update_active_session_if_present(
                active_session, chosen, trigger_reason
            )
            logger.info(
                "Dynamic live detour discovered and activated for journey %d (arr %s).",
                journey.id,
                chosen.arrival_time,
            )
            return chosen, "dynamic_reroute"

        logger.warning(
            "Reroute evaluation found no viable alternatives for journey %d.",
            journey.id,
        )
        return None, "none"

    def _update_active_session_if_present(
        self,
        active_session: Optional[ActiveJourney],
        new_itinerary: ScheduledItinerary,
        trigger_reason: str,
    ) -> None:
        """Update in-progress ActiveJourney session with dynamic detour legs."""
        if not active_session:
            return

        try:
            active_session.itinerary = new_itinerary
            active_session.legs = list(new_itinerary.legs)
            active_session.expected_arrival_time = new_itinerary.arrival_time
            active_session.delay_reason = f"Rerouted: {trigger_reason}"
            active_session.delay_minutes = 0
            save_active_journey_session(active_session)
        except Exception as exc:
            logger.warning(
                "Could not update active tracking session %d after reroute: %s",
                active_session.journey_id,
                exc,
            )


__all__ = [
    "CONNECTION_BREAK_THRESHOLD_MINUTES",
    "DELAY_REROUTE_THRESHOLD_MINUTES",
    "RerouteEngine",
]
