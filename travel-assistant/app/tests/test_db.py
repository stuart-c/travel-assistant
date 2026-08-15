"""Unit tests for SQLite database management and SettingsRepository."""

import os
import sqlite3
from unittest.mock import MagicMock
import pytest
from flask import Flask, g


from app.db import (
    get_db_path,
    get_db,
    close_db,
    init_db,
    init_app,
    get_db_stats,
    SettingsRepository,
    SyncMetadataRepository,
    BusRouteRepository,
    BusStopRepository,
    StationRepository,
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


def test_timetable_repository_crud(app: Flask) -> None:
    """Test TimetableRepository add, get, update, delete, and get_all."""
    from app.db import TimetableRepository

    with app.app_context():
        repo = TimetableRepository()

        # Initial get_all should be empty
        assert repo.get_all() == []
        assert repo.get(999) is None

        # Add timetable items
        bus_id = repo.add("bus", "Oxford Tube", "OX-TUBE", "active")
        assert bus_id > 0

        train_id = repo.add("train", "London Paddington", "PAD", "inactive")
        assert train_id > 0

        # Get single timetable
        item = repo.get(bus_id)
        assert item is not None
        assert item["id"] == bus_id
        assert item["transport_type"] == "bus"
        assert item["name"] == "Oxford Tube"
        assert item["identifier"] == "OX-TUBE"
        assert item["status"] == "active"
        assert "created_at" in item

        # Update timetable
        updated = repo.update(
            bus_id, "bus", "Oxford Tube Express", "OX-TUBE-EXP", "active"
        )
        assert updated is True
        item_updated = repo.get(bus_id)
        assert item_updated["name"] == "Oxford Tube Express"
        assert item_updated["identifier"] == "OX-TUBE-EXP"

        # Update nonexistent timetable
        assert repo.update(888, "bus", "Fake", "F1", "active") is False

        # Get all timetables
        all_items = repo.get_all()
        assert len(all_items) == 2
        assert all_items[0]["id"] == bus_id
        assert all_items[1]["id"] == train_id

        # Delete timetable
        assert repo.delete(bus_id) is True
        assert repo.get(bus_id) is None
        assert len(repo.get_all()) == 1
        assert repo.delete(999) is False


def test_timetable_repository_replace_all(app: Flask) -> None:
    """Test TimetableRepository replace_all replaces dataset atomically."""
    from app.db import TimetableRepository

    with app.app_context():
        repo = TimetableRepository()

        repo.add("bus", "Old Bus", "OLD-1", "active")
        assert len(repo.get_all()) == 1

        new_dataset = [
            {
                "transport_type": "bus",
                "name": "Route 1",
                "identifier": "OX-01",
                "status": "active",
            },
            {
                "transport_type": "train",
                "name": "Oxford Station",
                "identifier": "OXF",
                "status": "active",
            },
            {
                "transport_type": "train",
                "name": "Reading",
                "identifier": "RDG",
                "status": "inactive",
            },
        ]

        repo.replace_all(new_dataset)
        items = repo.get_all()
        assert len(items) == 3
        assert items[0]["name"] == "Route 1"
        assert items[1]["identifier"] == "OXF"
        assert items[2]["status"] == "inactive"

        # Replace with empty list
        repo.replace_all([])
        assert repo.get_all() == []


def test_timetable_repository_explicit_connection(temp_db_path: str) -> None:
    """Test TimetableRepository with manually supplied connection."""
    from app.db import TimetableRepository

    conn = sqlite3.connect(temp_db_path)
    conn.row_factory = sqlite3.Row
    with conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS timetables (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transport_type TEXT NOT NULL,
                name TEXT NOT NULL,
                identifier TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

    repo = TimetableRepository(connection=conn)
    tid = repo.add("bus", "Custom Route", "CR-1")
    item = repo.get(tid)
    assert item["name"] == "Custom Route"
    conn.close()


def test_db_module_exports() -> None:
    """Test that app.db exports SettingsRepository, TimetableRepository, and core helpers."""
    from app.db.settings import SettingsRepository as DirectSettingsRepo
    from app.db.timetables import TimetableRepository as DirectTimetableRepo
    from app.db.core import (
        get_db as DirectGetDb,
        get_db_stats as DirectGetDbStats,
        format_file_size as DirectFormatFileSize,
    )
    from app.db import (
        SettingsRepository as DbSettingsRepo,
        TimetableRepository as DbTimetableRepo,
        get_db as DbGetDb,
        get_db_stats as DbGetDbStats,
        format_file_size as DbFormatFileSize,
    )

    assert DirectSettingsRepo is DbSettingsRepo
    assert DirectTimetableRepo is DbTimetableRepo
    assert DirectGetDb is DbGetDb
    assert DirectGetDbStats is DbGetDbStats
    assert DirectFormatFileSize is DbFormatFileSize


def test_format_file_size() -> None:
    """Test format_file_size formats byte quantities correctly."""
    from app.db import format_file_size

    assert format_file_size(0) == "0 B"
    assert format_file_size(512) == "512 B"
    assert format_file_size(1023) == "1023 B"
    assert format_file_size(1024) == "1.0 KB"
    assert format_file_size(1536) == "1.5 KB"
    assert format_file_size(1024 * 1024) == "1.0 MB"
    assert format_file_size(25 * 1024 * 1024) == "25.0 MB"
    assert format_file_size(1024 * 1024 * 1024) == "1.00 GB"
    assert format_file_size(3 * 1024 * 1024 * 1024) == "3.00 GB"


def test_get_db_stats_in_app_context(app: Flask) -> None:
    """Test get_db_stats within application context with tables and rows."""
    from app.db import SettingsRepository, TimetableRepository, get_db_stats

    with app.app_context():
        settings_repo = SettingsRepository()
        settings_repo.set("site_name", "Test Site", category="general")
        settings_repo.set("theme", "dark", category="appearance")

        timetables_repo = TimetableRepository()
        timetables_repo.add("bus", "Route 1", "R-1")

        stats = get_db_stats()

        assert stats["file_path"] == app.config["DATABASE_PATH"]
        assert stats["file_size_bytes"] > 0
        assert (
            "KB" in stats["file_size_formatted"] or "B" in stats["file_size_formatted"]
        )
        assert stats["total_tables"] == 6
        assert stats["total_rows"] == 3

        table_dict = {t["name"]: t for t in stats["tables"]}
        assert "settings" in table_dict
        assert "timetables" in table_dict

        assert table_dict["settings"]["row_count"] == 2
        assert "key" in table_dict["settings"]["columns"]
        assert "value" in table_dict["settings"]["columns"]

        assert table_dict["timetables"]["row_count"] == 1
        assert "transport_type" in table_dict["timetables"]["columns"]


def test_get_db_stats_explicit_connection(temp_db_path: str) -> None:
    """Test get_db_stats using an explicitly passed sqlite3 connection."""
    from app.db import get_db_stats

    conn = sqlite3.connect(temp_db_path)
    conn.row_factory = sqlite3.Row
    with conn:
        conn.executescript("""
            CREATE TABLE custom_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_name TEXT NOT NULL
            );
            INSERT INTO custom_items (item_name) VALUES ('Item A'), ('Item B');
        """)

    stats = get_db_stats(connection=conn)
    assert stats["total_tables"] == 1
    assert stats["total_rows"] == 2
    assert stats["tables"][0]["name"] == "custom_items"
    assert stats["tables"][0]["row_count"] == 2
    assert stats["tables"][0]["column_count"] == 2
    conn.close()


def test_get_db_stats_no_app_context(
    temp_db_path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test get_db_stats called outside of Flask request/app context."""
    from app.db import get_db_stats

    monkeypatch.setenv("DATABASE_PATH", temp_db_path)
    conn = sqlite3.connect(temp_db_path)
    with conn:
        conn.execute("CREATE TABLE sample (id INT)")
        conn.execute("INSERT INTO sample VALUES (1)")
    conn.close()

    # Call with no app context and no connection passed
    stats = get_db_stats()
    assert stats["file_path"] == temp_db_path
    assert stats["total_tables"] == 1
    assert stats["total_rows"] == 1


def test_get_db_stats_memory_db() -> None:
    """Test get_db_stats with in-memory database."""
    from app.db import get_db_stats

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    with conn:
        conn.execute("CREATE TABLE mem_table (id INT, val TEXT)")
        conn.execute("INSERT INTO mem_table VALUES (1, 'alpha')")

    stats = get_db_stats(connection=conn)
    assert stats["file_size_bytes"] >= 0
    assert stats["total_tables"] == 1
    assert stats["total_rows"] == 1
    conn.close()


def test_get_db_stats_filters_internal_tables(temp_db_path: str) -> None:
    """Test get_db_stats filters out sqlite_ internal tables."""
    from app.db import get_db_stats

    conn = sqlite3.connect(temp_db_path)
    conn.row_factory = sqlite3.Row
    with conn:
        conn.executescript("""
            CREATE TABLE auto_tbl (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT);
            INSERT INTO auto_tbl (name) VALUES ('Alpha');
        """)

    # Check sqlite_sequence exists in sqlite_master
    cur = conn.execute("SELECT name FROM sqlite_master WHERE name = 'sqlite_sequence'")
    assert cur.fetchone() is not None

    stats = get_db_stats(connection=conn)
    table_names = [t["name"] for t in stats["tables"]]
    assert "auto_tbl" in table_names
    assert "sqlite_sequence" not in table_names
    assert stats["total_tables"] == 1
    conn.close()


def test_sync_metadata_repository_lifecycle(app: Flask) -> None:
    """Test SyncMetadataRepository CRUD and state recording."""
    with app.app_context():
        repo = SyncMetadataRepository()
        assert repo.get("bus_routes") is None
        assert repo.get_all() == {}

        # Record start
        repo.record_sync_start("bus_routes")
        meta = repo.get("bus_routes")
        assert meta is not None
        assert meta["status"] == "syncing"
        assert meta["records_count"] == 0

        # Record success
        repo.record_sync_success("bus_routes", 42, duration_seconds=1.23)
        meta = repo.get("bus_routes")
        assert meta["status"] == "success"
        assert meta["records_count"] == 42
        assert meta["duration_seconds"] == 1.23
        assert meta["last_updated_at"] is not None
        assert meta["error_message"] is None

        # Record skipped
        repo.record_sync_skipped("bus_stops", "API key missing")
        meta_stops = repo.get("bus_stops")
        assert meta_stops["status"] == "skipped_no_credentials"
        assert meta_stops["error_message"] == "API key missing"

        # Record error
        repo.record_sync_error("stations", "Network timeout", duration_seconds=0.5)
        meta_stations = repo.get("stations")
        assert meta_stations["status"] == "error"
        assert meta_stations["error_message"] == "Network timeout"
        assert meta_stations["duration_seconds"] == 0.5

        all_meta = repo.get_all()
        assert len(all_meta) == 3
        assert "bus_routes" in all_meta
        assert "bus_stops" in all_meta
        assert "stations" in all_meta


def test_sync_metadata_is_due_for_update(app: Flask) -> None:
    """Test is_due_for_update threshold calculations."""
    with app.app_context():
        repo = SyncMetadataRepository()
        # Never synced is due
        assert repo.is_due_for_update("bus_routes") is True

        # Synced just now is not due
        repo.record_sync_success("bus_routes", 10)
        assert repo.is_due_for_update("bus_routes", max_age_seconds=3600) is False

        # If updated over 10 seconds ago and max_age_seconds=5
        conn = get_db()
        with conn:
            conn.execute("""
                UPDATE sync_metadata
                SET last_updated_at = datetime('now', '-25 hours')
                WHERE table_name = 'bus_routes'
                """)
        assert repo.is_due_for_update("bus_routes", max_age_seconds=86400) is True

        # Test with invalid / weird timestamp fallback
        with conn:
            conn.execute("""
                UPDATE sync_metadata
                SET last_updated_at = 12345
                WHERE table_name = 'bus_routes'
                """)
        assert repo.is_due_for_update("bus_routes") is True


def test_bus_route_repository(app: Flask) -> None:
    """Test BusRouteRepository querying, bulk upsert, count, and clearing."""
    with app.app_context():
        repo = BusRouteRepository()
        assert repo.count() == 0
        assert repo.get_all() == []

        # Empty upsert
        assert repo.bulk_upsert([]) == 0

        # Upsert routes
        routes = [
            {
                "route_number": "1",
                "operator_name": "Oxford Bus Company",
                "operator_code": "OBC",
                "origin": "Blackbird Leys",
                "destination": "City Centre",
                "description": "City service",
            },
            {
                "route_number": "5",
                "operator_name": "Oxford Bus Company",
                "operator_code": "OBC",
                "origin": "Blackbird Leys",
                "destination": "Rail Station",
                "description": "Station link",
            },
        ]
        inserted = repo.bulk_upsert(routes)
        assert inserted == 2
        assert repo.count() == 2

        all_routes = repo.get_all()
        assert len(all_routes) == 2
        assert all_routes[0]["route_number"] == "1"

        # Search by number
        match = repo.get_by_number("5")
        assert len(match) == 1
        assert match[0]["destination"] == "Rail Station"

        repo.clear()
        assert repo.count() == 0


def test_bus_stop_repository(app: Flask) -> None:
    """Test BusStopRepository querying, bulk upsert, count, and clearing."""
    with app.app_context():
        repo = BusStopRepository()
        assert repo.count() == 0
        assert repo.get_all() == []

        assert repo.bulk_upsert([]) == 0

        stops = [
            {
                "atco_code": "340000001",
                "naptan_code": "oxf123",
                "name": "High Street T1",
                "indicator": "Stop T1",
                "locality": "Oxford",
                "latitude": 51.752,
                "longitude": -1.257,
            },
            {
                "atco_code": "340000002",
                "naptan_code": "oxf124",
                "name": "Broad Street B1",
                "indicator": "Stop B1",
                "locality": "Oxford",
                "latitude": 51.754,
                "longitude": -1.256,
            },
        ]
        inserted = repo.bulk_upsert(stops)
        assert inserted == 2
        assert repo.count() == 2

        all_stops = repo.get_all()
        assert len(all_stops) == 2

        stop = repo.get_by_atco("340000001")
        assert stop is not None
        assert stop["name"] == "High Street T1"

        # Nonexistent stop
        assert repo.get_by_atco("999999999") is None

        # Re-upsert with conflict update
        stops[0]["name"] = "High Street T1 (Updated)"
        repo.bulk_upsert([stops[0]])
        assert repo.count() == 2
        assert repo.get_by_atco("340000001")["name"] == "High Street T1 (Updated)"

        repo.clear()
        assert repo.count() == 0


def test_station_repository(app: Flask) -> None:
    """Test StationRepository querying, bulk upsert, count, and clearing."""
    with app.app_context():
        repo = StationRepository()
        assert repo.count() == 0
        assert repo.get_all() == []

        assert repo.bulk_upsert([]) == 0

        stations = [
            {
                "crs_code": "OXF",
                "name": "Oxford",
                "tiploc_code": "OXFD",
                "latitude": 51.7534,
                "longitude": -1.2700,
                "operator": "GWR",
            },
            {
                "crs_code": "PAD",
                "name": "London Paddington",
                "tiploc_code": "PADTON",
                "latitude": 51.5154,
                "longitude": -0.1755,
                "operator": "Network Rail",
            },
        ]
        inserted = repo.bulk_upsert(stations)
        assert inserted == 2
        assert repo.count() == 2

        all_st = repo.get_all()
        assert len(all_st) == 2

        st = repo.get_by_crs("oxf")
        assert st is not None
        assert st["name"] == "Oxford"

        assert repo.get_by_crs("XYZ") is None

        # Conflict update
        stations[0]["name"] = "Oxford Central"
        repo.bulk_upsert([stations[0]])
        assert repo.count() == 2
        assert repo.get_by_crs("OXF")["name"] == "Oxford Central"

        repo.clear()
        assert repo.count() == 0


def test_get_db_stats_with_sync_metadata(app: Flask) -> None:
    """Test get_db_stats correctly surfaces sync metadata and syncable flags."""
    with app.app_context():
        sync_repo = SyncMetadataRepository()
        sync_repo.record_sync_success("bus_routes", 15, duration_seconds=0.8)
        sync_repo.record_sync_skipped("bus_stops", "No key")

        stats = get_db_stats()
        tables_by_name = {t["name"]: t for t in stats["tables"]}

        assert "bus_routes" in tables_by_name
        assert tables_by_name["bus_routes"]["syncable"] is True
        assert tables_by_name["bus_routes"]["sync_status"] == "success"
        assert tables_by_name["bus_routes"]["last_updated_at"] is not None

        assert "bus_stops" in tables_by_name
        assert tables_by_name["bus_stops"]["syncable"] is True
        assert tables_by_name["bus_stops"]["sync_status"] == "skipped_no_credentials"
        assert tables_by_name["bus_stops"]["error_message"] == "No key"

        assert "stations" in tables_by_name
        assert tables_by_name["stations"]["syncable"] is True
        assert tables_by_name["stations"]["sync_status"] == "idle"

        assert "settings" in tables_by_name
        assert tables_by_name["settings"]["syncable"] is False


def test_transit_repositories_explicit_connection(temp_db_path: str) -> None:
    """Test passing explicit sqlite3 connection to transit repositories."""
    conn = sqlite3.connect(temp_db_path)
    conn.row_factory = sqlite3.Row
    init_db_conn = sqlite3.connect(temp_db_path)
    from app.db import DEFAULT_SCHEMA

    with init_db_conn:
        init_db_conn.executescript(DEFAULT_SCHEMA)
    init_db_conn.close()

    sync_repo = SyncMetadataRepository(connection=conn)
    route_repo = BusRouteRepository(connection=conn)
    stop_repo = BusStopRepository(connection=conn)
    station_repo = StationRepository(connection=conn)

    assert sync_repo.conn is conn
    assert route_repo.conn is conn
    assert stop_repo.conn is conn
    assert station_repo.conn is conn

    sync_repo.record_sync_success("bus_routes", 1)
    assert sync_repo.get("bus_routes")["records_count"] == 1

    route_repo.bulk_upsert([{"route_number": "10"}])
    assert route_repo.count() == 1

    stop_repo.bulk_upsert([{"atco_code": "STOP1", "name": "Stop One"}])
    assert stop_repo.count() == 1

    station_repo.bulk_upsert([{"crs_code": "STN1", "name": "Station One"}])
    assert station_repo.count() == 1

    conn.close()


def test_sync_metadata_datetime_object_parsing(app: Flask) -> None:
    """Test is_due_for_update when last_updated_at is a datetime object or timezone naive."""
    import datetime

    with app.app_context():
        # Mock connection to return datetime objects
        mock_conn = MagicMock()

        mock_cursor = MagicMock()
        dt_naive = datetime.datetime(2026, 1, 1, 12, 0, 0)
        mock_cursor.fetchone.return_value = {"last_updated_at": dt_naive}
        mock_conn.cursor.return_value = mock_cursor

        repo_mock = SyncMetadataRepository(connection=mock_conn)
        assert repo_mock.is_due_for_update("bus_routes", max_age_seconds=3600) is True

        dt_recent = datetime.datetime.now(datetime.timezone.utc)
        mock_cursor.fetchone.return_value = {"last_updated_at": dt_recent}
        assert repo_mock.is_due_for_update("bus_routes", max_age_seconds=3600) is False

        # String datetime standard SQLite format
        mock_cursor.fetchone.return_value = {"last_updated_at": "2026-08-15 14:00:00"}
        assert repo_mock.is_due_for_update("bus_routes", max_age_seconds=86400) is False

        # Unparseable string fallback
        mock_cursor.fetchone.return_value = {
            "last_updated_at": "invalid-datetime-string"
        }
        assert repo_mock.is_due_for_update("bus_routes") is True

        # Non string / non datetime fallback
        mock_cursor.fetchone.return_value = {"last_updated_at": 123456789}
        assert repo_mock.is_due_for_update("bus_routes") is True


def test_get_db_stats_operational_error_handling(temp_db_path: str) -> None:
    """Test get_db_stats gracefully handles operational error during updated_at inspection."""
    conn = sqlite3.connect(temp_db_path)
    conn.row_factory = sqlite3.Row
    with conn:
        conn.execute("CREATE TABLE test_op_err (id INT, updated_at TEXT)")
        conn.execute("INSERT INTO test_op_err VALUES (1, '2026-08-15')")

    class FailingExecuteWrapper:
        def __init__(self, real_conn):
            self._real = real_conn

        def cursor(self):
            return self._real.cursor()

        def execute(self, query, *args):
            if "SELECT MAX(updated_at)" in query:
                raise sqlite3.OperationalError("Simulated query failure")
            return self._real.execute(query, *args)

    wrapped = FailingExecuteWrapper(conn)
    stats = get_db_stats(connection=wrapped)  # type: ignore
    tbl = next(t for t in stats["tables"] if t["name"] == "test_op_err")
    assert tbl["last_updated_at"] is None
    conn.close()
