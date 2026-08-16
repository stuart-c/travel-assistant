"""Unit tests for Peewee database configuration, models, and operations."""

import os
import pytest
from flask import Flask
from peewee import SqliteDatabase

from app.db import (
    create_sqlite_database,
    format_file_size,
    get_db_path,
    get_db_stats,
    init_app,
    run_migrations,
)
from app.models import (
    BusRoute,
    BusStop,
    Location,
    LocationTransfer,
    PlatformTransfer,
    Setting,
    Station,
    SyncMetadata,
    Timetable,
)


def test_format_file_size() -> None:
    """Test format_file_size conversion to British English units."""
    assert format_file_size(500) == "500 B"
    assert format_file_size(2048) == "2.0 KB"
    assert format_file_size(5 * 1024 * 1024) == "5.0 MB"
    assert format_file_size(2 * 1024 * 1024 * 1024) == "2.00 GB"


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


def test_get_db_path_ha_data_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_get_db_path_no_app_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test get_db_path with no app and no context creates default instance dir."""
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    monkeypatch.setattr(os.path, "exists", lambda p: False)
    monkeypatch.setattr(os, "makedirs", lambda p, exist_ok=True: None)
    path = get_db_path()
    assert path == os.path.join("instance", "travel_assistant.db")


def test_create_sqlite_database(tmp_path: pytest.TempPathFactory) -> None:
    """Test create_sqlite_database configures WAL pragmas and creates parent dir."""
    db_file = str(tmp_path / "sub_dir" / "test.db")
    database = create_sqlite_database(db_file)
    assert isinstance(database, SqliteDatabase)
    assert any(p[0] == "journal_mode" and p[1] == "wal" for p in database._pragmas)


def test_init_app(app: Flask) -> None:
    """Test init_app attaches database to Flask application."""
    test_app = Flask(__name__)
    test_app.config["DATABASE_PATH"] = ":memory:"
    init_app(test_app)
    assert "DATABASE" in test_app.config


def test_setting_model_operations(app: Flask) -> None:
    """Test Setting Peewee model CRUD operations and helper methods."""
    with app.app_context():
        assert Setting.get_val("missing_key") == ""
        assert Setting.get_val("missing_key", default="fallback") == "fallback"

        item = Setting.set_val("bus_api_key", "secret123", category="credentials")
        assert item.key == "bus_api_key"
        assert item.value == "secret123"
        assert item.category == "credentials"
        assert Setting.get_val("bus_api_key") == "secret123"

        # Update existing
        item2 = Setting.set_val("bus_api_key", "secret456", category="credentials")
        assert item2.value == "secret456"
        assert Setting.get_val("bus_api_key") == "secret456"

        # None value
        Setting.set_val("null_key", None)
        assert Setting.get_val("null_key") == ""

        # Bulk set
        Setting.bulk_set({"key1": "val1", "key2": "val2"}, category="test_cat")
        assert Setting.get_val("key1") == "val1"
        assert Setting.get_val("key2") == "val2"

        # Get all dict
        all_dict = Setting.get_all_dict()
        assert all_dict["bus_api_key"] == "secret456"
        assert all_dict["key1"] == "val1"

        # Get by category
        cat_dict = Setting.get_by_category("test_cat")
        assert cat_dict == {"key1": "val1", "key2": "val2"}

        # to_dict
        s_dict = item2.to_dict()
        assert s_dict["key"] == "bus_api_key"
        assert s_dict["value"] == "secret456"
        assert "updated_at" in s_dict

        # Delete key
        assert Setting.delete_key("key1") is True
        assert Setting.delete_key("nonexistent") is False
        assert Setting.get_val("key1") == ""


def test_bus_route_model(app: Flask) -> None:
    """Test BusRoute model bulk_upsert and query methods."""
    with app.app_context():
        routes = [
            {
                "route_number": "1",
                "operator_name": "Oxford Bus",
                "operator_code": "OBC",
                "origin": "Blackbird Leys",
                "destination": "City Centre",
                "description": "Frequent city bus",
            },
            {
                "route_number": "5",
                "operator_name": "Oxford Bus",
                "operator_code": "OBC",
                "origin": "Blackbird Leys",
                "destination": "Rail Station",
                "description": "Rail link",
            },
            {"route_number": ""},  # Invalid, should be skipped
        ]
        assert BusRoute.bulk_upsert([]) == 0
        inserted = BusRoute.bulk_upsert(routes)
        assert inserted == 2

        # Get by route number
        res = BusRoute.get_by_route_number("1")
        assert len(res) == 1
        assert res[0].operator_name == "Oxford Bus"

        # Search
        search_res = BusRoute.search("Rail")
        assert len(search_res) == 1
        assert search_res[0].route_number == "5"

        # Get all
        all_res = BusRoute.get_all(limit=10)
        assert len(all_res) == 2


def test_bus_stop_model(app: Flask) -> None:
    """Test BusStop model upsert, on_conflict resolution, and search."""
    with app.app_context():
        stops = [
            {
                "atco_code": "340000001",
                "naptan_code": "oxfgpa",
                "name": "Frideswide Square",
                "indicator": "R1",
                "locality": "Oxford",
                "latitude": 51.753,
                "longitude": -1.269,
            },
            {
                "atco_code": "340000002",
                "naptan_code": "oxfgpb",
                "name": "Gloucester Green",
                "indicator": "Bay 1",
                "locality": "Oxford",
                "latitude": 51.754,
                "longitude": -1.262,
            },
            {"atco_code": ""},  # invalid
        ]
        assert BusStop.bulk_upsert([]) == 0
        BusStop.bulk_upsert(stops)

        stop = BusStop.get_by_atco("340000001")
        assert stop is not None
        assert stop.name == "Frideswide Square"

        # Non-existent
        assert BusStop.get_by_atco("999999999") is None

        # Upsert with updated name on conflict
        updated_stops = [
            {
                "atco_code": "340000001",
                "naptan_code": "oxfgpa",
                "name": "Frideswide Square (Renamed)",
                "indicator": "R1",
                "locality": "Oxford Central",
                "latitude": 51.753,
                "longitude": -1.269,
            }
        ]
        BusStop.bulk_upsert(updated_stops)
        stop_after = BusStop.get_by_atco("340000001")
        assert stop_after.name == "Frideswide Square (Renamed)"
        assert stop_after.locality == "Oxford Central"

        # Search
        search_res = BusStop.search("Gloucester")
        assert len(search_res) == 1
        assert search_res[0].atco_code == "340000002"

        # Get all
        all_stops = BusStop.get_all(limit=10)
        assert len(all_stops) == 2


def test_station_model(app: Flask) -> None:
    """Test Station model upsert, on_conflict update, and lookup."""
    with app.app_context():
        stations = [
            {
                "crs_code": "oxf",
                "name": "Oxford",
                "tiploc_code": "OXFD",
                "latitude": 51.753,
                "longitude": -1.269,
                "operator": "GWR",
            },
            {
                "crs_code": "pad",
                "name": "London Paddington",
                "tiploc_code": "PADTON",
                "latitude": 51.517,
                "longitude": -0.177,
                "operator": "GWR",
            },
            {"crs_code": ""},  # invalid
        ]
        assert Station.bulk_upsert([]) == 0
        Station.bulk_upsert(stations)

        st = Station.get_by_crs("OXF")
        assert st is not None
        assert st.name == "Oxford"
        assert st.crs_code == "OXF"

        assert Station.get_by_crs("XYZ") is None

        # Upsert with update
        updated_st = [
            {
                "crs_code": "OXF",
                "name": "Oxford Central Station",
                "tiploc_code": "OXFD",
                "latitude": 51.753,
                "longitude": -1.269,
                "operator": "Chiltern",
            }
        ]
        Station.bulk_upsert(updated_st)
        st_after = Station.get_by_crs("OXF")
        assert st_after.name == "Oxford Central Station"
        assert st_after.operator == "Chiltern"

        # Search
        res = Station.search("Paddington")
        assert len(res) == 1
        assert res[0].crs_code == "PAD"

        # Get all
        all_st = Station.get_all()
        assert len(all_st) == 2


def test_sync_metadata_model(app: Flask) -> None:
    """Test SyncMetadata state transitions and telemetry recording."""
    with app.app_context():
        assert SyncMetadata.get_meta("bus_routes") is None
        assert SyncMetadata.is_due_for_update("bus_routes") is True

        # Start
        SyncMetadata.record_start("bus_routes")
        meta = SyncMetadata.get_meta("bus_routes")
        assert meta is not None
        assert meta.status == "syncing"

        # Success
        SyncMetadata.record_success("bus_routes", 50, 1.25)
        meta2 = SyncMetadata.get_meta("bus_routes")
        assert meta2.status == "success"
        assert meta2.records_count == 50
        assert meta2.duration_seconds == 1.25
        assert meta2.error_message is None
        assert (
            SyncMetadata.is_due_for_update("bus_routes", max_age_seconds=3600) is False
        )

        # Error
        SyncMetadata.record_error("bus_stops", "Network timed out", 5.0)
        meta_err = SyncMetadata.get_meta("bus_stops")
        assert meta_err.status == "error"
        assert meta_err.error_message == "Network timed out"

        # Skipped
        SyncMetadata.record_skipped("stations", "No credentials")
        meta_skip = SyncMetadata.get_meta("stations")
        assert meta_skip.status == "skipped"
        assert meta_skip.error_message == "No credentials"


def test_timetable_model(app: Flask) -> None:
    """Test Timetable model search and summary statistics."""
    with app.app_context():
        t1 = Timetable.create(
            name="Weekday Morning Commute",
            start_date="2026-09-01",
            end_date="2026-12-31",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
            saturday=False,
            sunday=False,
            bank_holiday=False,
        )
        t2 = Timetable.create(
            name="Weekend Leisure Schedule",
            start_date=None,
            end_date=None,
            monday=False,
            tuesday=False,
            wednesday=False,
            thursday=False,
            friday=False,
            saturday=True,
            sunday=True,
            bank_holiday=True,
        )
        t3 = Timetable.create(
            name="Bank Holiday Special",
            start_date="2026-08-25",
            end_date="2026-08-25",
            monday=True,
            tuesday=False,
            wednesday=False,
            thursday=False,
            friday=False,
            saturday=False,
            sunday=False,
            bank_holiday=True,
        )

        stats = Timetable.get_stats()
        assert stats["total"] == 3

        # Search
        res1 = Timetable.search(query="Commute")
        assert len(res1) == 1
        assert res1[0].name == "Weekday Morning Commute"
        assert res1[0].monday is True
        assert res1[0].saturday is False
        assert res1[0].start_date.isoformat() == "2026-09-01"

        res2 = Timetable.search(query="Special")
        assert len(res2) == 1
        assert res2[0].name == "Bank Holiday Special"

        # to_dict verification
        t1_dict = t1.to_dict()
        assert t1_dict["name"] == "Weekday Morning Commute"
        assert t1_dict["start_date"] == "2026-09-01"
        assert t1_dict["end_date"] == "2026-12-31"
        assert t1_dict["monday"] is True
        assert t1_dict["saturday"] is False

        t2_dict = t2.to_dict()
        assert t2_dict["name"] == "Weekend Leisure Schedule"
        assert t2_dict["start_date"] is None
        assert t2_dict["saturday"] is True

        t3_dict = t3.to_dict()
        assert t3_dict["name"] == "Bank Holiday Special"
        assert t3_dict["bank_holiday"] is True


def test_transfer_models(app: Flask) -> None:
    """Test LocationTransfer and PlatformTransfer models and lookup."""
    with app.app_context():
        loc_t = LocationTransfer.create(
            from_type="station",
            from_id="OXF",
            from_name="Oxford Rail Station",
            to_type="bus_stop",
            to_id="340000001",
            to_name="Frideswide Square",
            transfer_time_minutes=3,
            bidirectional=True,
            step_free=True,
            notes="Walk via forecourt",
        )

        plat_t = PlatformTransfer.create(
            location_type="station",
            location_id="OXF",
            location_name="Oxford Rail Station",
            from_platform="1",
            to_platform="2",
            transfer_time_minutes=2,
            bidirectional=True,
            step_free=True,
            notes="Footbridge with lift",
        )

        # Direct search
        loc_search = LocationTransfer.search(query="Frideswide", step_free=True)
        assert len(loc_search) == 1
        assert loc_search[0].transfer_time_minutes == 3

        # LocationTransfer find_transfer direct and reverse
        t1 = LocationTransfer.find_transfer("station", "OXF", "bus_stop", "340000001")
        assert t1 is not None
        assert t1.id == loc_t.id

        t2 = LocationTransfer.find_transfer("bus_stop", "340000001", "station", "OXF")
        assert t2 is not None
        assert t2.id == loc_t.id

        # PlatformTransfer find_transfer
        pt1 = PlatformTransfer.find_transfer("OXF", "1", "2")
        assert pt1 is not None
        assert pt1.id == plat_t.id

        pt2 = PlatformTransfer.find_transfer("OXF", "2", "1")
        assert pt2 is not None
        assert pt2.id == plat_t.id

        assert PlatformTransfer.find_transfer("OXF", "1", "9") is None

        # PlatformTransfer search
        plat_search = PlatformTransfer.search(query="Footbridge", location_id="OXF")
        assert len(plat_search) == 1


def test_get_db_stats(app: Flask) -> None:
    """Test get_db_stats produces metrics and table telemetry."""
    with app.app_context():
        Setting.set_val("test_key", "test_val")
        BusRoute.bulk_upsert([{"route_number": "10"}])
        SyncMetadata.record_success("bus_routes", 1, 0.5)

        stats = get_db_stats(app)
        assert stats["total_tables"] >= 8
        assert stats["total_rows"] >= 3
        assert "file_size_formatted" in stats
        assert any(t["name"] == "settings" for t in stats["tables"])
        assert any(
            t["name"] == "bus_routes" and t["sync_status"] == "success"
            for t in stats["tables"]
        )


def test_timetable_schema_migration(tmp_path: pytest.TempPathFactory) -> None:
    """Test run_migrations upgrades legacy timetables schema without dropping existing rows."""
    db_file = str(tmp_path / "legacy_timetable_test.db")
    test_db = SqliteDatabase(db_file)
    test_db.connect()

    # Create legacy table definition without new schedule fields
    test_db.execute_sql("""
        CREATE TABLE "timetables" (
            "id" INTEGER PRIMARY KEY AUTOINCREMENT,
            "created_at" DATETIME NOT NULL,
            "updated_at" DATETIME NOT NULL,
            "transport_type" VARCHAR(50) NOT NULL,
            "name" VARCHAR(255) NOT NULL,
            "identifier" VARCHAR(255) NOT NULL,
            "status" VARCHAR(255) NOT NULL DEFAULT 'active'
        );
        """)
    test_db.execute_sql("""
        INSERT INTO "timetables" (
            "created_at", "updated_at", "transport_type", "name", "identifier", "status"
        ) VALUES (
            '2026-08-15 12:00:00', '2026-08-15 12:00:00', 'bus',
            'Oxford Tube Express', 'OX-TUBE', 'active'
        );
        """)

    # Run migrations
    run_migrations(test_db)

    # Inspect columns
    col_cursor = test_db.execute_sql('PRAGMA table_info("timetables")')
    cols = [col[1] for col in col_cursor.fetchall()]
    assert "start_date" in cols
    assert "end_date" in cols
    assert "monday" in cols
    assert "sunday" in cols
    assert "bank_holiday" in cols

    # Verify querying and to_dict work seamlessly with Peewee model
    with test_db.bind_ctx([Timetable]):
        entries = list(Timetable.select())
        assert len(entries) == 1
        t = entries[0]
        assert t.name == "Oxford Tube Express"
        assert t.start_date is None
        assert t.end_date is None
        assert t.monday is True
        assert t.bank_holiday is True

        d = t.to_dict()
        assert d["name"] == "Oxford Tube Express"
        assert d["start_date"] is None
        assert d["monday"] is True

        # Verify insert and retrieval from migrated schema
        t2 = Timetable.create(
            name="New Commute Schedule",
            start_date="2026-09-01",
            end_date="2026-12-31",
            monday=True,
            saturday=False,
        )
        assert t2.id is not None
        queried_t2 = Timetable.get_by_id(t2.id)
        assert queried_t2.start_date.isoformat() == "2026-09-01"

    test_db.close()


def test_location_schema_migration(tmp_path: pytest.TempPathFactory) -> None:
    """Test run_migrations upgrades legacy locations schema to add ha flag."""
    db_file = str(tmp_path / "legacy_location_test.db")
    test_db = SqliteDatabase(db_file)
    test_db.connect()

    # Create legacy table definition without ha column
    test_db.execute_sql("""
        CREATE TABLE "locations" (
            "id" INTEGER PRIMARY KEY AUTOINCREMENT,
            "created_at" DATETIME NOT NULL,
            "updated_at" DATETIME NOT NULL,
            "name" VARCHAR(255) NOT NULL,
            "latitude" REAL NOT NULL,
            "longitude" REAL NOT NULL
        );
        """)
    test_db.execute_sql("""
        INSERT INTO "locations" (
            "created_at", "updated_at", "name", "latitude", "longitude"
        ) VALUES (
            '2026-08-15 12:00:00', '2026-08-15 12:00:00', 'Central Office', 51.753, -1.26
        );
        """)

    # Run migrations
    run_migrations(test_db)

    # Inspect columns
    col_cursor = test_db.execute_sql('PRAGMA table_info("locations")')
    cols = [col[1] for col in col_cursor.fetchall()]
    assert "ha" in cols

    with test_db.bind_ctx([Location]):
        locs = list(Location.select())
        assert len(locs) == 1
        assert locs[0].name == "Central Office"
        assert locs[0].ha is False
        assert locs[0].id.startswith("custom:")
        assert len(locs[0].id) > 7

    test_db.close()
