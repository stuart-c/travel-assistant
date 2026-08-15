"""Database management and SQLite connection lifecycle for Travel Assistant.

Provides persistent storage initialization and re-exports table repositories.
"""

import os
import sqlite3
from typing import Optional
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


# Re-export table repository classes for clean backwards-compatibility
from app.repositories.settings import SettingsRepository  # noqa: E402
from app.repositories.timetables import TimetableRepository  # noqa: E402

__all__ = [
    "DEFAULT_SCHEMA",
    "get_db_path",
    "get_db",
    "close_db",
    "init_db",
    "init_app",
    "SettingsRepository",
    "TimetableRepository",
]
