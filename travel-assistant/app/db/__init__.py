"""Database package for Travel Assistant.

Provides Peewee SQLite database lifecycle management, FlaskDB integration, and schema migrations.
"""

from app.db.core import (
    SYNCABLE_TABLE_NAMES,
    create_sqlite_database,
    db,
    flask_db,
    format_file_size,
    get_db_path,
    get_db_stats,
    init_app,
    init_db,
    run_migrations,
)
from app.models import (
    ALL_MODELS,
    BaseModel,
    BusRoute,
    Journey,
    LocationTransfer,
    PlatformTransfer,
    Setting,
    Stop,
    SyncMetadata,
    Timetable,
)

SYNCABLE_TABLES = SYNCABLE_TABLE_NAMES

__all__ = [
    "db",
    "flask_db",
    "init_db",
    "init_app",
    "get_db_path",
    "get_db_stats",
    "format_file_size",
    "create_sqlite_database",
    "run_migrations",
    "SYNCABLE_TABLE_NAMES",
    "SYNCABLE_TABLES",
    "ALL_MODELS",
    "BaseModel",
    "Setting",
    "Timetable",
    "Journey",
    "BusRoute",
    "Stop",
    "SyncMetadata",
    "LocationTransfer",
    "PlatformTransfer",
]
