"""Base repository class for SQLite data access."""

import sqlite3
from typing import Any, Optional

from app.db.core import get_db


class BaseRepository:
    """Base repository providing connection management and common database utilities."""

    def __init__(self, connection: Optional[sqlite3.Connection] = None) -> None:
        self._connection = connection

    @property
    def conn(self) -> sqlite3.Connection:
        """Get the active SQLite connection."""
        if self._connection is not None:
            return self._connection
        return get_db()

    @staticmethod
    def format_timestamp(dt: Any) -> str:
        """Format a database datetime or timestamp field into an ISO string."""
        if dt is None:
            return ""
        if hasattr(dt, "isoformat"):
            return dt.isoformat()
        return str(dt)
