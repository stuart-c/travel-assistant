"""Database package for Travel Assistant.

Provides SQLite lifecycle management and table repositories.
"""

from app.db.core import (
    DEFAULT_SCHEMA,
    close_db,
    get_db,
    get_db_path,
    init_app,
    init_db,
)
from app.db.settings import SettingsRepository
from app.db.timetables import TimetableRepository

__all__ = [
    "DEFAULT_SCHEMA",
    "get_db_path",
    "get_db",
    "close_db",
    "init_db",
    "init_app",
    "SettingsRepository",
    "TimetableRepository",
]
