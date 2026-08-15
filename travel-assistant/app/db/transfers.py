"""Repositories for querying and persisting transfers (inter-location and platform) in SQLite."""

from typing import Any, Dict, List, Optional

from app.db.base import BaseRepository


class LocationTransferRepository(BaseRepository):
    """Repository for managing inter-location walking and interchange transfers."""

    def get_all(self) -> List[Dict[str, Any]]:
        """Retrieve all inter-location transfers ordered by ID."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, from_type, from_id, from_name,
                   to_type, to_id, to_name,
                   transfer_time_minutes, bidirectional, step_free, notes,
                   created_at, updated_at
            FROM location_transfers
            ORDER BY id ASC
            """)
        rows = cursor.fetchall()
        return [
            {
                "id": row["id"],
                "from_type": row["from_type"],
                "from_id": row["from_id"],
                "from_name": row["from_name"],
                "to_type": row["to_type"],
                "to_id": row["to_id"],
                "to_name": row["to_name"],
                "transfer_time_minutes": row["transfer_time_minutes"],
                "bidirectional": bool(row["bidirectional"]),
                "step_free": bool(row["step_free"]),
                "notes": row["notes"] or "",
                "created_at": self.format_timestamp(row["created_at"]),
                "updated_at": self.format_timestamp(row["updated_at"]),
            }
            for row in rows
        ]

    def get(self, transfer_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a single inter-location transfer by ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT id, from_type, from_id, from_name,
                   to_type, to_id, to_name,
                   transfer_time_minutes, bidirectional, step_free, notes,
                   created_at, updated_at
            FROM location_transfers
            WHERE id = ?
            """,
            (transfer_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "from_type": row["from_type"],
            "from_id": row["from_id"],
            "from_name": row["from_name"],
            "to_type": row["to_type"],
            "to_id": row["to_id"],
            "to_name": row["to_name"],
            "transfer_time_minutes": row["transfer_time_minutes"],
            "bidirectional": bool(row["bidirectional"]),
            "step_free": bool(row["step_free"]),
            "notes": row["notes"] or "",
            "created_at": self.format_timestamp(row["created_at"]),
            "updated_at": self.format_timestamp(row["updated_at"]),
        }

    def add(
        self,
        from_type: str,
        from_id: str,
        from_name: str,
        to_type: str,
        to_id: str,
        to_name: str,
        transfer_time_minutes: int = 5,
        bidirectional: bool = True,
        step_free: bool = False,
        notes: str = "",
    ) -> int:
        """Insert a new inter-location transfer and return its generated ID."""
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO location_transfers (
                    from_type, from_id, from_name,
                    to_type, to_id, to_name,
                    transfer_time_minutes, bidirectional, step_free, notes,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (
                    str(from_type).lower().strip(),
                    str(from_id).strip(),
                    str(from_name).strip(),
                    str(to_type).lower().strip(),
                    str(to_id).strip(),
                    str(to_name).strip(),
                    max(1, int(transfer_time_minutes)),
                    1 if bidirectional else 0,
                    1 if step_free else 0,
                    str(notes).strip() if notes else None,
                ),
            )
            return cursor.lastrowid or 0

    def update(
        self,
        transfer_id: int,
        from_type: str,
        from_id: str,
        from_name: str,
        to_type: str,
        to_id: str,
        to_name: str,
        transfer_time_minutes: int = 5,
        bidirectional: bool = True,
        step_free: bool = False,
        notes: str = "",
    ) -> bool:
        """Update an existing inter-location transfer."""
        with self.conn:
            cursor = self.conn.execute(
                """
                UPDATE location_transfers
                SET from_type = ?, from_id = ?, from_name = ?,
                    to_type = ?, to_id = ?, to_name = ?,
                    transfer_time_minutes = ?, bidirectional = ?, step_free = ?,
                    notes = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    str(from_type).lower().strip(),
                    str(from_id).strip(),
                    str(from_name).strip(),
                    str(to_type).lower().strip(),
                    str(to_id).strip(),
                    str(to_name).strip(),
                    max(1, int(transfer_time_minutes)),
                    1 if bidirectional else 0,
                    1 if step_free else 0,
                    str(notes).strip() if notes else None,
                    transfer_id,
                ),
            )
            return cursor.rowcount > 0

    def delete(self, transfer_id: int) -> bool:
        """Delete an inter-location transfer by ID."""
        with self.conn:
            cursor = self.conn.execute(
                "DELETE FROM location_transfers WHERE id = ?",
                (transfer_id,),
            )
            return cursor.rowcount > 0

    def replace_all(self, transfers: List[Dict[str, Any]]) -> None:
        """Atomically replace all inter-location transfers with a newly submitted list."""
        rows_to_insert = [
            (
                str(item.get("from_type", "station")).lower().strip(),
                str(item.get("from_id", "")).strip(),
                str(item.get("from_name", "")).strip(),
                str(item.get("to_type", "bus_stop")).lower().strip(),
                str(item.get("to_id", "")).strip(),
                str(item.get("to_name", "")).strip(),
                max(1, int(item.get("transfer_time_minutes", 5))),
                1 if item.get("bidirectional", True) else 0,
                1 if item.get("step_free", False) else 0,
                str(item.get("notes", "")).strip() if item.get("notes") else None,
            )
            for item in transfers
            if item.get("from_id") and item.get("to_id")
        ]
        with self.conn:
            self.conn.execute("DELETE FROM location_transfers")
            if rows_to_insert:
                self.conn.executemany(
                    """
                    INSERT INTO location_transfers (
                        from_type, from_id, from_name,
                        to_type, to_id, to_name,
                        transfer_time_minutes, bidirectional, step_free, notes,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    rows_to_insert,
                )

    def count(self) -> int:
        """Count total inter-location transfer records."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM location_transfers")
        return cursor.fetchone()[0]

    def clear(self) -> None:
        """Delete all inter-location transfer records."""
        with self.conn:
            self.conn.execute("DELETE FROM location_transfers")


class PlatformTransferRepository(BaseRepository):
    """Repository for managing platform-to-platform transfers within a station or interchange."""

    def get_all(self) -> List[Dict[str, Any]]:
        """Retrieve all platform transfers ordered by ID."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, location_type, location_id, location_name,
                   from_platform, to_platform,
                   transfer_time_minutes, bidirectional, step_free, notes,
                   created_at, updated_at
            FROM platform_transfers
            ORDER BY id ASC
            """)
        rows = cursor.fetchall()
        return [
            {
                "id": row["id"],
                "location_type": row["location_type"],
                "location_id": row["location_id"],
                "location_name": row["location_name"],
                "from_platform": row["from_platform"],
                "to_platform": row["to_platform"],
                "transfer_time_minutes": row["transfer_time_minutes"],
                "bidirectional": bool(row["bidirectional"]),
                "step_free": bool(row["step_free"]),
                "notes": row["notes"] or "",
                "created_at": self.format_timestamp(row["created_at"]),
                "updated_at": self.format_timestamp(row["updated_at"]),
            }
            for row in rows
        ]

    def get(self, transfer_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a single platform transfer by ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT id, location_type, location_id, location_name,
                   from_platform, to_platform,
                   transfer_time_minutes, bidirectional, step_free, notes,
                   created_at, updated_at
            FROM platform_transfers
            WHERE id = ?
            """,
            (transfer_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "location_type": row["location_type"],
            "location_id": row["location_id"],
            "location_name": row["location_name"],
            "from_platform": row["from_platform"],
            "to_platform": row["to_platform"],
            "transfer_time_minutes": row["transfer_time_minutes"],
            "bidirectional": bool(row["bidirectional"]),
            "step_free": bool(row["step_free"]),
            "notes": row["notes"] or "",
            "created_at": self.format_timestamp(row["created_at"]),
            "updated_at": self.format_timestamp(row["updated_at"]),
        }

    def add(
        self,
        location_type: str,
        location_id: str,
        location_name: str,
        from_platform: str,
        to_platform: str,
        transfer_time_minutes: int = 2,
        bidirectional: bool = True,
        step_free: bool = False,
        notes: str = "",
    ) -> int:
        """Insert a new platform transfer and return its generated ID."""
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO platform_transfers (
                    location_type, location_id, location_name,
                    from_platform, to_platform,
                    transfer_time_minutes, bidirectional, step_free, notes,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (
                    str(location_type).lower().strip(),
                    str(location_id).strip(),
                    str(location_name).strip(),
                    str(from_platform).strip(),
                    str(to_platform).strip(),
                    max(1, int(transfer_time_minutes)),
                    1 if bidirectional else 0,
                    1 if step_free else 0,
                    str(notes).strip() if notes else None,
                ),
            )
            return cursor.lastrowid or 0

    def update(
        self,
        transfer_id: int,
        location_type: str,
        location_id: str,
        location_name: str,
        from_platform: str,
        to_platform: str,
        transfer_time_minutes: int = 2,
        bidirectional: bool = True,
        step_free: bool = False,
        notes: str = "",
    ) -> bool:
        """Update an existing platform transfer."""
        with self.conn:
            cursor = self.conn.execute(
                """
                UPDATE platform_transfers
                SET location_type = ?, location_id = ?, location_name = ?,
                    from_platform = ?, to_platform = ?,
                    transfer_time_minutes = ?, bidirectional = ?, step_free = ?,
                    notes = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    str(location_type).lower().strip(),
                    str(location_id).strip(),
                    str(location_name).strip(),
                    str(from_platform).strip(),
                    str(to_platform).strip(),
                    max(1, int(transfer_time_minutes)),
                    1 if bidirectional else 0,
                    1 if step_free else 0,
                    str(notes).strip() if notes else None,
                    transfer_id,
                ),
            )
            return cursor.rowcount > 0

    def delete(self, transfer_id: int) -> bool:
        """Delete a platform transfer by ID."""
        with self.conn:
            cursor = self.conn.execute(
                "DELETE FROM platform_transfers WHERE id = ?",
                (transfer_id,),
            )
            return cursor.rowcount > 0

    def replace_all(self, transfers: List[Dict[str, Any]]) -> None:
        """Atomically replace all platform transfers with a newly submitted list."""
        rows_to_insert = [
            (
                str(item.get("location_type", "station")).lower().strip(),
                str(item.get("location_id", "")).strip(),
                str(item.get("location_name", "")).strip(),
                str(item.get("from_platform", "")).strip(),
                str(item.get("to_platform", "")).strip(),
                max(1, int(item.get("transfer_time_minutes", 2))),
                1 if item.get("bidirectional", True) else 0,
                1 if item.get("step_free", False) else 0,
                str(item.get("notes", "")).strip() if item.get("notes") else None,
            )
            for item in transfers
            if item.get("location_id")
            and item.get("from_platform")
            and item.get("to_platform")
        ]
        with self.conn:
            self.conn.execute("DELETE FROM platform_transfers")
            if rows_to_insert:
                self.conn.executemany(
                    """
                    INSERT INTO platform_transfers (
                        location_type, location_id, location_name,
                        from_platform, to_platform,
                        transfer_time_minutes, bidirectional, step_free, notes,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    rows_to_insert,
                )

    def count(self) -> int:
        """Count total platform transfer records."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM platform_transfers")
        return cursor.fetchone()[0]

    def clear(self) -> None:
        """Delete all platform transfer records."""
        with self.conn:
            self.conn.execute("DELETE FROM platform_transfers")


class TransferRepository(BaseRepository):
    """Unified repository orchestrating both location and platform transfer operations."""

    def __init__(self, connection: Optional[Any] = None) -> None:
        super().__init__(connection)
        self.locations = LocationTransferRepository(connection)
        self.platforms = PlatformTransferRepository(connection)

    def get_all(self) -> Dict[str, List[Dict[str, Any]]]:
        """Retrieve both location transfers and platform transfers."""
        return {
            "location_transfers": self.locations.get_all(),
            "platform_transfers": self.platforms.get_all(),
        }

    def get_all_location_transfers(self) -> List[Dict[str, Any]]:
        """Retrieve all inter-location transfers."""
        return self.locations.get_all()

    def get_all_platform_transfers(self) -> List[Dict[str, Any]]:
        """Retrieve all platform transfers."""
        return self.platforms.get_all()

    def replace_all(
        self,
        location_transfers: List[Dict[str, Any]],
        platform_transfers: List[Dict[str, Any]],
    ) -> None:
        """Atomically replace all location and platform transfers in a single transaction."""
        with self.conn:
            self.locations.replace_all(location_transfers)
            self.platforms.replace_all(platform_transfers)
