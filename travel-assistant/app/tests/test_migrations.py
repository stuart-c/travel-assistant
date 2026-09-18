"""Unit tests for declarative Peewee schema migrations."""

import pytest
from peewee import SqliteDatabase
from playhouse.migrate import SqliteMigrator

from app.db.migrations import (
    cleanup_legacy_tables,
    cleanup_sync_metadata_and_data,
    ensure_tables_and_virtual_tables,
    migrate_column_additions,
    migrate_locations_schema,
    migrate_mcp_tools_schema,
    migrate_timetables_schema,
    run_migrations,
)
from app.models.location import Location
from app.models.mcp import MCPTool
from app.models.timetable import Timetable
from app.models.transit import SyncMetadata


def test_cleanup_legacy_tables(tmp_path: pytest.TempPathFactory) -> None:
    """Test cleanup_legacy_tables removes deprecated tables."""
    db_file = str(tmp_path / "legacy_tables.db")
    database = SqliteDatabase(db_file)
    database.connect()

    database.execute_sql('CREATE TABLE "bus_stops" (id INTEGER PRIMARY KEY);')
    database.execute_sql('CREATE TABLE "stations" (id INTEGER PRIMARY KEY);')
    database.execute_sql('CREATE TABLE "location_transfers" (id INTEGER PRIMARY KEY);')
    database.execute_sql('CREATE TABLE "rail_references" (id INTEGER PRIMARY KEY);')

    cleanup_legacy_tables(database)

    cursor = database.execute_sql(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    remaining = [row[0] for row in cursor.fetchall()]
    assert "bus_stops" not in remaining
    assert "stations" not in remaining
    assert "location_transfers" not in remaining
    assert "rail_references" not in remaining
    database.close()


def test_ensure_tables_and_virtual_tables(tmp_path: pytest.TempPathFactory) -> None:
    """Test ensure_tables_and_virtual_tables creates tables and R*Tree virtual table."""
    db_file = str(tmp_path / "ensure_tables.db")
    database = SqliteDatabase(db_file)
    database.connect()

    ensure_tables_and_virtual_tables(database)

    cursor = database.execute_sql(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    table_names = [row[0] for row in cursor.fetchall()]
    assert "settings" in table_names
    assert "timetables" in table_names
    assert "stops" in table_names
    assert "journeys" in table_names
    assert "walking" in table_names
    assert "mcp_tools" in table_names
    database.close()


def test_migrate_column_additions_declarative(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Test migrate_column_additions adds missing columns to existing tables."""
    db_file = str(tmp_path / "column_additions.db")
    database = SqliteDatabase(db_file)
    database.connect()

    database.execute_sql('CREATE TABLE "walking" (id INTEGER PRIMARY KEY);')
    database.execute_sql('CREATE TABLE "journeys" (id INTEGER PRIMARY KEY);')
    database.execute_sql('CREATE TABLE "stops" (id INTEGER PRIMARY KEY);')
    database.execute_sql(
        'CREATE TABLE "sync_metadata" (table_name VARCHAR(255) PRIMARY KEY);'
    )

    migrator = SqliteMigrator(database)
    migrate_column_additions(database, migrator)

    walking_cols = [
        c[1] for c in database.execute_sql('PRAGMA table_info("walking")').fetchall()
    ]
    assert "auto_generated" in walking_cols

    journeys_cols = [
        c[1] for c in database.execute_sql('PRAGMA table_info("journeys")').fetchall()
    ]
    assert "calculated_routes" in journeys_cols

    stops_cols = [
        c[1] for c in database.execute_sql('PRAGMA table_info("stops")').fetchall()
    ]
    assert "easting" in stops_cols
    assert "northing" in stops_cols

    sync_cols = [
        c[1]
        for c in database.execute_sql('PRAGMA table_info("sync_metadata")').fetchall()
    ]
    assert "sync_requested" in sync_cols
    database.close()


def test_migrate_locations_ha_slug_generation(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Test migrate_locations_schema formats HA location IDs as ha:slug."""
    db_file = str(tmp_path / "locations_slug.db")
    database = SqliteDatabase(db_file)
    database.connect()

    database.execute_sql("""
        CREATE TABLE "locations" (
            "id" INTEGER PRIMARY KEY AUTOINCREMENT,
            "created_at" DATETIME,
            "updated_at" DATETIME,
            "name" VARCHAR(255) NOT NULL,
            "latitude" REAL NOT NULL,
            "longitude" REAL NOT NULL,
            "ha" INTEGER DEFAULT 1
        );
    """)
    database.execute_sql("""
        INSERT INTO "locations" ("name", "latitude", "longitude", "ha")
        VALUES ('King''s Cross Station', 51.53, -0.12, 1);
    """)

    migrator = SqliteMigrator(database)
    migrate_locations_schema(database, migrator)

    with database.bind_ctx([Location]):
        loc = Location.get()
        assert loc.id == "ha:king's_cross_station"
        assert loc.ha is True
        assert loc.name == "King's Cross Station"

    database.close()


def test_migrate_locations_noop_when_modern(tmp_path: pytest.TempPathFactory) -> None:
    """Test migrate_locations_schema is a no-op when already modern schema."""
    db_file = str(tmp_path / "locations_modern.db")
    database = SqliteDatabase(db_file)
    database.connect()

    with database.bind_ctx([Location]):
        Location.create_table()
        Location.create(
            id="custom:abc12345",
            name="London King's Cross",
            latitude=51.53,
            longitude=-0.12,
            ha=False,
        )

    migrator = SqliteMigrator(database)
    migrate_locations_schema(database, migrator)

    with database.bind_ctx([Location]):
        assert Location.select().count() == 1

    database.close()


def test_migrate_timetables_noop_when_modern(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Test migrate_timetables_schema is a no-op when already modern schema."""
    db_file = str(tmp_path / "timetables_modern.db")
    database = SqliteDatabase(db_file)
    database.connect()

    with database.bind_ctx([Timetable]):
        Timetable.create_table()
        Timetable.create(
            name="Route 73",
            transport_type="bus",
            auto_added=True,
        )

    migrator = SqliteMigrator(database)
    migrate_timetables_schema(database, migrator)

    with database.bind_ctx([Timetable]):
        assert Timetable.select().count() == 1

    database.close()


def test_migrate_mcp_tools_noop_when_modern(tmp_path: pytest.TempPathFactory) -> None:
    """Test migrate_mcp_tools_schema is a no-op when already modern schema."""
    db_file = str(tmp_path / "mcp_tools_modern.db")
    database = SqliteDatabase(db_file)
    database.connect()

    with database.bind_ctx([MCPTool]):
        MCPTool.create_table()
        MCPTool.create(
            tool_name="journey_list",
            domain="journeys",
            description="List journeys",
            is_mutating=False,
            enabled=True,
        )

    migrator = SqliteMigrator(database)
    migrate_mcp_tools_schema(database, migrator)

    with database.bind_ctx([MCPTool]):
        tool = MCPTool.get(MCPTool.tool_name == "journey_list")
        assert tool.enabled is True

    database.close()


def test_run_migrations_full_lifecycle(tmp_path: pytest.TempPathFactory) -> None:
    """Test run_migrations master coordinator handles fresh and subsequent runs cleanly."""
    db_file = str(tmp_path / "lifecycle.db")
    database = SqliteDatabase(db_file)
    database.connect()

    # Initial migration run
    run_migrations(database)

    # Secondary migration run (idempotent)
    run_migrations(database)

    # Verify tables present
    cursor = database.execute_sql(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    tables = {row[0] for row in cursor.fetchall()}
    assert "settings" in tables
    assert "timetables" in tables
    assert "sync_metadata" in tables
    assert "stops" in tables
    assert "locations" in tables
    assert "journeys" in tables
    assert "walking" in tables
    assert "mcp_tools" in tables

    database.close()


def test_cleanup_sync_metadata_and_data(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Test cleanup_sync_metadata_and_data cleans obsolete tables and rail end dates."""
    db_file = str(tmp_path / "cleanup_sync.db")
    database = SqliteDatabase(db_file)
    database.connect()

    with database.bind_ctx([SyncMetadata, Timetable]):
        SyncMetadata.create_table()
        Timetable.create_table()

        SyncMetadata.create(
            table_name="legacy_nonexistent_table",
            status="success",
            records_count=10,
            duration_seconds=0.5,
        )
        Timetable.create(
            name="London East Coast Express",
            transport_type="rail",
            auto_added=True,
            start_date="2026-09-01",
            end_date="2026-09-01",
        )

    cleanup_sync_metadata_and_data(database)

    with database.bind_ctx([SyncMetadata, Timetable]):
        assert (
            SyncMetadata.select()
            .where(SyncMetadata.table_name == "legacy_nonexistent_table")
            .count()
            == 0
        )
        tt = Timetable.get(Timetable.name == "London East Coast Express")
        assert tt.end_date is None

    database.close()
