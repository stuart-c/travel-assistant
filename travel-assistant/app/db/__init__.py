"""Database package for Travel Assistant.

Provides Peewee SQLite database lifecycle management, FlaskDB integration, and schema migrations.
"""

from app.db.core import (
    DEFAULT_VACUUM_FREELIST_THRESHOLD,
    create_sqlite_database,
    db,
    flask_db,
    format_file_size,
    get_db_path,
    get_db_stats,
    get_sync_stats,
    init_app,
    init_db,
    vacuum_database,
)
from app.db.migrations import run_migrations

__all__ = [
    "db",
    "flask_db",
    "init_db",
    "init_app",
    "get_db_path",
    "get_db_stats",
    "get_sync_stats",
    "format_file_size",
    "create_sqlite_database",
    "run_migrations",
    "vacuum_database",
    "DEFAULT_VACUUM_FREELIST_THRESHOLD",
]
