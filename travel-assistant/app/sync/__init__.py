"""Synchronisation and background update package for transit datasets."""

from app.sync.ha_sync import sync_ha_locations
from app.sync.transit_sync import (
    sync_bus_routes,
    sync_bus_timetables,
    sync_stop_interchanges,
    sync_stops,
    sync_table,
    sync_train_timetables,
)
from app.sync.journey_sync import sync_journey_routes
from app.sync.walking_sync import sync_walking_routes
from app.sync.worker import (
    SYNC_REGISTRY,
    SyncEntry,
    SyncWorker,
    get_background_worker,
    request_sync,
    start_background_worker,
    stop_background_worker,
)

__all__ = [
    "sync_bus_routes",
    "sync_stop_interchanges",
    "sync_stops",
    "sync_ha_locations",
    "sync_train_timetables",
    "sync_bus_timetables",
    "sync_walking_routes",
    "sync_journey_routes",
    "sync_table",
    "SYNC_REGISTRY",
    "SyncEntry",
    "SyncWorker",
    "start_background_worker",
    "stop_background_worker",
    "get_background_worker",
    "request_sync",
]
