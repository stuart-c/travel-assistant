"""Background daemon monitor for detecting Stuart and dispatching departure alerts."""

import datetime
import logging
import threading
from typing import Optional, Set
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

        dispatched_count = 0
        journeys = list(Journey.select())

        for journey in journeys:
            # 1. Quick check: Is journey scheduled and active right now?
            is_active, _ = is_journey_active_for_datetime(journey, current_dt)
            if not is_active:
                continue

            # 2. Proximity check: Is Stuart near the journey origin?
            is_near = is_person_near_origin(
                person_state=stuart_state,
                from_type=journey.from_type,
                from_id=journey.from_id,
            )
            if not is_near:
                logger.debug(
                    "Stuart is not near origin %s (%s) for journey %d.",
                    journey.from_id,
                    journey.from_name,
                    journey.id,
                )
                continue

            # 3. Evaluate timing and find upcoming candidate
            candidate = evaluate_journey_notification(
                journey=journey,
                dt=current_dt,
                sent_keys=self.sent_keys,
                live_client=live_client,
            )
            if not candidate:
                continue

            # 4. Format and dispatch notification to Stuart's mobile device
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
