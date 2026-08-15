"""Unit tests for SQLite database management and SettingsRepository."""

import os
import sqlite3
import pytest
from flask import Flask, g

from app.db import (
    get_db_path,
    get_db,
    close_db,
    init_db,
    init_app,
    SettingsRepository,
)


def test_get_db_path_from_app(temp_db_path: str) -> None:
    """Test get_db_path retrieves path from app config."""
    app = Flask(__name__)
    app.config["DATABASE_PATH"] = temp_db_path
    assert get_db_path(app) == temp_db_path


def test_get_db_path_from_current_app(app: Flask, temp_db_path: str) -> None:
    """Test get_db_path retrieves path from current_app context."""
    with app.app_context():
        assert get_db_path() == temp_db_path


def test_get_db_path_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test get_db_path retrieves path from DATABASE_PATH environment variable."""
    monkeypatch.setenv("DATABASE_PATH", "/tmp/custom_env_test.db")
    app = Flask(__name__)
    assert get_db_path(app) == "/tmp/custom_env_test.db"


def test_get_db_path_ha_data_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test get_db_path checks Home Assistant /data directory."""
    monkeypatch.setattr(os.path, "exists", lambda p: p == "/data")
    monkeypatch.setattr(os, "access", lambda p, m: True)
    app = Flask(__name__)
    path = get_db_path(app)
    assert path == "/data/travel_assistant.db"


def test_get_db_path_instance_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    """Test get_db_path falls back to instance path when /data is unavailable."""
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    orig_exists = os.path.exists
    monkeypatch.setattr(
        os.path, "exists", lambda p: False if p == "/data" else orig_exists(p)
    )
    app = Flask(__name__, instance_path=str(tmp_path / "custom_instance"))
    path = get_db_path(app)
    assert path == str(tmp_path / "custom_instance" / "travel_assistant.db")
    assert orig_exists(str(tmp_path / "custom_instance"))


def test_get_db_path_current_app_instance_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    """Test get_db_path falls back to current_app instance path."""
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    orig_exists = os.path.exists
    monkeypatch.setattr(
        os.path, "exists", lambda p: False if p == "/data" else orig_exists(p)
    )
    app = Flask(__name__, instance_path=str(tmp_path / "app_instance"))
    with app.app_context():
        path = get_db_path()
        assert path == str(tmp_path / "app_instance" / "travel_assistant.db")


def test_get_db_path_no_app_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test get_db_path with no app and no context creates default instance dir."""
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    monkeypatch.setattr(os.path, "exists", lambda p: False)
    monkeypatch.setattr(os, "makedirs", lambda p, exist_ok=True: None)
    path = get_db_path()
    assert path == os.path.join("instance", "travel_assistant.db")


def test_get_db_caching_and_closing(app: Flask) -> None:
    """Test that get_db caches the connection in g and close_db closes it."""
    with app.app_context():
        db1 = get_db()
        db2 = get_db()
        assert db1 is db2
        assert "db" in g
        close_db()
        assert "db" not in g

        # Calling close_db when g.db is already absent should be a no-op
        close_db()


def test_init_db_in_memory() -> None:
    """Test init_db works with in-memory database."""
    app = Flask(__name__)
    app.config["DATABASE_PATH"] = ":memory:"
    init_db(app)


def test_init_app_registration(temp_db_path: str) -> None:
    """Test init_app registers teardown and initialises schema."""
    app = Flask(__name__)
    app.config["DATABASE_PATH"] = temp_db_path
    init_app(app)

    with app.app_context():
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='settings'"
        )
        assert cursor.fetchone() is not None


def test_settings_repository_crud(app: Flask) -> None:
    """Test SettingsRepository get, set, set_many, get_all, and delete."""
    with app.app_context():
        repo = SettingsRepository()

        # Test initial get default
        assert repo.get("nonexistent") is None
        assert repo.get("nonexistent", "fallback") == "fallback"

        # Test set single setting
        repo.set("api_key", "secret123", category="credentials")
        assert repo.get("api_key") == "secret123"

        # Test update existing setting
        repo.set("api_key", "secret456", category="credentials")
        assert repo.get("api_key") == "secret456"

        # Test set_many with None handling
        repo.set_many(
            {
                "bus_key": "bus_val",
                "train_key": "train_val",
                "empty_key": None,
            },
            category="transport",
        )

        assert repo.get("bus_key") == "bus_val"
        assert repo.get("train_key") == "train_val"
        assert repo.get("empty_key") == ""

        # Test get_all with category filter
        credentials_settings = repo.get_all(category="credentials")
        assert credentials_settings == {"api_key": "secret456"}

        transport_settings = repo.get_all(category="transport")
        assert transport_settings == {
            "bus_key": "bus_val",
            "train_key": "train_val",
            "empty_key": "",
        }

        # Test get_all without category filter
        all_settings = repo.get_all()
        assert len(all_settings) == 4
        assert "api_key" in all_settings
        assert "bus_key" in all_settings

        # Test delete
        repo.delete("bus_key")
        assert repo.get("bus_key") is None


def test_settings_repository_with_explicit_connection(
    temp_db_path: str,
) -> None:
    """Test SettingsRepository using a manually injected SQLite connection."""
    conn = sqlite3.connect(temp_db_path)
    conn.row_factory = sqlite3.Row
    with conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                category TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

    repo = SettingsRepository(connection=conn)
    repo.set("custom_conn_key", "custom_val")
    assert repo.get("custom_conn_key") == "custom_val"
    conn.close()
