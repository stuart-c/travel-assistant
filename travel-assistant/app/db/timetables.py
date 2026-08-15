"""Repository for querying and persisting timetable entries in SQLite."""

import sqlite3
from typing import Any, Dict, List, Optional

from app.db.core import get_db


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
