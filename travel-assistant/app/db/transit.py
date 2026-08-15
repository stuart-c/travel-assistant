"""Repositories for transit datasets (bus routes, bus stops, rail stations, and sync metadata)."""

import datetime
import sqlite3
from typing import Any, Dict, List, Optional

from app.db.core import get_db

SYNCABLE_TABLES = ("bus_routes", "bus_stops", "stations")


class SyncMetadataRepository:
    """Repository for querying and updating synchronisation metadata."""

    def __init__(self, connection: Optional[sqlite3.Connection] = None) -> None:
        self._connection = connection

    @property
    def conn(self) -> sqlite3.Connection:
        """Get the active SQLite connection."""
        if self._connection is not None:
            return self._connection
        return get_db()

    def get(self, table_name: str) -> Optional[Dict[str, Any]]:
        """Retrieve synchronisation metadata for a given table."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT table_name, last_updated_at, status, error_message,
                   records_count, duration_seconds, updated_at
            FROM sync_metadata
            WHERE table_name = ?
            """,
            (table_name,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "table_name": row["table_name"],
            "last_updated_at": (
                row["last_updated_at"].isoformat()
                if hasattr(row["last_updated_at"], "isoformat")
                else (str(row["last_updated_at"]) if row["last_updated_at"] else None)
            ),
            "status": row["status"],
            "error_message": row["error_message"],
            "records_count": row["records_count"] or 0,
            "duration_seconds": row["duration_seconds"] or 0.0,
            "updated_at": (
                row["updated_at"].isoformat()
                if hasattr(row["updated_at"], "isoformat")
                else (str(row["updated_at"]) if row["updated_at"] else None)
            ),
        }

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        """Retrieve all synchronisation metadata mapped by table name."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT table_name, last_updated_at, status, error_message,
                   records_count, duration_seconds, updated_at
            FROM sync_metadata
            ORDER BY table_name ASC
            """)
        rows = cursor.fetchall()
        result: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            table_name = row["table_name"]
            result[table_name] = {
                "table_name": table_name,
                "last_updated_at": (
                    row["last_updated_at"].isoformat()
                    if hasattr(row["last_updated_at"], "isoformat")
                    else (
                        str(row["last_updated_at"]) if row["last_updated_at"] else None
                    )
                ),
                "status": row["status"],
                "error_message": row["error_message"],
                "records_count": row["records_count"] or 0,
                "duration_seconds": row["duration_seconds"] or 0.0,
                "updated_at": (
                    row["updated_at"].isoformat()
                    if hasattr(row["updated_at"], "isoformat")
                    else (str(row["updated_at"]) if row["updated_at"] else None)
                ),
            }
        return result

    def record_sync_start(self, table_name: str) -> None:
        """Mark synchronisation as in progress for a given table."""
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO sync_metadata (
                    table_name, status, updated_at
                )
                VALUES (?, 'syncing', CURRENT_TIMESTAMP)
                ON CONFLICT(table_name) DO UPDATE SET
                    status = 'syncing',
                    updated_at = CURRENT_TIMESTAMP
                """,
                (table_name,),
            )

    def record_sync_success(
        self, table_name: str, records_count: int, duration_seconds: float = 0.0
    ) -> None:
        """Record successful synchronisation completion."""
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO sync_metadata (
                    table_name, last_updated_at, status, error_message,
                    records_count, duration_seconds, updated_at
                )
                VALUES (?, CURRENT_TIMESTAMP, 'success', NULL, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(table_name) DO UPDATE SET
                    last_updated_at = CURRENT_TIMESTAMP,
                    status = 'success',
                    error_message = NULL,
                    records_count = excluded.records_count,
                    duration_seconds = excluded.duration_seconds,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (table_name, records_count, max(0.0, duration_seconds)),
            )

    def record_sync_skipped(self, table_name: str, reason: str) -> None:
        """Record skipped synchronisation (e.g. unconfigured credentials)."""
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO sync_metadata (
                    table_name, status, error_message, updated_at
                )
                VALUES (?, 'skipped_no_credentials', ?, CURRENT_TIMESTAMP)
                ON CONFLICT(table_name) DO UPDATE SET
                    status = 'skipped_no_credentials',
                    error_message = excluded.error_message,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (table_name, reason),
            )

    def record_sync_error(
        self, table_name: str, error_message: str, duration_seconds: float = 0.0
    ) -> None:
        """Record failed synchronisation error."""
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO sync_metadata (
                    table_name, status, error_message, duration_seconds, updated_at
                )
                VALUES (?, 'error', ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(table_name) DO UPDATE SET
                    status = 'error',
                    error_message = excluded.error_message,
                    duration_seconds = excluded.duration_seconds,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (table_name, error_message, max(0.0, duration_seconds)),
            )

    def is_due_for_update(self, table_name: str, max_age_seconds: int = 86400) -> bool:
        """Check if a table synchronisation is overdue (never run or older than max_age_seconds)."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT CAST(last_updated_at AS TEXT) AS last_updated_at
            FROM sync_metadata
            WHERE table_name = ?
            """,
            (table_name,),
        )
        row = cursor.fetchone()
        if row is None or row["last_updated_at"] is None:
            return True

        last_updated = row["last_updated_at"]
        if isinstance(last_updated, str):
            try:
                dt = datetime.datetime.fromisoformat(
                    last_updated.replace("Z", "+00:00")
                )
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
            except ValueError:
                return True
        elif isinstance(last_updated, datetime.datetime):

            dt = last_updated
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
        else:
            return True

        now = datetime.datetime.now(datetime.timezone.utc)
        age_seconds = (now - dt).total_seconds()
        return age_seconds >= max_age_seconds


class BusRouteRepository:
    """Repository for querying and persisting bus routes in SQLite."""

    def __init__(self, connection: Optional[sqlite3.Connection] = None) -> None:
        self._connection = connection

    @property
    def conn(self) -> sqlite3.Connection:
        """Get the active SQLite connection."""
        if self._connection is not None:
            return self._connection
        return get_db()

    def get_all(self) -> List[Dict[str, Any]]:
        """Retrieve all bus routes ordered by route number."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, route_number, operator_name, operator_code,
                   origin, destination, description, updated_at
            FROM bus_routes
            ORDER BY route_number ASC, id ASC
            """)
        rows = cursor.fetchall()
        return [
            {
                "id": row["id"],
                "route_number": row["route_number"],
                "operator_name": row["operator_name"],
                "operator_code": row["operator_code"],
                "origin": row["origin"],
                "destination": row["destination"],
                "description": row["description"],
                "updated_at": (
                    row["updated_at"].isoformat()
                    if hasattr(row["updated_at"], "isoformat")
                    else str(row["updated_at"])
                ),
            }
            for row in rows
        ]

    def get_by_number(self, route_number: str) -> List[Dict[str, Any]]:
        """Retrieve bus routes matching a given route number."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT id, route_number, operator_name, operator_code,
                   origin, destination, description, updated_at
            FROM bus_routes
            WHERE route_number = ?
            ORDER BY id ASC
            """,
            (route_number,),
        )
        rows = cursor.fetchall()
        return [
            {
                "id": row["id"],
                "route_number": row["route_number"],
                "operator_name": row["operator_name"],
                "operator_code": row["operator_code"],
                "origin": row["origin"],
                "destination": row["destination"],
                "description": row["description"],
                "updated_at": (
                    row["updated_at"].isoformat()
                    if hasattr(row["updated_at"], "isoformat")
                    else str(row["updated_at"])
                ),
            }
            for row in rows
        ]

    def bulk_upsert(self, routes: List[Dict[str, Any]]) -> int:
        """Atomically insert or update multiple bus routes."""
        if not routes:
            return 0
        with self.conn:
            for item in routes:
                self.conn.execute(
                    """
                    INSERT INTO bus_routes (
                        route_number, operator_name, operator_code,
                        origin, destination, description, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        str(item.get("route_number", "")).strip(),
                        item.get("operator_name"),
                        item.get("operator_code"),
                        item.get("origin"),
                        item.get("destination"),
                        item.get("description"),
                    ),
                )
        return len(routes)

    def count(self) -> int:
        """Count total bus route records."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM bus_routes")
        return cursor.fetchone()[0]

    def clear(self) -> None:
        """Delete all bus route records."""
        with self.conn:
            self.conn.execute("DELETE FROM bus_routes")


class BusStopRepository:
    """Repository for querying and persisting bus stops in SQLite."""

    def __init__(self, connection: Optional[sqlite3.Connection] = None) -> None:
        self._connection = connection

    @property
    def conn(self) -> sqlite3.Connection:
        """Get the active SQLite connection."""
        if self._connection is not None:
            return self._connection
        return get_db()

    def get_all(self) -> List[Dict[str, Any]]:
        """Retrieve all bus stops ordered by name."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, atco_code, naptan_code, name, indicator,
                   locality, latitude, longitude, updated_at
            FROM bus_stops
            ORDER BY name ASC, atco_code ASC
            """)
        rows = cursor.fetchall()
        return [
            {
                "id": row["id"],
                "atco_code": row["atco_code"],
                "naptan_code": row["naptan_code"],
                "name": row["name"],
                "indicator": row["indicator"],
                "locality": row["locality"],
                "latitude": row["latitude"],
                "longitude": row["longitude"],
                "updated_at": (
                    row["updated_at"].isoformat()
                    if hasattr(row["updated_at"], "isoformat")
                    else str(row["updated_at"])
                ),
            }
            for row in rows
        ]

    def get_by_atco(self, atco_code: str) -> Optional[Dict[str, Any]]:
        """Retrieve a bus stop by unique ATCO code."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT id, atco_code, naptan_code, name, indicator,
                   locality, latitude, longitude, updated_at
            FROM bus_stops
            WHERE atco_code = ?
            """,
            (atco_code,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "atco_code": row["atco_code"],
            "naptan_code": row["naptan_code"],
            "name": row["name"],
            "indicator": row["indicator"],
            "locality": row["locality"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "updated_at": (
                row["updated_at"].isoformat()
                if hasattr(row["updated_at"], "isoformat")
                else str(row["updated_at"])
            ),
        }

    def bulk_upsert(self, stops: List[Dict[str, Any]]) -> int:
        """Atomically insert or update multiple bus stops."""
        if not stops:
            return 0
        with self.conn:
            for item in stops:
                self.conn.execute(
                    """
                    INSERT INTO bus_stops (
                        atco_code, naptan_code, name, indicator,
                        locality, latitude, longitude, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(atco_code) DO UPDATE SET
                        naptan_code = excluded.naptan_code,
                        name = excluded.name,
                        indicator = excluded.indicator,
                        locality = excluded.locality,
                        latitude = excluded.latitude,
                        longitude = excluded.longitude,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        str(item.get("atco_code", "")).strip(),
                        item.get("naptan_code"),
                        str(item.get("name", "")).strip(),
                        item.get("indicator"),
                        item.get("locality"),
                        item.get("latitude"),
                        item.get("longitude"),
                    ),
                )
        return len(stops)

    def count(self) -> int:
        """Count total bus stop records."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM bus_stops")
        return cursor.fetchone()[0]

    def clear(self) -> None:
        """Delete all bus stop records."""
        with self.conn:
            self.conn.execute("DELETE FROM bus_stops")


class StationRepository:
    """Repository for querying and persisting rail stations in SQLite."""

    def __init__(self, connection: Optional[sqlite3.Connection] = None) -> None:
        self._connection = connection

    @property
    def conn(self) -> sqlite3.Connection:
        """Get the active SQLite connection."""
        if self._connection is not None:
            return self._connection
        return get_db()

    def get_all(self) -> List[Dict[str, Any]]:
        """Retrieve all rail stations ordered by station name."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, crs_code, name, tiploc_code,
                   latitude, longitude, operator, updated_at
            FROM stations
            ORDER BY name ASC, crs_code ASC
            """)
        rows = cursor.fetchall()
        return [
            {
                "id": row["id"],
                "crs_code": row["crs_code"],
                "name": row["name"],
                "tiploc_code": row["tiploc_code"],
                "latitude": row["latitude"],
                "longitude": row["longitude"],
                "operator": row["operator"],
                "updated_at": (
                    row["updated_at"].isoformat()
                    if hasattr(row["updated_at"], "isoformat")
                    else str(row["updated_at"])
                ),
            }
            for row in rows
        ]

    def get_by_crs(self, crs_code: str) -> Optional[Dict[str, Any]]:
        """Retrieve a rail station by unique CRS code."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT id, crs_code, name, tiploc_code,
                   latitude, longitude, operator, updated_at
            FROM stations
            WHERE crs_code = ?
            """,
            (crs_code.upper().strip(),),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "crs_code": row["crs_code"],
            "name": row["name"],
            "tiploc_code": row["tiploc_code"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "operator": row["operator"],
            "updated_at": (
                row["updated_at"].isoformat()
                if hasattr(row["updated_at"], "isoformat")
                else str(row["updated_at"])
            ),
        }

    def bulk_upsert(self, stations: List[Dict[str, Any]]) -> int:
        """Atomically insert or update multiple rail stations."""
        if not stations:
            return 0
        with self.conn:
            for item in stations:
                self.conn.execute(
                    """
                    INSERT INTO stations (
                        crs_code, name, tiploc_code,
                        latitude, longitude, operator, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(crs_code) DO UPDATE SET
                        name = excluded.name,
                        tiploc_code = excluded.tiploc_code,
                        latitude = excluded.latitude,
                        longitude = excluded.longitude,
                        operator = excluded.operator,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        str(item.get("crs_code", "")).upper().strip(),
                        str(item.get("name", "")).strip(),
                        item.get("tiploc_code"),
                        item.get("latitude"),
                        item.get("longitude"),
                        item.get("operator"),
                    ),
                )
        return len(stations)

    def count(self) -> int:
        """Count total rail station records."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM stations")
        return cursor.fetchone()[0]

    def clear(self) -> None:
        """Delete all rail station records."""
        with self.conn:
            self.conn.execute("DELETE FROM stations")
