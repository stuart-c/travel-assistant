"""Database package for Travel Assistant.

Provides SQLite lifecycle management and table repositories.
"""

from app.db.core import (
    DEFAULT_SCHEMA,
    SYNCABLE_TABLE_NAMES,
    close_db,
    format_file_size,
    get_db,
    get_db_path,
    get_db_stats,
    init_app,
    init_db,
)
from app.db.settings import SettingsRepository
from app.db.timetables import TimetableRepository
from app.db.transit import (
    BusRouteRepository,
    BusStopRepository,
    StationRepository,
    SyncMetadataRepository,
    SYNCABLE_TABLES,
)

__all__ = [
    "DEFAULT_SCHEMA",
    "SYNCABLE_TABLE_NAMES",
    "SYNCABLE_TABLES",
    "get_db_path",
    "get_db",
    "get_db_stats",
    "format_file_size",
    "close_db",
    "init_db",
    "init_app",
    "SettingsRepository",
    "TimetableRepository",
    "SyncMetadataRepository",
    "BusRouteRepository",
    "BusStopRepository",
    "StationRepository",
]
