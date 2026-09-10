"""Background daemon monitor for detecting Stuart and dispatching departure alerts."""

import datetime
import logging
import threading
from typing import Dict, Optional, Set
from flask import Flask

from app.datasources.homeassistant import HomeAssistantClient
from app.datasources.train_live import TrainLiveClient
from app.models.journey import Journey
from app.services.dispatcher.evaluator import (
    evaluate_journey_notification,
    format_departure_notification,
    is_journey_active_for_datetime,
)
from app.services.dispatcher.proximity import is_person_near_origin
from app.services.dispatcher.tracker import (
    ActiveJourney,
    JourneyStepStatus,
    detect_en_route_journey,
    format_progress_notification,
    update_journey_progress,
)

logger = logging.getLogger(__name__)

_DEFAULT_CHECK_INTERVAL = 30.0
_TARGET_PERSON_ENTITY = "person.stuart"
_TARGET_NOTIFY_SERVICE = "mobile_app_stuart_mobile"


class DepartureMonitor:
    """Continuously running daemon thread evaluating journey departure notifications for Stuart."""

    def __init__(
        self,
        app: Flask,
        check_interval_seconds: float = _DEFAULT_CHECK_INTERVAL,
        target_person: str = _TARGET_PERSON_ENTITY,
        target_notify_service: str = _TARGET_NOTIFY_SERVICE,
    ) -> None:
        self.app = app
        self.check_interval_seconds = max(5.0, check_interval_seconds)
        self.target_person = target_person
        self.target_notify_service = target_notify_service

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.sent_keys: Set[str] = set()
        self.active_journeys: Dict[int, ActiveJourney] = {}
        self._last_clean_date: Optional[datetime.date] = None

    def start(self) -> None:
        """Start the departure monitor background thread."""
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="DepartureMonitor",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Departure monitor started (checking %s every %ds).",
            self.target_person,
            int(self.check_interval_seconds),
        )

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the monitor to stop and wait for completion."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            logger.info("Departure monitor stopped.")
        self._thread = None

    def is_running(self) -> bool:
        """Return True if the monitor daemon thread is currently running."""
        return self._thread is not None and self._thread.is_alive()

    def _cleanup_old_keys_if_needed(self, today: datetime.date) -> None:
        """Purge recorded notification keys from previous days."""
        if self._last_clean_date != today:
            iso_today = today.isoformat()
            self.sent_keys = {k for k in self.sent_keys if iso_today in k}
            self._last_clean_date = today

    def check_and_dispatch(
        self,
        ha_client: Optional[HomeAssistantClient] = None,
        live_client: Optional[TrainLiveClient] = None,
        now: Optional[datetime.datetime] = None,
    ) -> int:
        """Execute a single evaluation pass across all journeys.

        Returns the count of dispatched notifications.
        """
        current_dt = now or datetime.datetime.now()
        self._cleanup_old_keys_if_needed(current_dt.date())

        client = ha_client or HomeAssistantClient.from_settings()
        if not client.token:
            logger.debug(
                "Home Assistant token not configured; skipping departure check."
            )
            return 0

        # Query Stuart's state from Home Assistant Core API
        stuart_state = client.get_entity_state(self.target_person)
        if not stuart_state:
            logger.debug(
                "Could not retrieve state for %s from Home Assistant; skipping check.",
                self.target_person,
            )
            return 0

        train_live = live_client or TrainLiveClient.from_settings()

        dispatched_count = 0

        # 1. Update in-progress journeys first
        completed_or_expired = []
        for journey_id, active in list(self.active_journeys.items()):
            updated = update_journey_progress(
                active=active,
                person_state=stuart_state,
                current_dt=current_dt,
                ha_client=client,
                live_client=train_live,
            )
            if updated:
                dispatched_count += 1
            if active.current_status in (
                JourneyStepStatus.ARRIVED,
                JourneyStepStatus.EXPIRED,
            ):
                completed_or_expired.append(journey_id)

        for j_id in completed_or_expired:
            self.active_journeys.pop(j_id, None)

        # 2. Evaluate departures for journeys not currently in progress
        journeys = list(Journey.select())

        for journey in journeys:
            if journey.id in self.active_journeys:
                continue

            # 2a. Quick check: Is journey scheduled and active right now?
            is_active, _ = is_journey_active_for_datetime(journey, current_dt)
            if not is_active:
                continue

            # 2b. Proximity check: Is Stuart near the journey origin?
            is_near = is_person_near_origin(
                person_state=stuart_state,
                from_type=journey.from_type,
                from_id=journey.from_id,
            )
            if not is_near:
                # 2c. En-route recovery: Detect if Stuart is in transit along journey corridor
                recovered = detect_en_route_journey(
                    journey=journey,
                    person_state=stuart_state,
                    current_dt=current_dt,
                    live_client=train_live,
                )
                if recovered:
                    self.active_journeys[journey.id] = recovered
                    title, message, data = format_progress_notification(recovered)
                    try:
                        sent = client.send_mobile_notification(
                            title=title,
                            message=message,
                            service_name=self.target_notify_service,
                            data=data,
                        )
                        if sent:
                            recovered.last_notification_message = message
                            dispatched_count += 1
                            logger.info(
                                "Recovered en-route active journey %d (%s) for %s at [%s]: %s",
                                journey.id,
                                journey.name,
                                self.target_person,
                                recovered.current_status.value,
                                message,
                            )
                    except Exception as exc:
                        logger.error(
                            "Failed to dispatch en-route recovery notification for journey %d (%s): %s",
                            journey.id,
                            journey.name,
                            exc,
                        )
                else:
                    logger.debug(
                        "Stuart is not near origin %s (%s) for journey %d.",
                        journey.from_id,
                        journey.from_name,
                        journey.id,
                    )
                continue

            # 2c. Evaluate timing and find upcoming candidate
            candidate = evaluate_journey_notification(
                journey=journey,
                dt=current_dt,
                sent_keys=self.sent_keys,
                live_client=train_live,
            )
            if not candidate:
                continue

            # 2d. Format and dispatch notification to Stuart's mobile device
            title, message, data = format_departure_notification(candidate)
            try:
                sent = client.send_mobile_notification(
                    title=title,
                    message=message,
                    service_name=self.target_notify_service,
                    data=data,
                )
                if sent:
                    self.sent_keys.add(candidate.service_key)
                    dispatched_count += 1
                    if candidate.itinerary:
                        active = ActiveJourney(
                            journey_id=journey.id,
                            journey_name=journey.name,
                            from_type=journey.from_type,
                            from_id=journey.from_id,
                            from_name=journey.from_name,
                            to_type=journey.to_type,
                            to_id=journey.to_id,
                            to_name=journey.to_name,
                            itinerary=candidate.itinerary,
                            platform=candidate.platform,
                            last_notification_message=message,
                            started_at=current_dt,
                            expected_arrival_time=candidate.arrival_time,
                        )
                        self.active_journeys[journey.id] = active

                    logger.info(
                        "Dispatched departure alert for journey %d (%s) to %s: %s",
                        journey.id,
                        journey.name,
                        self.target_notify_service,
                        message,
                    )
            except Exception as exc:
                logger.error(
                    "Failed to dispatch departure notification for journey %d (%s): %s",
                    journey.id,
                    journey.name,
                    exc,
                )

        return dispatched_count

    def _run_loop(self) -> None:
        """Daemon worker loop executing check_and_dispatch every check_interval_seconds."""
        while not self._stop_event.is_set():
            try:
                with self.app.app_context():
                    self.check_and_dispatch()
            except Exception as exc:
                logger.error("Unexpected error in departure monitor loop: %s", exc)

            if self._stop_event.wait(timeout=self.check_interval_seconds):
                break


_monitor_instance: Optional[DepartureMonitor] = None
_monitor_lock = threading.Lock()


def start_departure_monitor(
    app: Flask,
    check_interval_seconds: float = _DEFAULT_CHECK_INTERVAL,
) -> DepartureMonitor:
    """Initialise and start the global DepartureMonitor daemon instance."""
    global _monitor_instance
    with _monitor_lock:
        if _monitor_instance is None or not _monitor_instance.is_running():
            _monitor_instance = DepartureMonitor(
                app=app,
                check_interval_seconds=check_interval_seconds,
            )
            _monitor_instance.start()
        return _monitor_instance


def get_departure_monitor() -> Optional[DepartureMonitor]:
    """Retrieve the running DepartureMonitor instance if active."""
    return _monitor_instance
