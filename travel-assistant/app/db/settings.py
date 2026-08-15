"""Repository for querying and persisting configuration settings in SQLite."""

import sqlite3
from typing import Any, Dict, Optional

from app.db.core import get_db


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
