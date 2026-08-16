"""Transit dataset synchronisation manager and orchestrator.

Orchestrates background and on-demand synchronisation for bus routes,
bus stops, and rail station datasets using modular datasource clients.
"""

import time
from typing import Any, Dict, Optional
from flask import Flask
import requests

from app.datasources import (
    BodsClient,
    DataSourceAuthError,
    DataSourceConfigError,
    DataSourceConnectionError,
    DataSourceError,
    NaptanClient,
)
from app.db import SYNCABLE_TABLES, db, init_db
from app.models import (
    BusRoute,
    Stop,
    SyncMetadata,
)
from app.sync.ha_sync import sync_ha_locations


def _ensure_db_initialized(app: Optional[Flask] = None) -> None:
    """Ensure Peewee DatabaseProxy has been initialized."""
    if db.obj is None:
        init_db(app)


def sync_bus_routes(app: Optional[Flask] = None) -> Dict[str, Any]:
    """Synchronise bus routes using configured Bus Open Data Service (BODS) credentials."""
    _ensure_db_initialized(app)
    start_time = time.time()

    with db.connection_context():
        client = BodsClient.from_settings()
        if not client.api_key:
            msg = "Bus API Key not configured in Settings > API Credentials"
            SyncMetadata.record_skipped("bus_routes", msg)
            return {
                "table": "bus_routes",
                "status": "skipped_no_credentials",
                "records": 0,
                "message": msg,
                "duration_seconds": 0.0,
            }

        SyncMetadata.record_start("bus_routes")

        try:
            routes_to_upsert = client.fetch_routes(limit=25)
            if routes_to_upsert:
                BusRoute.bulk_upsert(routes_to_upsert)

            duration = round(time.time() - start_time, 2)
            count = len(routes_to_upsert)
            SyncMetadata.record_success("bus_routes", count, duration)
            return {
                "table": "bus_routes",
                "status": "success",
                "records": count,
                "message": f"Successfully synchronised {count} bus route datasets from BODS.",
                "duration_seconds": duration,
            }
        except (DataSourceAuthError, DataSourceConfigError) as exc:
            duration = round(time.time() - start_time, 2)
            err_msg = str(exc)
            SyncMetadata.record_error("bus_routes", err_msg, duration)
            return {
                "table": "bus_routes",
                "status": "error",
                "records": 0,
                "message": err_msg,
                "duration_seconds": duration,
            }
        except DataSourceConnectionError as exc:
            duration = round(time.time() - start_time, 2)
            err_msg = f"Network or API error while contacting BODS: {str(exc)}"
            SyncMetadata.record_error("bus_routes", err_msg, duration)
            return {
                "table": "bus_routes",
                "status": "error",
                "records": 0,
                "message": err_msg,
                "duration_seconds": duration,
            }
        except Exception as exc:
            duration = round(time.time() - start_time, 2)
            err_msg = f"Unexpected error during bus route synchronisation: {str(exc)}"
            SyncMetadata.record_error("bus_routes", err_msg, duration)
            return {
                "table": "bus_routes",
                "status": "error",
                "records": 0,
                "message": err_msg,
                "duration_seconds": duration,
            }


def sync_stops(app: Optional[Flask] = None) -> Dict[str, Any]:
    """Synchronise transit access nodes (bus, rail, metro, tram, ferry) using UK NaPTAN dataset."""
    _ensure_db_initialized(app)
    start_time = time.time()

    with db.connection_context():
        SyncMetadata.record_start("stops")

        try:
            client = NaptanClient.from_settings()
            stops_to_upsert = client.fetch_stops()
            if stops_to_upsert:
                Stop.bulk_upsert(stops_to_upsert)

            duration = round(time.time() - start_time, 2)
            count = len(stops_to_upsert)
            SyncMetadata.record_success("stops", count, duration)
            return {
                "table": "stops",
                "status": "success",
                "records": count,
                "message": f"Successfully synchronised {count} UK transit stops from NaPTAN.",
                "duration_seconds": duration,
            }
        except (DataSourceConnectionError, requests.exceptions.RequestException) as exc:
            duration = round(time.time() - start_time, 2)
            err_msg = f"Network or connection error while contacting NaPTAN: {str(exc)}"
            SyncMetadata.record_error("stops", err_msg, duration)
            return {
                "table": "stops",
                "status": "error",
                "records": 0,
                "message": err_msg,
                "duration_seconds": duration,
            }
        except DataSourceError as exc:
            duration = round(time.time() - start_time, 2)
            err_msg = str(exc)
            SyncMetadata.record_error("stops", err_msg, duration)
            return {
                "table": "stops",
                "status": "error",
                "records": 0,
                "message": err_msg,
                "duration_seconds": duration,
            }
        except Exception as exc:
            duration = round(time.time() - start_time, 2)
            err_msg = f"Unexpected error during NaPTAN stop synchronisation: {str(exc)}"
            SyncMetadata.record_error("stops", err_msg, duration)
            return {
                "table": "stops",
                "status": "error",
                "records": 0,
                "message": err_msg,
                "duration_seconds": duration,
            }


def sync_table(
    table_name: str,
    force: bool = False,
    app: Optional[Flask] = None,
) -> Dict[str, Any]:
    """Synchronise a specific transit dataset table."""
    norm_name = table_name.lower().strip()
    if norm_name == "bus_routes":
        return sync_bus_routes(app=app)
    elif norm_name in ("stops", "transit_stops", "naptan"):
        return sync_stops(app=app)
    elif norm_name in ("ha_locations", "locations", "homeassistant"):
        return sync_ha_locations(app=app)
    else:
        return {
            "table": norm_name,
            "status": "error",
            "records": 0,
            "message": (
                f"Unknown or non-syncable table: '{norm_name}'. "
                f"Syncable tables are: {', '.join(SYNCABLE_TABLES)}."
            ),
            "duration_seconds": 0.0,
        }


def sync_all(
    force: bool = False,
    app: Optional[Flask] = None,
) -> Dict[str, Any]:
    """Synchronise all transit dataset tables sequentially."""
    results: Dict[str, Any] = {}
    total_records = 0
    all_success = True

    for tbl in SYNCABLE_TABLES:
        res = sync_table(tbl, force=force, app=app)
        results[tbl] = res
        total_records += res.get("records", 0)
        if res.get("status") == "error":
            all_success = False

    return {
        "success": all_success,
        "tables": results,
        "total_records": total_records,
    }


def check_and_run_background_sync(
    app: Optional[Flask] = None,
    max_age_seconds: int = 86400,
) -> Dict[str, Any]:
    """Check transit tables and trigger synchronisation for any table older than max_age_seconds."""
    _ensure_db_initialized(app)
    triggered: Dict[str, Any] = {}

    with db.connection_context():
        for tbl in SYNCABLE_TABLES:
            if SyncMetadata.is_due_for_update(tbl, max_age_seconds=max_age_seconds):
                res = sync_table(tbl, app=app)
                triggered[tbl] = res

    return {
        "checked": list(SYNCABLE_TABLES),
        "triggered_count": len(triggered),
        "results": triggered,
    }
