"""Background worker daemon thread for automated periodic and on-demand data synchronisation."""

import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
from flask import Flask

from app.models.transit import SyncMetadata
from app.sync.ha_sync import sync_ha_locations
from app.sync.transit_sync import (
    sync_bus_routes,
    sync_bus_timetables,
    sync_stops,
    sync_train_timetables,
)
from app.sync.walking_sync import sync_walking_routes

logger = logging.getLogger(__name__)

_SECONDS_PER_HOUR = 3600
_SECONDS_PER_DAY = 86_400
_SECONDS_PER_WEEK = 604_800
_IDLE_SLEEP_SECONDS = 60


@dataclass
class SyncEntry:
    """A single entry in the background sync registry."""

    table_name: str
    sync_fn: Callable[..., Dict[str, Any]]
    max_age_seconds: int


# Ordered list of sync operations. The loop processes entries in this order on each pass.
# Dependencies are respected: stops must precede timetables, timetables must precede walking.
SYNC_REGISTRY: List[SyncEntry] = [
    SyncEntry("bus_routes", sync_bus_routes, _SECONDS_PER_DAY),
    SyncEntry("stops", sync_stops, _SECONDS_PER_WEEK),
    SyncEntry("ha_locations", sync_ha_locations, _SECONDS_PER_HOUR),
    SyncEntry("train_timetables", sync_train_timetables, _SECONDS_PER_DAY),
    SyncEntry("bus_timetables", sync_bus_timetables, _SECONDS_PER_DAY),
    SyncEntry("walking", sync_walking_routes, _SECONDS_PER_DAY),
]


class SyncWorker:
    """Continuously running background daemon thread that serialises all sync work.

    On each loop pass the worker evaluates each entry in SYNC_REGISTRY in order.
    An entry is executed when either:
    - its ``sync_requested`` flag is set in the database, or
    - its ``last_updated_at`` timestamp is older than ``max_age_seconds``.

    The flag is cleared atomically before each run to deduplicate concurrent requests.
    If a complete pass of the registry runs without executing any sync, the worker
    sleeps for up to ``_IDLE_SLEEP_SECONDS`` seconds.  The sleep is interruptible:
    calling ``request_sync`` signals the wake event so the loop resumes immediately.
    """

    def __init__(
        self,
        app: Flask,
        initial_delay_seconds: float = 2.0,
    ) -> None:
        self.app = app
        self.initial_delay_seconds = max(0.0, initial_delay_seconds)
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the background worker thread if not already running."""
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._wake_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="SyncWorker",
            daemon=True,
        )
        self._thread.start()
        logger.info("Background sync worker started.")

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the worker to stop and wait for completion."""
        self._stop_event.set()
        self._wake_event.set()  # wake immediately so it can exit
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            logger.info("Background sync worker stopped.")
        self._thread = None

    def is_running(self) -> bool:
        """Return True if the worker thread is alive."""
        return self._thread is not None and self._thread.is_alive()

    def wake(self) -> None:
        """Interrupt the idle sleep so the loop evaluates the registry immediately."""
        self._wake_event.set()

    def _run_loop(self) -> None:
        """Worker loop: evaluate SYNC_REGISTRY continuously within the Flask app context."""
        # Brief initial delay to let the application finish starting up
        if self.initial_delay_seconds > 0:
            if self._stop_event.wait(timeout=self.initial_delay_seconds):
                return

        while not self._stop_event.is_set():
            did_work = False

            for entry in SYNC_REGISTRY:
                if self._stop_event.is_set():
                    return

                try:
                    with self.app.app_context():
                        meta = SyncMetadata.get_meta(entry.table_name)
                        flag_set = meta is not None and meta.sync_requested
                        overdue = SyncMetadata.is_due_for_update(
                            entry.table_name,
                            max_age_seconds=entry.max_age_seconds,
                        )

                        if flag_set or overdue:
                            # Clear the flag atomically before running to deduplicate
                            SyncMetadata.clear_sync_requested(entry.table_name)
                            logger.debug(
                                "Running sync for '%s' (flag=%s, overdue=%s).",
                                entry.table_name,
                                flag_set,
                                overdue,
                            )
                            result = entry.sync_fn()
                            logger.debug(
                                "Sync complete for '%s': status=%s, records=%d.",
                                entry.table_name,
                                result.get("status"),
                                result.get("records", 0),
                            )
                            did_work = True

                except Exception as exc:
                    logger.error("Error during sync of '%s': %s", entry.table_name, exc)

            if not did_work:
                # Nothing to do — sleep until woken or the idle timeout expires
                self._wake_event.clear()
                self._wake_event.wait(timeout=_IDLE_SLEEP_SECONDS)


# ---------------------------------------------------------------------------
# Module-level singleton management
# ---------------------------------------------------------------------------

_worker_instance: Optional[SyncWorker] = None
_worker_lock = threading.Lock()


def start_background_worker(
    app: Flask,
    initial_delay_seconds: float = 2.0,
) -> Optional[SyncWorker]:
    """Initialise and start the global background sync worker."""
    global _worker_instance
    with _worker_lock:
        if _worker_instance is not None and _worker_instance.is_running():
            return _worker_instance

        # Do not start background daemon in test environments unless explicitly forced
        if app.config.get("TESTING") or app.config.get(
            "DISABLE_BACKGROUND_WORKER", False
        ):
            return None

        _worker_instance = SyncWorker(
            app=app,
            initial_delay_seconds=initial_delay_seconds,
        )
        _worker_instance.start()
        return _worker_instance


def stop_background_worker(timeout: float = 5.0) -> None:
    """Stop and clean up the global background sync worker."""
    global _worker_instance
    with _worker_lock:
        if _worker_instance is not None:
            _worker_instance.stop(timeout=timeout)
            _worker_instance = None


def get_background_worker() -> Optional[SyncWorker]:
    """Retrieve the current background sync worker instance."""
    return _worker_instance


def request_sync(table_name: str) -> None:
    """Request an immediate sync for the given table.

    Sets the ``sync_requested`` flag in the database so the request survives
    worker restarts, then signals the running worker to wake from its idle sleep.
    This is the single public API for all callers (UI requests, internal sync
    processes) that wish to queue a sync.

    Safe to call even when the worker is not running — the flag will be picked up
    on the next worker start.
    """
    SyncMetadata.request_sync(table_name)
    with _worker_lock:
        if _worker_instance is not None and _worker_instance.is_running():
            _worker_instance.wake()
