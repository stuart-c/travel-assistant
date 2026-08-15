"""Database connection lifecycle, SQLite management, and schema initialisation."""

import os
import sqlite3
from typing import Any, Dict, List, Optional
from flask import Flask, current_app, g

DEFAULT_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    category TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS timetables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transport_type TEXT NOT NULL,
    name TEXT NOT NULL,
    identifier TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


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


def get_db() -> sqlite3.Connection:
    """Obtain or initialise a SQLite database connection for the current request."""
    if "db" not in g:
        db_path = get_db_path()
        g.db = sqlite3.connect(
            db_path,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(e: Optional[BaseException] = None) -> None:
    """Close the SQLite database connection at the end of the request."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app: Optional[Flask] = None) -> None:
    """Initialise database schema tables."""
    db_path = get_db_path(app)
    # Ensure parent directory exists if using a file path
    if db_path != ":memory:":
        parent_dir = os.path.dirname(db_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.executescript(DEFAULT_SCHEMA)
    finally:
        conn.close()


def get_db_stats(
    app: Optional[Flask] = None,
    connection: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """Inspect and return SQLite database storage metrics and table row counts."""
    db_path = get_db_path(app)
    own_connection = False

    if connection is not None:
        conn = connection
    else:
        try:
            conn = get_db()
        except RuntimeError:
            # Outside of application context
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            own_connection = True

    try:
        cursor = conn.cursor()

        # Query page size and page count
        cursor.execute("PRAGMA page_size")
        page_size_row = cursor.fetchone()
        page_size = page_size_row[0] if page_size_row else 4096

        cursor.execute("PRAGMA page_count")
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

        # Discover all user tables (exclude internal sqlite_% metadata tables)
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name ASC
            """)
        table_rows = cursor.fetchall()

        tables: List[Dict[str, Any]] = []
        total_rows = 0

        for row in table_rows:
            table_name = row[0] if isinstance(row, (tuple, list)) else row["name"]

            # Count rows
            # Table name is sanitized by matching sqlite_master
            count_cursor = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"')
            row_count = count_cursor.fetchone()[0]

            # Fetch column metadata
            info_cursor = conn.execute(f'PRAGMA table_info("{table_name}")')
            col_rows = info_cursor.fetchall()
            columns = [
                col[1] if isinstance(col, (tuple, list)) else col["name"]
                for col in col_rows
            ]

            total_rows += row_count
            tables.append(
                {
                    "name": table_name,
                    "row_count": row_count,
                    "column_count": len(columns),
                    "columns": columns,
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
    finally:
        if own_connection:
            conn.close()


def init_app(app: Flask) -> None:
    """Register database functions with the Flask application."""
    app.teardown_appcontext(close_db)
    init_db(app)
