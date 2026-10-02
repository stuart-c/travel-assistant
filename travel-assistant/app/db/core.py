"""Database connection lifecycle, Peewee SQLite management, and schema initialisation."""

import logging
import os
import time
from typing import Any, Dict, List, Optional
from flask import Flask, current_app
from peewee import DatabaseProxy, SqliteDatabase
from playhouse.flask_utils import FlaskDB

from app.db.migrations import run_migrations

logger = logging.getLogger(__name__)

# Global database proxy for model bindings
db = DatabaseProxy()
flask_db = FlaskDB()

SQLITE_PRAGMAS = {
    "journal_mode": "wal",
    "foreign_keys": 1,
    "busy_timeout": 30000,
    "cache_size": -1024 * 64,  # 64MB cache
}

DEFAULT_VACUUM_FREELIST_THRESHOLD = 500  # pages (~2MB at default 4096B page size)


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
    """Create a configured SqliteDatabase instance with WAL pragmas or URI options."""
    is_uri = db_path.startswith("file:")
    is_memory = db_path == ":memory:" or "mode=memory" in db_path

    if not is_uri and not is_memory:
        parent_dir = os.path.dirname(db_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

    pragmas = dict(SQLITE_PRAGMAS)
    if is_memory:
        pragmas.pop("journal_mode", None)

    kwargs: Dict[str, Any] = {
        "pragmas": pragmas,
        "thread_safe": True,
        "autoconnect": True,
        "timeout": 30.0,
    }
    if is_uri:
        kwargs["uri"] = True

    return SqliteDatabase(db_path, **kwargs)


def init_db(app: Optional[Flask] = None) -> SqliteDatabase:
    """Initialise database, configure proxy, and create schema tables."""
    db_path = get_db_path(app)
    logger.info("Initialising SQLite database at %s...", db_path)
    sqlite_db = create_sqlite_database(db_path)
    db.initialize(sqlite_db)
    sqlite_db.connect(reuse_if_open=True)
    run_migrations(sqlite_db)
    is_memory = db_path == ":memory:" or "mode=memory" in str(db_path)
    if not is_memory and not sqlite_db.is_closed():
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
        if (
            db.obj is not None
            and not db.obj.is_closed()
            and not (
                db.obj.database == ":memory:" or "mode=memory" in str(db.obj.database)
            )
        ):
            db.obj.close()


def get_db_stats(app: Optional[Flask] = None) -> Dict[str, Any]:
    """Inspect and return SQLite database storage metrics and table row counts."""
    from app.models.journey import Journey
    from app.models.location import Location
    from app.models.setting import Setting
    from app.models.timetable import Timetable
    from app.models.transfer import PlatformTransfer
    from app.models.transit import (
        Stop,
        SyncMetadata,
    )
    from app.models.walking import Walking

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

        cursor = database.execute_sql("PRAGMA freelist_count")
        freelist_row = cursor.fetchone()
        freelist_count = freelist_row[0] if freelist_row else 0

        # Calculate file size
        if (
            db_path != ":memory:"
            and not db_path.startswith("file:")
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
            "stops": Stop,
            "platform_transfers": PlatformTransfer,
            "locations": Location,
            "journeys": Journey,
            "walking": Walking,
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
            _syncable = (
                "stops",
                "ha_locations",
                "walking",
            )
            is_syncable = table_name in _syncable or table_name in (
                "locations",
                "timetables",
            )
            last_updated_at = None
            sync_status = "idle" if is_syncable else "managed"
            error_message = None

            meta_key = (
                table_name
                if table_name in sync_meta_map
                else (
                    "ha_locations"
                    if table_name == "locations" and "ha_locations" in sync_meta_map
                    else (
                        "train_timetables"
                        if table_name == "timetables"
                        and "train_timetables" in sync_meta_map
                        else (
                            "bus_timetables"
                            if table_name == "timetables"
                            and "bus_timetables" in sync_meta_map
                            else None
                        )
                    )
                )
            )
            if meta_key:
                meta_item = sync_meta_map[meta_key]
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

        vacuum_meta = sync_meta_map.get("database_vacuum") if has_sync_meta else None
        last_vacuumed_at = vacuum_meta.get("last_updated_at") if vacuum_meta else None
        vacuum_status = vacuum_meta.get("status", "idle") if vacuum_meta else "idle"

        return {
            "file_path": db_path,
            "file_size_bytes": file_size_bytes,
            "file_size_formatted": file_size_formatted,
            "page_size": page_size,
            "page_count": page_count,
            "freelist_count": freelist_count,
            "last_vacuumed_at": last_vacuumed_at,
            "vacuum_status": vacuum_status,
            "total_tables": len(tables),
            "total_rows": total_rows,
            "tables": tables,
        }


def vacuum_database(
    threshold_freelist_pages: int = DEFAULT_VACUUM_FREELIST_THRESHOLD,
    force: bool = False,
    app: Optional[Flask] = None,
) -> Dict[str, Any]:
    """Inspect SQLite freelist count and execute a full database VACUUM if needed.

    Args:
        threshold_freelist_pages: Minimum unallocated freelist pages required to trigger
            a VACUUM when force is False.
        force: If True, executes VACUUM unconditionally regardless of freelist threshold.
        app: Optional Flask application context.

    Returns:
        Dictionary conforming to standard telemetry response:
        {
            "status": "success" | "skipped_below_threshold" | "error",
            "freelist_count_before": int,
            "freelist_count_after": int,
            "pages_reclaimed": int,
            "bytes_reclaimed": int,
            "duration_seconds": float,
            "message": str,
        }
    """
    from app.models.transit import SyncMetadata

    start_time = time.time()
    db_path = get_db_path(app)

    if db.obj is None:
        init_db(app)

    database = db.obj

    with database.connection_context():
        cursor = database.execute_sql("PRAGMA page_size")
        page_size_row = cursor.fetchone()
        page_size = page_size_row[0] if page_size_row else 4096

        cursor = database.execute_sql("PRAGMA page_count")
        page_count_row = cursor.fetchone()
        page_count_before = page_count_row[0] if page_count_row else 0

        cursor = database.execute_sql("PRAGMA freelist_count")
        freelist_row = cursor.fetchone()
        freelist_count_before = freelist_row[0] if freelist_row else 0

        is_file_db = (
            db_path != ":memory:"
            and not db_path.startswith("file:")
            and os.path.exists(db_path)
            and os.path.isfile(db_path)
        )
        file_size_before = (
            os.path.getsize(db_path) if is_file_db else (page_size * page_count_before)
        )

        if not force and freelist_count_before < threshold_freelist_pages:
            duration = round(time.time() - start_time, 2)
            msg = (
                f"Database vacuum skipped: unallocated freelist page count "
                f"({freelist_count_before}) is below threshold ({threshold_freelist_pages})."
            )
            logger.info(msg)
            # Record success with 0 reclaimed records so the scheduled freshness expiry resets
            SyncMetadata.record_success(
                "database_vacuum", records_count=0, duration_seconds=duration
            )
            return {
                "status": "skipped_below_threshold",
                "freelist_count_before": freelist_count_before,
                "freelist_count_after": freelist_count_before,
                "pages_reclaimed": 0,
                "bytes_reclaimed": 0,
                "duration_seconds": duration,
                "message": msg,
            }

        SyncMetadata.record_start("database_vacuum")
        logger.info(
            "Executing database VACUUM (freelist: %d pages, file size: %s)...",
            freelist_count_before,
            format_file_size(file_size_before),
        )

        try:
            # Passive WAL checkpoint before VACUUM to fold WAL frames back into database pages
            try:
                database.execute_sql("PRAGMA wal_checkpoint(PASSIVE)")
            except Exception as checkpoint_err:
                logger.warning(
                    "Passive WAL checkpoint prior to VACUUM reported: %s",
                    checkpoint_err,
                )

            database.execute_sql("VACUUM")

            cursor = database.execute_sql("PRAGMA freelist_count")
            freelist_row = cursor.fetchone()
            freelist_count_after = freelist_row[0] if freelist_row else 0

            cursor = database.execute_sql("PRAGMA page_count")
            page_count_row = cursor.fetchone()
            page_count_after = page_count_row[0] if page_count_row else 0

            file_size_after = (
                os.path.getsize(db_path)
                if is_file_db
                else (page_size * page_count_after)
            )

            pages_reclaimed = max(0, freelist_count_before - freelist_count_after)
            bytes_reclaimed = max(0, file_size_before - file_size_after)
            duration = round(time.time() - start_time, 2)

            SyncMetadata.record_success(
                "database_vacuum",
                records_count=pages_reclaimed,
                duration_seconds=duration,
            )

            success_msg = (
                f"Successfully vacuumed database in {duration:.2f}s, reclaiming "
                f"{pages_reclaimed} freelist page(s) ({format_file_size(bytes_reclaimed)}). "
                f"New database size: {format_file_size(file_size_after)}."
            )
            logger.info(success_msg)

            return {
                "status": "success",
                "freelist_count_before": freelist_count_before,
                "freelist_count_after": freelist_count_after,
                "pages_reclaimed": pages_reclaimed,
                "bytes_reclaimed": bytes_reclaimed,
                "duration_seconds": duration,
                "message": success_msg,
            }

        except Exception as exc:
            duration = round(time.time() - start_time, 2)
            err_msg = f"Failed to vacuum database: {str(exc)}"
            logger.error(err_msg)
            SyncMetadata.record_error("database_vacuum", err_msg, duration)
            return {
                "status": "error",
                "freelist_count_before": freelist_count_before,
                "freelist_count_after": freelist_count_before,
                "pages_reclaimed": 0,
                "bytes_reclaimed": 0,
                "duration_seconds": duration,
                "message": err_msg,
            }


def get_sync_stats(app: Optional[Flask] = None) -> List[Dict[str, Any]]:
    """Inspect and return synchronisation metrics for all registered datasets."""
    from app.models.transit import SyncMetadata
    from app.sync.worker import SYNC_REGISTRY

    if db.obj is None:
        init_db(app)

    database = db.obj
    results: List[Dict[str, Any]] = []

    with database.connection_context():
        sync_meta_map: Dict[str, SyncMetadata] = {}
        try:
            for meta in SyncMetadata.select():
                sync_meta_map[meta.table_name] = meta
        except Exception:
            pass

        for entry in SYNC_REGISTRY:
            table_name = entry.table_name
            meta = sync_meta_map.get(table_name)

            last_updated_at = (
                meta.last_updated_at.isoformat()
                if meta and meta.last_updated_at
                else None
            )
            sync_status = meta.status if meta and meta.status else "idle"
            error_message = meta.error_message if meta else None
            records_count = meta.records_count if meta and meta.records_count else 0
            duration_seconds = (
                meta.duration_seconds if meta and meta.duration_seconds else 0.0
            )
            sync_requested = (
                meta.sync_requested if meta and meta.sync_requested else False
            )

            results.append(
                {
                    "name": table_name,
                    "syncable": True,
                    "last_updated_at": last_updated_at,
                    "sync_status": sync_status,
                    "error_message": error_message,
                    "records_count": records_count,
                    "duration_seconds": duration_seconds,
                    "sync_requested": sync_requested,
                }
            )

    return results
