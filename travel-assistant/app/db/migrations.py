"""Database schema migration module for Travel Assistant.

Executes declarative and safe schema migrations using Peewee's native
SqliteMigrator to ensure database structures remain up-to-date across versions.
"""

from __future__ import annotations

import logging
import uuid

import peewee
from peewee import SqliteDatabase
from playhouse.migrate import SqliteMigrator, migrate

logger = logging.getLogger(__name__)


def cleanup_legacy_tables(database: SqliteDatabase) -> None:
    """Remove obsolete legacy database tables if present."""
    legacy_tables = [
        "bus_stops",
        "stations",
        "location_transfers",
        "rail_references",
    ]
    for table in legacy_tables:
        try:
            database.execute_sql(f'DROP TABLE IF EXISTS "{table}"')
        except Exception as err:
            logger.debug("Failed to drop legacy table %s: %s", table, err)


def ensure_tables_and_virtual_tables(database: SqliteDatabase) -> None:
    """Ensure all core schema models and R*Tree virtual tables exist."""
    from app.models.journey import Journey
    from app.models.location import Location
    from app.models.mcp import MCPTool
    from app.models.setting import Setting
    from app.models.timetable import Timetable
    from app.models.transfer import PlatformTransfer
    from app.models.transit import (
        BusRoute,
        Stop,
        StopInterchange,
        SyncMetadata,
    )
    from app.models.walking import Walking

    all_models = [
        Setting,
        Timetable,
        SyncMetadata,
        BusRoute,
        Stop,
        StopInterchange,
        PlatformTransfer,
        Location,
        Journey,
        Walking,
        MCPTool,
    ]

    with database.bind_ctx(all_models):
        database.create_tables(all_models, safe=True)

    try:
        database.execute_sql("""
            CREATE VIRTUAL TABLE IF NOT EXISTS "stops_rtree" USING rtree(
                id,
                min_easting, max_easting,
                min_northing, max_northing
            )
        """)
    except Exception as err:
        logger.debug("stops_rtree virtual table creation deferred: %s", err)


def migrate_locations_schema(
    database: SqliteDatabase, migrator: SqliteMigrator
) -> None:
    """Migrate legacy integer-ID locations schema to UUID/slug ID format with HA flag."""
    from app.models.location import Location

    try:
        cursor = database.execute_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='locations'"
        )
        if not cursor.fetchone():
            return

        col_cursor = database.execute_sql('PRAGMA table_info("locations")')
        col_info = {col[1]: col[2].upper() for col in col_cursor.fetchall()}
        cols = list(col_info.keys())
        id_type = col_info.get("id", "")

        # Check if migration is needed: id is INTEGER/AutoField or ha column missing
        if "INTEGER" in id_type or "ha" not in cols:
            with database.atomic():
                migrate(migrator.rename_table("locations", "_locations_old"))
                with database.bind_ctx([Location]):
                    Location.create_table(safe=True)

                old_col_cursor = database.execute_sql(
                    'PRAGMA table_info("_locations_old")'
                )
                old_cols = [col[1] for col in old_col_cursor.fetchall()]
                has_ha = "ha" in old_cols
                has_created = "created_at" in old_cols
                has_updated = "updated_at" in old_cols

                select_cursor = database.execute_sql('SELECT * FROM "_locations_old"')
                rows = select_cursor.fetchall()
                for row in rows:
                    row_dict = dict(zip(old_cols, row))
                    name = row_dict.get("name", "")
                    lat = row_dict.get("latitude", 0.0)
                    lon = row_dict.get("longitude", 0.0)
                    is_ha = bool(row_dict.get("ha", 0)) if has_ha else False

                    raw_id = row_dict.get("id")
                    if is_ha:
                        slug = name.lower().replace(" ", "_").replace("-", "_").strip()
                        new_id = f"ha:{slug}"
                    elif isinstance(raw_id, str) and raw_id.startswith("custom:"):
                        new_id = raw_id
                    else:
                        new_id = f"custom:{uuid.uuid4().hex[:8]}"

                    created = row_dict.get("created_at") if has_created else None
                    updated = row_dict.get("updated_at") if has_updated else None

                    database.execute_sql(
                        'INSERT OR REPLACE INTO "locations" '
                        "(id, name, latitude, longitude, ha, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, "
                        "COALESCE(?, CURRENT_TIMESTAMP), COALESCE(?, CURRENT_TIMESTAMP))",
                        (
                            new_id,
                            name,
                            lat,
                            lon,
                            1 if is_ha else 0,
                            created,
                            updated,
                        ),
                    )

                migrate(migrator.drop_table("_locations_old"))
    except Exception as err:
        logger.warning("Locations table migration encountered an issue: %s", err)


def migrate_timetables_schema(
    database: SqliteDatabase, migrator: SqliteMigrator
) -> None:
    """Migrate legacy timetables schema to modern schema with calendar and content fields."""
    from app.models.timetable import Timetable

    try:
        cursor = database.execute_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='timetables'"
        )
        if not cursor.fetchone():
            return

        col_cursor = database.execute_sql('PRAGMA table_info("timetables")')
        cols = [col[1] for col in col_cursor.fetchall()]
        if (
            "transport_type" not in cols
            or "content" not in cols
            or "start_date" not in cols
            or "auto_added" not in cols
        ):
            has_created = "created_at" in cols
            has_updated = "updated_at" in cols
            created_col = '"created_at"' if has_created else "CURRENT_TIMESTAMP"
            updated_col = '"updated_at"' if has_updated else "CURRENT_TIMESTAMP"
            name_col = '"name"' if "name" in cols else "''"
            transport_type_col = (
                '"transport_type"' if "transport_type" in cols else "'bus'"
            )
            start_date_col = '"start_date"' if "start_date" in cols else "NULL"
            end_date_col = '"end_date"' if "end_date" in cols else "NULL"
            monday_col = '"monday"' if "monday" in cols else "1"
            tuesday_col = '"tuesday"' if "tuesday" in cols else "1"
            wednesday_col = '"wednesday"' if "wednesday" in cols else "1"
            thursday_col = '"thursday"' if "thursday" in cols else "1"
            friday_col = '"friday"' if "friday" in cols else "1"
            saturday_col = '"saturday"' if "saturday" in cols else "1"
            sunday_col = '"sunday"' if "sunday" in cols else "1"
            bank_holiday_col = '"bank_holiday"' if "bank_holiday" in cols else "1"
            auto_added_col = '"auto_added"' if "auto_added" in cols else "0"
            content_col = (
                '"content"' if "content" in cols else '\'{"stops":[], "trips":[]}\''
            )

            with database.atomic():
                migrate(migrator.rename_table("timetables", "_timetables_old"))
                with database.bind_ctx([Timetable]):
                    Timetable.create_table(safe=True)

                database.execute_sql(f"""
                    INSERT INTO "timetables" (
                        "id", "created_at", "updated_at", "name", "transport_type",
                        "start_date", "end_date",
                        "monday", "tuesday", "wednesday", "thursday",
                        "friday", "saturday", "sunday", "bank_holiday", "auto_added", "content"
                    )
                    SELECT
                        "id", {created_col}, {updated_col}, {name_col}, {transport_type_col},
                        {start_date_col}, {end_date_col},
                        {monday_col}, {tuesday_col}, {wednesday_col}, {thursday_col},
                        {friday_col}, {saturday_col}, {sunday_col},
                        {bank_holiday_col}, {auto_added_col}, {content_col}
                    FROM "_timetables_old"
                """)
                migrate(migrator.drop_table("_timetables_old"))
    except Exception as err:
        logger.warning("Timetables table migration encountered an issue: %s", err)


def migrate_column_additions(
    database: SqliteDatabase, migrator: SqliteMigrator
) -> None:
    """Add newly introduced columns using SqliteMigrator."""
    # Walking table migrations
    try:
        cursor = database.execute_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='walking'"
        )
        if cursor.fetchone():
            col_cursor = database.execute_sql('PRAGMA table_info("walking")')
            cols = [col[1] for col in col_cursor.fetchall()]
            if "auto_generated" not in cols:
                migrate(
                    migrator.add_column(
                        "walking", "auto_generated", peewee.IntegerField(default=0)
                    )
                )
    except Exception as err:
        logger.warning("Walking column migration encountered an issue: %s", err)

    # Journeys table migrations
    try:
        cursor = database.execute_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='journeys'"
        )
        if cursor.fetchone():
            col_cursor = database.execute_sql('PRAGMA table_info("journeys")')
            cols = [col[1] for col in col_cursor.fetchall()]
            if "calculated_routes" not in cols:
                migrate(
                    migrator.add_column(
                        "journeys", "calculated_routes", peewee.TextField(null=True)
                    )
                )
    except Exception as err:
        logger.warning("Journeys column migration encountered an issue: %s", err)

    # Stops table migrations
    try:
        cursor = database.execute_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='stops'"
        )
        if cursor.fetchone():
            col_cursor = database.execute_sql('PRAGMA table_info("stops")')
            cols = [col[1] for col in col_cursor.fetchall()]
            ops = []
            if "easting" not in cols:
                ops.append(
                    migrator.add_column(
                        "stops", "easting", peewee.IntegerField(null=True)
                    )
                )
            if "northing" not in cols:
                ops.append(
                    migrator.add_column(
                        "stops", "northing", peewee.IntegerField(null=True)
                    )
                )
            if ops:
                migrate(*ops)
    except Exception as err:
        logger.warning("Stops column migration encountered an issue: %s", err)

    # Sync metadata table migrations
    try:
        cursor = database.execute_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sync_metadata'"
        )
        if cursor.fetchone():
            col_cursor = database.execute_sql('PRAGMA table_info("sync_metadata")')
            cols = [col[1] for col in col_cursor.fetchall()]
            if "sync_requested" not in cols:
                migrate(
                    migrator.add_column(
                        "sync_metadata",
                        "sync_requested",
                        peewee.IntegerField(default=0),
                    )
                )
    except Exception as err:
        logger.warning("Sync metadata column migration encountered an issue: %s", err)


def cleanup_sync_metadata_and_data(database: SqliteDatabase) -> None:
    """Clean up obsolete sync metadata entries and normalize timetable records."""
    from app.models.transit import SyncMetadata
    from app.sync.worker import SYNC_REGISTRY

    try:
        cursor = database.execute_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sync_metadata'"
        )
        if cursor.fetchone():
            valid_tables = [entry.table_name for entry in SYNC_REGISTRY]
            with database.bind_ctx([SyncMetadata]):
                SyncMetadata.cleanup_obsolete_entries(valid_tables)
    except Exception as err:
        logger.warning("Sync metadata cleanup encountered an issue: %s", err)

    try:
        # Clear legacy single-day end_date on auto_added rail timetables so recurring services stay active
        cursor = database.execute_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='timetables'"
        )
        if cursor.fetchone():
            database.execute_sql(
                "UPDATE timetables SET end_date = NULL "
                "WHERE auto_added = 1 AND transport_type = 'rail' AND end_date IS NOT NULL;"
            )
    except Exception as err:
        logger.warning("Rail timetable end_date cleanup encountered an issue: %s", err)


def migrate_mcp_tools_schema(
    database: SqliteDatabase, migrator: SqliteMigrator
) -> None:
    """Migrate MCP tools schema to binary enabled flag with opt-in defaults."""
    from app.models.mcp import MCPTool

    try:
        cursor = database.execute_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='mcp_tools'"
        )
        if not cursor.fetchone():
            return

        col_cursor = database.execute_sql('PRAGMA table_info("mcp_tools")')
        cols = [col[1] for col in col_cursor.fetchall()]
        if "access_level" in cols or "enabled" not in cols:
            with database.atomic():
                migrate(migrator.rename_table("mcp_tools", "_mcp_tools_old"))
                with database.bind_ctx([MCPTool]):
                    MCPTool.create_table(safe=True)

                has_created = "created_at" in cols
                has_updated = "updated_at" in cols
                created_col = (
                    'COALESCE("created_at", CURRENT_TIMESTAMP)'
                    if has_created
                    else "CURRENT_TIMESTAMP"
                )
                updated_col = (
                    'COALESCE("updated_at", CURRENT_TIMESTAMP)'
                    if has_updated
                    else "CURRENT_TIMESTAMP"
                )
                database.execute_sql(f"""
                    INSERT INTO "mcp_tools" (
                        "id", "created_at", "updated_at", "tool_name", "domain",
                        "description", "is_mutating", "enabled"
                    )
                    SELECT
                        "id", {created_col}, {updated_col}, "tool_name", "domain",
                        "description", "is_mutating", 0
                    FROM "_mcp_tools_old"
                """)
                migrate(migrator.drop_table("_mcp_tools_old"))
    except Exception as err:
        logger.warning("MCP tools table migration encountered an issue: %s", err)


def sync_mcp_registry(database: SqliteDatabase) -> None:
    """Synchronise registered MCP tools with database table."""
    from app.mcp.registry import sync_mcp_tools_with_db
    from app.models.mcp import MCPTool

    try:
        with database.bind_ctx([MCPTool]):
            sync_mcp_tools_with_db(database)
    except Exception as err:
        logger.debug("MCP tools synchronisation deferred: %s", err)


def run_migrations(database: SqliteDatabase) -> None:
    """Execute schema migrations using SqliteMigrator and ensure all tables are initialised."""
    logger.info("Verifying database tables and applying pending schema migrations...")
    migrator = SqliteMigrator(database)

    cleanup_legacy_tables(database)
    ensure_tables_and_virtual_tables(database)
    migrate_locations_schema(database, migrator)
    migrate_timetables_schema(database, migrator)
    migrate_column_additions(database, migrator)
    cleanup_sync_metadata_and_data(database)
    migrate_mcp_tools_schema(database, migrator)
    sync_mcp_registry(database)

    logger.info("Database schema verification and migrations complete.")
