"""Database management and settings repository using SQLite.

Provides persistent storage for application settings, credentials, and data.
"""

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


def init_app(app: Flask) -> None:
    """Register database functions with the Flask application."""
    app.teardown_appcontext(close_db)
    init_db(app)


class SettingsRepository:
    """Repository for querying and persisting configuration settings in SQLite."""

    def __init__(self, connection: Optional[sqlite3.Connection] = None) -> None:
        self._connection = connection

    @property
    def conn(self) -> sqlite3.Connection:
        """Get the active SQLite connection."""
        if self._connection is not None:
            return self._connection
        return get_db()

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Retrieve a single configuration value by key."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        if row is not None:
            return row["value"]
        return default

    def get_all(self, category: Optional[str] = None) -> Dict[str, str]:
        """Retrieve all configuration settings, optionally filtered by category."""
        cursor = self.conn.cursor()
        if category:
            cursor.execute(
                "SELECT key, value FROM settings WHERE category = ?",
                (category,),
            )
        else:
            cursor.execute("SELECT key, value FROM settings")

        rows = cursor.fetchall()
        return {row["key"]: row["value"] for row in rows}

    def set(self, key: str, value: str, category: Optional[str] = None) -> None:
        """Store or update a configuration setting."""
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO settings (key, value, category, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    category = coalesce(excluded.category, settings.category),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (key, value, category),
            )

    def set_many(
        self, settings: Dict[str, Any], category: Optional[str] = None
    ) -> None:
        """Store or update multiple configuration settings in a single transaction."""
        with self.conn:
            for key, value in settings.items():
                str_val = "" if value is None else str(value)
                self.conn.execute(
                    """
                    INSERT INTO settings (key, value, category, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        category = coalesce(excluded.category, settings.category),
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (key, str_val, category),
                )

    def delete(self, key: str) -> None:
        """Delete a configuration setting by key."""
        with self.conn:
            self.conn.execute("DELETE FROM settings WHERE key = ?", (key,))


class TimetableRepository:
    """Repository for querying and persisting timetable entries in SQLite."""

    def __init__(self, connection: Optional[sqlite3.Connection] = None) -> None:
        self._connection = connection

    @property
    def conn(self) -> sqlite3.Connection:
        """Get the active SQLite connection."""
        if self._connection is not None:
            return self._connection
        return get_db()

    def get_all(self) -> List[Dict[str, Any]]:
        """Retrieve all timetable entries ordered by creation date."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, transport_type, name, identifier, status, created_at, updated_at
            FROM timetables
            ORDER BY id ASC
            """)
        rows = cursor.fetchall()
        return [
            {
                "id": row["id"],
                "transport_type": row["transport_type"],
                "name": row["name"],
                "identifier": row["identifier"],
                "status": row["status"],
                "created_at": (
                    row["created_at"].isoformat()
                    if hasattr(row["created_at"], "isoformat")
                    else str(row["created_at"])
                ),
                "updated_at": (
                    row["updated_at"].isoformat()
                    if hasattr(row["updated_at"], "isoformat")
                    else str(row["updated_at"])
                ),
            }
            for row in rows
        ]

    def get(self, timetable_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a single timetable entry by ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT id, transport_type, name, identifier, status, created_at, updated_at
            FROM timetables
            WHERE id = ?
            """,
            (timetable_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "transport_type": row["transport_type"],
            "name": row["name"],
            "identifier": row["identifier"],
            "status": row["status"],
            "created_at": (
                row["created_at"].isoformat()
                if hasattr(row["created_at"], "isoformat")
                else str(row["created_at"])
            ),
            "updated_at": (
                row["updated_at"].isoformat()
                if hasattr(row["updated_at"], "isoformat")
                else str(row["updated_at"])
            ),
        }

    def add(
        self,
        transport_type: str,
        name: str,
        identifier: str,
        status: str = "active",
    ) -> int:
        """Add a new timetable entry and return its generated ID."""
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO timetables (
                    transport_type, name, identifier, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (transport_type.lower(), name, identifier, status.lower()),
            )
            return cursor.lastrowid or 0

    def update(
        self,
        timetable_id: int,
        transport_type: str,
        name: str,
        identifier: str,
        status: str = "active",
    ) -> bool:
        """Update an existing timetable entry."""
        with self.conn:
            cursor = self.conn.execute(
                """
                UPDATE timetables
                SET transport_type = ?, name = ?, identifier = ?, status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    transport_type.lower(),
                    name,
                    identifier,
                    status.lower(),
                    timetable_id,
                ),
            )
            return cursor.rowcount > 0

    def delete(self, timetable_id: int) -> bool:
        """Delete a timetable entry by ID."""
        with self.conn:
            cursor = self.conn.execute(
                "DELETE FROM timetables WHERE id = ?",
                (timetable_id,),
            )
            return cursor.rowcount > 0

    def replace_all(self, timetables: List[Dict[str, Any]]) -> None:
        """Atomically replace all timetable entries with a newly submitted list."""
        with self.conn:
            self.conn.execute("DELETE FROM timetables")
            for item in timetables:
                self.conn.execute(
                    """
                    INSERT INTO timetables (
                        transport_type, name, identifier, status, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (
                        item.get("transport_type", "bus").lower(),
                        item.get("name", "").strip(),
                        item.get("identifier", "").strip(),
                        item.get("status", "active").lower(),
                    ),
                )
