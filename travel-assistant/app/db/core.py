"""Database connection lifecycle, Peewee SQLite management, and schema initialisation."""

import os
from typing import Any, Dict, List, Optional
from flask import Flask, current_app
from peewee import DatabaseProxy, SqliteDatabase
from playhouse.flask_utils import FlaskDB
from playhouse.migrate import SqliteMigrator

# Global database proxy for model bindings
db = DatabaseProxy()
flask_db = FlaskDB()

SQLITE_PRAGMAS = {
    "journal_mode": "wal",
    "foreign_keys": 1,
    "busy_timeout": 5000,
    "cache_size": -1024 * 64,  # 64MB cache
}

SYNCABLE_TABLE_NAMES = ("bus_routes", "bus_stops", "stations")


def format_file_size(size_bytes: int) -> str:
    """Format raw byte size into a human-readable British English string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def get_db_path(app: Optional[Flask] = None) -> str:
    """Determine the SQLite database file path."""
    if app is not None and "DATABASE_PATH" in app.config:
        return app.config["DATABASE_PATH"]
    if current_app and "DATABASE_PATH" in current_app.config:
        return current_app.config["DATABASE_PATH"]

    env_path = os.environ.get("DATABASE_PATH")
    if env_path:
        return env_path

    # Home Assistant persistent data directory
    if os.path.exists("/data") and os.access("/data", os.W_OK):
        return "/data/travel_assistant.db"

    # Default to instance directory for local development
    instance_dir = (
        app.instance_path
        if app is not None
        else (current_app.instance_path if current_app else "instance")
    )
    os.makedirs(instance_dir, exist_ok=True)
    return os.path.join(instance_dir, "travel_assistant.db")


def create_sqlite_database(db_path: str) -> SqliteDatabase:
    """Create a configured SqliteDatabase instance with WAL pragmas."""
    if db_path != ":memory:":
        parent_dir = os.path.dirname(db_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

    return SqliteDatabase(
        db_path,
        pragmas=SQLITE_PRAGMAS,
        thread_safe=True,
        autoconnect=True,
    )


def run_migrations(database: SqliteDatabase) -> None:
    """Execute schema migrations using SqliteMigrator if needed."""
    from app.models.setting import Setting
    from app.models.timetable import Timetable
    from app.models.transfer import LocationTransfer, PlatformTransfer
    from app.models.transit import BusRoute, BusStop, Station, SyncMetadata

    all_models = [
        Setting,
        Timetable,
        SyncMetadata,
        BusRoute,
        BusStop,
        Station,
        LocationTransfer,
        PlatformTransfer,
    ]

    with database.bind_ctx(all_models):
        database.create_tables(all_models, safe=True)

    # Migrator instance for future column alterations
    _ = SqliteMigrator(database)


def init_db(app: Optional[Flask] = None) -> SqliteDatabase:
    """Initialise database, configure proxy, and create schema tables."""
    db_path = get_db_path(app)
    sqlite_db = create_sqlite_database(db_path)
    db.initialize(sqlite_db)
    run_migrations(sqlite_db)
    if not sqlite_db.is_closed():
        sqlite_db.close()
    return sqlite_db


def init_app(app: Flask) -> None:
    """Register database hooks with the Flask application."""
    sqlite_db = init_db(app)
    app.config["DATABASE"] = sqlite_db

    @app.before_request
    def before_request() -> None:
        if db.obj is not None and db.obj.is_closed():
            db.obj.connect(reuse_if_open=True)

    @app.teardown_request
    def teardown_request(exc: Optional[BaseException] = None) -> None:
        if db.obj is not None and not db.obj.is_closed():
            db.obj.close()


def get_db_stats(app: Optional[Flask] = None) -> Dict[str, Any]:
    """Inspect and return SQLite database storage metrics and table row counts."""
    from app.models.setting import Setting
    from app.models.timetable import Timetable
    from app.models.transfer import LocationTransfer, PlatformTransfer
    from app.models.transit import BusRoute, BusStop, Station, SyncMetadata

    db_path = get_db_path(app)

    # Ensure db proxy is initialized
    if db.obj is None:
        init_db(app)

    database = db.obj

    with database.connection_context():
        cursor = database.execute_sql("PRAGMA page_size")
        page_size_row = cursor.fetchone()
        page_size = page_size_row[0] if page_size_row else 4096

        cursor = database.execute_sql("PRAGMA page_count")
        page_count_row = cursor.fetchone()
        page_count = page_count_row[0] if page_count_row else 0

        # Calculate file size
        if (
            db_path != ":memory:"
            and os.path.exists(db_path)
            and os.path.isfile(db_path)
        ):
            file_size_bytes = os.path.getsize(db_path)
        else:
            file_size_bytes = page_size * page_count

        file_size_formatted = format_file_size(file_size_bytes)

        # Discover all user tables
        cursor = database.execute_sql("""
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name ASC
        """)
        table_rows = cursor.fetchall()

        # Build sync metadata map
        sync_meta_map: Dict[str, Dict[str, Any]] = {}
        has_sync_meta = any(row[0] == "sync_metadata" for row in table_rows)
        if has_sync_meta:
            for meta in SyncMetadata.select():
                sync_meta_map[meta.table_name] = {
                    "last_updated_at": (
                        meta.last_updated_at.isoformat()
                        if meta.last_updated_at
                        else None
                    ),
                    "status": meta.status,
                    "error_message": meta.error_message,
                    "records_count": meta.records_count or 0,
                    "duration_seconds": meta.duration_seconds or 0.0,
                }

        # Model mapping
        model_map = {
            "settings": Setting,
            "timetables": Timetable,
            "sync_metadata": SyncMetadata,
            "bus_routes": BusRoute,
            "bus_stops": BusStop,
            "stations": Station,
            "location_transfers": LocationTransfer,
            "platform_transfers": PlatformTransfer,
        }

        tables: List[Dict[str, Any]] = []
        total_rows = 0

        for row in table_rows:
            table_name = row[0]

            # Row count
            model_cls = model_map.get(table_name)
            if model_cls:
                row_count = model_cls.select().count()
            else:
                c = database.execute_sql(f'SELECT COUNT(*) FROM "{table_name}"')
                row_count = c.fetchone()[0]

            # Columns
            col_cursor = database.execute_sql(f'PRAGMA table_info("{table_name}")')
            columns = [col[1] for col in col_cursor.fetchall()]

            # Determine sync status and last updated
            is_syncable = table_name in SYNCABLE_TABLE_NAMES
            last_updated_at = None
            sync_status = "idle" if is_syncable else "managed"
            error_message = None

            if table_name in sync_meta_map:
                meta_item = sync_meta_map[table_name]
                last_updated_at = meta_item.get("last_updated_at")
                sync_status = meta_item.get("status", "idle")
                error_message = meta_item.get("error_message")
            elif "updated_at" in columns:
                try:
                    ts_cursor = database.execute_sql(
                        f'SELECT MAX(updated_at) FROM "{table_name}"'
                    )
                    ts_row = ts_cursor.fetchone()
                    if ts_row and ts_row[0]:
                        raw_ts = ts_row[0]
                        last_updated_at = (
                            raw_ts.isoformat()
                            if hasattr(raw_ts, "isoformat")
                            else str(raw_ts)
                        )
                except Exception:
                    pass

            total_rows += row_count
            tables.append(
                {
                    "name": table_name,
                    "row_count": row_count,
                    "column_count": len(columns),
                    "columns": columns,
                    "syncable": is_syncable,
                    "last_updated_at": last_updated_at,
                    "sync_status": sync_status,
                    "error_message": error_message,
                }
            )

        return {
            "file_path": db_path,
            "file_size_bytes": file_size_bytes,
            "file_size_formatted": file_size_formatted,
            "page_size": page_size,
            "page_count": page_count,
            "total_tables": len(tables),
            "total_rows": total_rows,
            "tables": tables,
        }
