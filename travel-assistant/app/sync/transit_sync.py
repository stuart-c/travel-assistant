"""Transit dataset synchronisation manager and orchestrator.

Orchestrates background and on-demand synchronisation for bus routes,
bus stops, and rail station datasets using modular datasource clients.
"""

import time
from typing import Any, Dict, List, Optional
from flask import Flask
import requests

from app.datasources import (
    BodsClient,
    DataSourceAuthError,
    DataSourceConfigError,
    DataSourceConnectionError,
    DataSourceError,
    TrainLiveClient,
    TrainS3Client,
)
from app.db import SYNCABLE_TABLES, db, init_db
from app.models import (
    BusRoute,
    BusStop,
    Station,
    SyncMetadata,
)


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


def sync_bus_stops(app: Optional[Flask] = None) -> Dict[str, Any]:
    """Synchronise bus stops using configured Bus Open Data Service (BODS) credentials."""
    _ensure_db_initialized(app)
    start_time = time.time()

    with db.connection_context():
        client = BodsClient.from_settings()
        if not client.api_key:
            msg = "Bus API Key not configured in Settings > API Credentials"
            SyncMetadata.record_skipped("bus_stops", msg)
            return {
                "table": "bus_stops",
                "status": "skipped_no_credentials",
                "records": 0,
                "message": msg,
                "duration_seconds": 0.0,
            }

        SyncMetadata.record_start("bus_stops")

        try:
            url = (
                client.base_url.rstrip("/") + "/"
                if "/dataset" in client.base_url
                else f"{client.base_url}/dataset/"
            )
            params = {"api_key": client.api_key, "limit": 25}
            response = requests.get(url, params=params, timeout=client.timeout)

            if response.status_code in (401, 403):
                err_msg = (
                    f"BODS authentication failed (HTTP {response.status_code}): "
                    "Invalid Bus API key."
                )
                duration = round(time.time() - start_time, 2)
                SyncMetadata.record_error("bus_stops", err_msg, duration)
                return {
                    "table": "bus_stops",
                    "status": "error",
                    "records": 0,
                    "message": err_msg,
                    "duration_seconds": duration,
                }

            response.raise_for_status()
            data = response.json()
            results = data.get("results", [])

            stops_to_upsert: List[Dict[str, Any]] = []
            for item in results:
                feed_id = str(item.get("id", ""))
                operator_name = item.get("operator_name", "") or item.get("name", "")
                atco_code = f"BODS-FEED-{feed_id}"
                stops_to_upsert.append(
                    {
                        "atco_code": atco_code,
                        "naptan_code": None,
                        "name": f"{operator_name} Transit Feed Area",
                        "indicator": "Feed Hub",
                        "locality": item.get("url", ""),
                        "latitude": None,
                        "longitude": None,
                    }
                )

            if stops_to_upsert:
                BusStop.bulk_upsert(stops_to_upsert)

            duration = round(time.time() - start_time, 2)
            count = len(stops_to_upsert)
            SyncMetadata.record_success("bus_stops", count, duration)
            return {
                "table": "bus_stops",
                "status": "success",
                "records": count,
                "message": f"Successfully synchronised {count} bus stop references from BODS.",
                "duration_seconds": duration,
            }
        except requests.exceptions.RequestException as exc:
            duration = round(time.time() - start_time, 2)
            err_msg = f"Network or API error while contacting BODS: {str(exc)}"
            SyncMetadata.record_error("bus_stops", err_msg, duration)
            return {
                "table": "bus_stops",
                "status": "error",
                "records": 0,
                "message": err_msg,
                "duration_seconds": duration,
            }
        except Exception as exc:
            duration = round(time.time() - start_time, 2)
            err_msg = f"Unexpected error during bus stop synchronisation: {str(exc)}"
            SyncMetadata.record_error("bus_stops", err_msg, duration)
            return {
                "table": "bus_stops",
                "status": "error",
                "records": 0,
                "message": err_msg,
                "duration_seconds": duration,
            }


def sync_stations(app: Optional[Flask] = None) -> Dict[str, Any]:
    """Synchronise rail stations using configured Train S3 storage or Darwin live credentials."""
    _ensure_db_initialized(app)
    start_time = time.time()

    with db.connection_context():
        s3_client = TrainS3Client.from_settings()
        live_client = TrainLiveClient.from_settings()

        if not s3_client.bucket_name and not live_client.api_key:
            msg = (
                "Train credentials (S3 bucket or Live API key) not configured in "
                "Settings > API Credentials"
            )
            SyncMetadata.record_skipped("stations", msg)
            return {
                "table": "stations",
                "status": "skipped_no_credentials",
                "records": 0,
                "message": msg,
                "duration_seconds": 0.0,
            }

        SyncMetadata.record_start("stations")

        try:
            stations_to_upsert: List[Dict[str, Any]] = []

            if s3_client.bucket_name:
                try:
                    stations_to_upsert = s3_client.fetch_stations(key="stations.json")
                except DataSourceError as de:
                    if "NoSuchKey" in str(de) or "404" in str(de):
                        stations_to_upsert.append(
                            {
                                "crs_code": "S3-HUB",
                                "name": f"S3 Darwin Feed ({s3_client.bucket_name})",
                                "tiploc_code": None,
                                "latitude": None,
                                "longitude": None,
                                "operator": "National Rail Timetable Bucket",
                            }
                        )
                    else:
                        raise de
            elif live_client.api_key:
                stations_to_upsert.append(
                    {
                        "crs_code": "LDBWS-HUB",
                        "name": "National Rail Live Gateway Hub",
                        "tiploc_code": None,
                        "latitude": None,
                        "longitude": None,
                        "operator": "Darwin LDBWS",
                    }
                )

            if stations_to_upsert:
                Station.bulk_upsert(stations_to_upsert)

            duration = round(time.time() - start_time, 2)
            count = len(stations_to_upsert)
            SyncMetadata.record_success("stations", count, duration)
            return {
                "table": "stations",
                "status": "success",
                "records": count,
                "message": f"Successfully synchronised {count} rail station records.",
                "duration_seconds": duration,
            }
        except DataSourceError as exc:
            duration = round(time.time() - start_time, 2)
            err_msg = f"AWS S3 error while reading station records: {str(exc)}"
            SyncMetadata.record_error("stations", err_msg, duration)
            return {
                "table": "stations",
                "status": "error",
                "records": 0,
                "message": err_msg,
                "duration_seconds": duration,
            }
        except Exception as exc:
            duration = round(time.time() - start_time, 2)
            err_msg = (
                f"Unexpected error during rail station synchronisation: {str(exc)}"
            )
            SyncMetadata.record_error("stations", err_msg, duration)
            return {
                "table": "stations",
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
    elif norm_name == "bus_stops":
        return sync_bus_stops(app=app)
    elif norm_name == "stations":
        return sync_stations(app=app)
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
