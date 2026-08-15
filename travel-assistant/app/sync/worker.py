"""Background worker daemon thread for automated periodic transit data updates."""

import logging
import threading
from typing import Optional
from flask import Flask

from app.sync.transit_sync import check_and_run_background_sync

logger = logging.getLogger(__name__)


class TransitBackgroundWorker:
    """Background daemon thread that periodically checks and updates transit datasets."""

    def __init__(
        self,
        app: Flask,
        check_interval_seconds: int = 3600,
        initial_delay_seconds: float = 2.0,
        max_age_seconds: int = 86400,
    ) -> None:
        self.app = app
        self.check_interval_seconds = max(1, check_interval_seconds)
        self.initial_delay_seconds = max(0.0, initial_delay_seconds)
        self.max_age_seconds = max_age_seconds
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the background worker thread if not already running."""
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="TransitBackgroundWorker",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Transit background worker started (interval=%ds, max_age=%ds).",
            self.check_interval_seconds,
            self.max_age_seconds,
        )

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the worker to stop and wait for completion."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            logger.info("Transit background worker stopped.")
        self._thread = None

    def is_running(self) -> bool:
        """Check if worker thread is actively running."""
        return self._thread is not None and self._thread.is_alive()

    def _run_loop(self) -> None:
        """Worker loop running periodic checks within the Flask application context."""
        # Initial delay before first check
        if self.initial_delay_seconds > 0:
            if self._stop_event.wait(timeout=self.initial_delay_seconds):
                return

        while not self._stop_event.is_set():
            try:
                with self.app.app_context():
                    logger.debug("Executing scheduled transit dataset freshness check.")
                    result = check_and_run_background_sync(
                        app=self.app,
                        max_age_seconds=self.max_age_seconds,
                    )
                    logger.debug(
                        "Transit check complete: triggered=%d",
                        result.get("triggered_count", 0),
                    )
            except Exception as exc:
                logger.error("Error during scheduled transit update: %s", exc)

            # Wait for the next check interval or until stopped
            if self._stop_event.wait(timeout=self.check_interval_seconds):
                break


_worker_instance: Optional[TransitBackgroundWorker] = None
_worker_lock = threading.Lock()


def start_background_worker(
    app: Flask,
    check_interval_seconds: int = 3600,
    initial_delay_seconds: float = 2.0,
    max_age_seconds: int = 86400,
) -> Optional[TransitBackgroundWorker]:
    """Initialise and start the global background worker."""
    global _worker_instance
    with _worker_lock:
        if _worker_instance is not None and _worker_instance.is_running():
            return _worker_instance

        # Do not start background daemon in test environments unless explicitly forced
        if app.config.get("TESTING") or app.config.get(
            "DISABLE_BACKGROUND_WORKER", False
        ):
            return None

        _worker_instance = TransitBackgroundWorker(
            app=app,
            check_interval_seconds=check_interval_seconds,
            initial_delay_seconds=initial_delay_seconds,
            max_age_seconds=max_age_seconds,
        )
        _worker_instance.start()
        return _worker_instance


def stop_background_worker(timeout: float = 5.0) -> None:
    """Stop and cleanup the global background worker."""
    global _worker_instance
    with _worker_lock:
        if _worker_instance is not None:
            _worker_instance.stop(timeout=timeout)
            _worker_instance = None


def get_background_worker() -> Optional[TransitBackgroundWorker]:
    """Retrieve the current background worker instance."""
    return _worker_instance
