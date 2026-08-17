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
    TrainS3Client,
)
from app.db import SYNCABLE_TABLES, db, init_db
from app.models import (
    BusRoute,
    Stop,
    SyncMetadata,
    Timetable,
)
from app.sync.ha_sync import sync_ha_locations
from app.sync.walking_sync import sync_walking_routes


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


def sync_train_timetables(app: Optional[Flask] = None) -> Dict[str, Any]:
    """Synchronise train timetables from AWS S3 Darwin XML snapshots."""
    _ensure_db_initialized(app)
    start_time = time.time()

    with db.connection_context():
        client = TrainS3Client.from_settings()
        if not client.bucket_name:
            msg = "Train S3 Bucket not configured in Settings > API Credentials"
            SyncMetadata.record_skipped("train_timetables", msg)
            return {
                "table": "train_timetables",
                "status": "skipped_no_credentials",
                "records": 0,
                "message": msg,
                "duration_seconds": 0.0,
            }

        SyncMetadata.record_start("train_timetables")

        try:
            # Build stop lookup dictionary from cached rail stops
            stop_lookup: Dict[str, Dict[str, Any]] = {}
            for stp in Stop.select().where(Stop.stop_type == "rail"):
                meta = {
                    "id": stp.naptan_code or stp.atco_code,
                    "name": stp.name,
                    "type": "rail",
                    "indicator": stp.indicator or "Station",
                    "icon": "train",
                    "latitude": stp.latitude,
                    "longitude": stp.longitude,
                }
                if stp.naptan_code:
                    stop_lookup[stp.naptan_code.upper().strip()] = meta
                if stp.atco_code:
                    stop_lookup[stp.atco_code.upper().strip()] = meta
                if stp.name:
                    stop_lookup[stp.name.upper().strip()] = meta

            parsed_timetables = client.fetch_timetables(stop_lookup=stop_lookup)
            count = len(parsed_timetables)

            with db.atomic():
                # Reconcile auto_added train timetables while preserving custom timetables
                Timetable.delete().where(
                    Timetable.auto_added == True  # noqa: E712
                ).execute()
                if parsed_timetables:
                    Timetable.insert_many(parsed_timetables).execute()

            duration = round(time.time() - start_time, 2)
            SyncMetadata.record_success("train_timetables", count, duration)
            return {
                "table": "train_timetables",
                "status": "success",
                "records": count,
                "message": (
                    f"Successfully synchronised {count} train route timetable(s) from Darwin S3."
                ),
                "duration_seconds": duration,
            }
        except (DataSourceAuthError, DataSourceConfigError) as exc:
            duration = round(time.time() - start_time, 2)
            err_msg = str(exc)
            SyncMetadata.record_error("train_timetables", err_msg, duration)
            return {
                "table": "train_timetables",
                "status": "error",
                "records": 0,
                "message": err_msg,
                "duration_seconds": duration,
            }
        except DataSourceConnectionError as exc:
            duration = round(time.time() - start_time, 2)
            err_msg = f"Network or API error while contacting AWS S3: {str(exc)}"
            SyncMetadata.record_error("train_timetables", err_msg, duration)
            return {
                "table": "train_timetables",
                "status": "error",
                "records": 0,
                "message": err_msg,
                "duration_seconds": duration,
            }
        except DataSourceError as exc:
            duration = round(time.time() - start_time, 2)
            err_msg = str(exc)
            SyncMetadata.record_error("train_timetables", err_msg, duration)
            return {
                "table": "train_timetables",
                "status": "error",
                "records": 0,
                "message": err_msg,
                "duration_seconds": duration,
            }
        except Exception as exc:
            duration = round(time.time() - start_time, 2)
            err_msg = (
                f"Unexpected error during train timetable synchronisation: {str(exc)}"
            )
            SyncMetadata.record_error("train_timetables", err_msg, duration)
            return {
                "table": "train_timetables",
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
    elif norm_name == "train_timetables":
        return sync_train_timetables(app=app)
    elif norm_name in ("walking", "walking_routes"):
        return sync_walking_routes(app=app, force=force)
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
