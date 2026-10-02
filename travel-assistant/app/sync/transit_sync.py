"""Transit dataset synchronisation manager and orchestrator.

Orchestrates background and on-demand synchronisation for bus routes,
bus stops, and rail station datasets using modular datasource clients.
"""

import logging
from typing import Any, Dict, Optional
from flask import Flask

from app.datasources import NaptanClient
from app.db import db
from app.models import Stop
from app.sync.common import run_sync_task

logger = logging.getLogger(__name__)

DEFAULT_INTERCHANGE_RADIUS_METRES = 250.0
WALKING_METRES_PER_MINUTE = 80.0


def sync_stops(app: Optional[Flask] = None) -> Dict[str, Any]:
    """Synchronise transit access nodes (bus, rail, metro, tram, ferry) using UK NaPTAN dataset."""

    def _perform_sync() -> int:
        logger.info("Fetching UK public transport stops from NaPTAN dataset...")
        client = NaptanClient.from_settings()
        stops_to_upsert = client.fetch_stops()
        if stops_to_upsert:
            logger.info(
                "Upserting %d transit stop records into database...",
                len(stops_to_upsert),
            )
            Stop.bulk_upsert(stops_to_upsert)
        return len(stops_to_upsert)

    return run_sync_task(
        table_name="stops",
        sync_operation=_perform_sync,
        connection_error_template="Network or connection error while contacting NaPTAN: {error}",
        success_message_factory=lambda cnt: (
            f"Successfully synchronised {cnt} UK transit stops from NaPTAN."
        ),
        app=app,
    )


def populate_stops_rtree(database: Optional[Any] = None) -> int:
    """Populate the SQLite stops_rtree virtual table with current stops coordinates."""
    db_conn = database or db.obj
    with db_conn.connection_context():
        db_conn.execute_sql("""
            CREATE VIRTUAL TABLE IF NOT EXISTS "stops_rtree" USING rtree(
                id,
                min_easting, max_easting,
                min_northing, max_northing
            )
            """)
        with db_conn.atomic():
            db_conn.execute_sql('DELETE FROM "stops_rtree"')
            db_conn.execute_sql("""
                INSERT INTO "stops_rtree" (id, min_easting, max_easting, min_northing, max_northing)
                SELECT id, easting, easting, northing, northing
                FROM "stops"
                WHERE easting IS NOT NULL AND northing IS NOT NULL
                """)
            cursor = db_conn.execute_sql('SELECT COUNT(*) FROM "stops_rtree"')
            row = cursor.fetchone()
            return row[0] if row else 0


def sync_table(
    table_name: str,
    force: bool = False,
    app: Optional[Flask] = None,
) -> Dict[str, Any]:
    """Synchronise a specific transit dataset table by name."""
    from app.sync.ha_sync import sync_ha_locations
    from app.sync.walking_sync import sync_walking_routes
    from app.sync.worker import SYNC_REGISTRY

    norm_name = table_name.lower().strip()
    valid_names = [e.table_name for e in SYNC_REGISTRY]

    if norm_name in ("stops", "transit_stops", "naptan"):
        return sync_stops(app=app)
    elif norm_name in ("ha_locations", "locations", "homeassistant"):
        return sync_ha_locations(app=app)
    elif norm_name in ("walking", "walking_routes"):
        return sync_walking_routes(app=app, force=force)
    else:
        err_msg = (
            f"Unknown or non-syncable table: '{norm_name}'. "
            f"Syncable tables are: {', '.join(valid_names)}."
        )
        logger.error(err_msg)
        return {
            "table": norm_name,
            "status": "error",
            "records": 0,
            "message": err_msg,
            "duration_seconds": 0.0,
        }
