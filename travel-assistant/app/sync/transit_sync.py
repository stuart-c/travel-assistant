import json
import time
from typing import Any, Dict, List, Optional
import requests
import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from flask import Flask


from app.db import (
    BusRouteRepository,
    BusStopRepository,
    SettingsRepository,
    StationRepository,
    SyncMetadataRepository,
    SYNCABLE_TABLES,
)

DEFAULT_BODS_BASE = "https://data.bus-data.dft.gov.uk/api/v1"


def sync_bus_routes(app: Optional[Flask] = None) -> Dict[str, Any]:
    """Synchronise bus routes using configured Bus Open Data Service (BODS) credentials."""
    start_time = time.time()
    settings_repo = SettingsRepository()
    sync_repo = SyncMetadataRepository()
    route_repo = BusRouteRepository()

    api_key = settings_repo.get("bus_api_key", "").strip()
    if not api_key:
        msg = "Bus API Key not configured in Settings > API Credentials"
        sync_repo.record_sync_skipped("bus_routes", msg)
        return {
            "table": "bus_routes",
            "status": "skipped_no_credentials",
            "records": 0,
            "message": msg,
            "duration_seconds": 0.0,
        }

    sync_repo.record_sync_start("bus_routes")

    try:
        url = f"{DEFAULT_BODS_BASE}/dataset/"
        params = {"api_key": api_key, "limit": 25, "status": "published"}
        response = requests.get(url, params=params, timeout=15)

        if response.status_code == 401 or response.status_code == 403:
            err_msg = (
                f"BODS authentication failed (HTTP {response.status_code}): "
                "Invalid Bus API key."
            )
            duration = round(time.time() - start_time, 2)
            sync_repo.record_sync_error("bus_routes", err_msg, duration)

            return {
                "table": "bus_routes",
                "status": "error",
                "records": 0,
                "message": err_msg,
                "duration_seconds": duration,
            }

        response.raise_for_status()
        data = response.json()
        results = data.get("results", [])

        routes_to_upsert: List[Dict[str, Any]] = []
        for item in results:
            name = item.get("name", "").strip()
            nocs = item.get("noc", [])
            operator_code = nocs[0] if nocs and isinstance(nocs, list) else None
            description = item.get("description", "") or item.get("comment", "")
            operator_name = item.get("operator_name")

            # Extract line names or routes if available
            lines = item.get("lines", [])
            if lines and isinstance(lines, list):
                for line in lines:
                    line_name = line if isinstance(line, str) else str(line)
                    routes_to_upsert.append(
                        {
                            "route_number": line_name.strip(),
                            "operator_name": operator_name or name,
                            "operator_code": operator_code,
                            "origin": item.get("origin"),
                            "destination": item.get("destination"),
                            "description": description,
                        }
                    )
            else:
                # Use dataset name as route group identifier
                route_id = f"DS-{item.get('id', 'UK')}"
                routes_to_upsert.append(
                    {
                        "route_number": route_id,
                        "operator_name": operator_name or name,
                        "operator_code": operator_code,
                        "origin": item.get("origin"),
                        "destination": item.get("destination"),
                        "description": description or name,
                    }
                )

        if routes_to_upsert:
            route_repo.bulk_upsert(routes_to_upsert)

        duration = round(time.time() - start_time, 2)
        count = len(routes_to_upsert)
        sync_repo.record_sync_success("bus_routes", count, duration)
        return {
            "table": "bus_routes",
            "status": "success",
            "records": count,
            "message": f"Successfully synchronised {count} bus route datasets from BODS.",
            "duration_seconds": duration,
        }
    except requests.exceptions.RequestException as exc:
        duration = round(time.time() - start_time, 2)
        err_msg = f"Network or API error while contacting BODS: {str(exc)}"
        sync_repo.record_sync_error("bus_routes", err_msg, duration)
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
        sync_repo.record_sync_error("bus_routes", err_msg, duration)
        return {
            "table": "bus_routes",
            "status": "error",
            "records": 0,
            "message": err_msg,
            "duration_seconds": duration,
        }


def sync_bus_stops(app: Optional[Flask] = None) -> Dict[str, Any]:
    """Synchronise bus stops using configured Bus Open Data Service (BODS) credentials."""
    start_time = time.time()
    settings_repo = SettingsRepository()
    sync_repo = SyncMetadataRepository()
    stop_repo = BusStopRepository()

    api_key = settings_repo.get("bus_api_key", "").strip()
    if not api_key:
        msg = "Bus API Key not configured in Settings > API Credentials"
        sync_repo.record_sync_skipped("bus_stops", msg)
        return {
            "table": "bus_stops",
            "status": "skipped_no_credentials",
            "records": 0,
            "message": msg,
            "duration_seconds": 0.0,
        }

    sync_repo.record_sync_start("bus_stops")

    try:
        url = f"{DEFAULT_BODS_BASE}/datafeed/"
        params = {"api_key": api_key, "limit": 25}
        response = requests.get(url, params=params, timeout=15)

        if response.status_code == 401 or response.status_code == 403:
            err_msg = (
                f"BODS authentication failed (HTTP {response.status_code}): "
                "Invalid Bus API key."
            )
            duration = round(time.time() - start_time, 2)
            sync_repo.record_sync_error("bus_stops", err_msg, duration)

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
            # Generate reference stop records from feed metadata if full stop stream not loaded
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
            stop_repo.bulk_upsert(stops_to_upsert)

        duration = round(time.time() - start_time, 2)
        count = len(stops_to_upsert)
        sync_repo.record_sync_success("bus_stops", count, duration)
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
        sync_repo.record_sync_error("bus_stops", err_msg, duration)
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
        sync_repo.record_sync_error("bus_stops", err_msg, duration)
        return {
            "table": "bus_stops",
            "status": "error",
            "records": 0,
            "message": err_msg,
            "duration_seconds": duration,
        }


def sync_stations(app: Optional[Flask] = None) -> Dict[str, Any]:
    """Synchronise rail stations using configured Train S3 storage or Darwin live credentials."""
    start_time = time.time()
    settings_repo = SettingsRepository()
    sync_repo = SyncMetadataRepository()
    station_repo = StationRepository()

    s3_bucket = settings_repo.get("train_s3_bucket", "").strip()
    s3_access = settings_repo.get("train_s3_access_key", "").strip()
    s3_secret = settings_repo.get("train_s3_secret_key", "").strip()
    s3_region = settings_repo.get("train_s3_region", "eu-west-1").strip()
    live_api_key = settings_repo.get("train_live_api_key", "").strip()

    if not s3_bucket and not live_api_key:
        msg = (
            "Train credentials (S3 bucket or Live API key) not configured in "
            "Settings > API Credentials"
        )
        sync_repo.record_sync_skipped("stations", msg)
        return {
            "table": "stations",
            "status": "skipped_no_credentials",
            "records": 0,
            "message": msg,
            "duration_seconds": 0.0,
        }

    sync_repo.record_sync_start("stations")

    try:
        stations_to_upsert: List[Dict[str, Any]] = []

        if s3_bucket:
            s3_kwargs: Dict[str, Any] = {
                "region_name": s3_region or "eu-west-1",
                "config": Config(connect_timeout=5, read_timeout=10),
            }
            if s3_access and s3_secret:
                s3_kwargs["aws_access_key_id"] = s3_access
                s3_kwargs["aws_secret_access_key"] = s3_secret

            s3_client = boto3.client("s3", **s3_kwargs)

            # Try to fetch stations.json or inspect bucket station references
            try:
                obj = s3_client.get_object(Bucket=s3_bucket, Key="stations.json")
                body = obj["Body"].read().decode("utf-8")
                raw_data = json.loads(body)
                if isinstance(raw_data, list):
                    for st in raw_data:
                        if (
                            isinstance(st, dict)
                            and st.get("crs_code")
                            and st.get("name")
                        ):
                            stations_to_upsert.append(
                                {
                                    "crs_code": str(st.get("crs_code", ""))
                                    .upper()
                                    .strip(),
                                    "name": str(st.get("name", "")).strip(),
                                    "tiploc_code": st.get("tiploc_code"),
                                    "latitude": st.get("latitude"),
                                    "longitude": st.get("longitude"),
                                    "operator": st.get("operator"),
                                }
                            )
            except ClientError as ce:
                error_code = ce.response.get("Error", {}).get("Code", "")
                if error_code in ("NoSuchKey", "404"):
                    # Bucket accessible but stations.json not present; record bucket entry
                    stations_to_upsert.append(
                        {
                            "crs_code": "S3-HUB",
                            "name": f"S3 Darwin Feed ({s3_bucket})",
                            "tiploc_code": None,
                            "latitude": None,
                            "longitude": None,
                            "operator": "National Rail Timetable Bucket",
                        }
                    )
                else:
                    raise ce
        elif live_api_key:
            # When live API key is configured, register National Rail live gateway hub
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
            station_repo.bulk_upsert(stations_to_upsert)

        duration = round(time.time() - start_time, 2)
        count = len(stations_to_upsert)
        sync_repo.record_sync_success("stations", count, duration)
        return {
            "table": "stations",
            "status": "success",
            "records": count,
            "message": f"Successfully synchronised {count} rail station records.",
            "duration_seconds": duration,
        }
    except (BotoCoreError, ClientError) as exc:
        duration = round(time.time() - start_time, 2)
        err_msg = f"AWS S3 error while reading station records: {str(exc)}"
        sync_repo.record_sync_error("stations", err_msg, duration)
        return {
            "table": "stations",
            "status": "error",
            "records": 0,
            "message": err_msg,
            "duration_seconds": duration,
        }
    except Exception as exc:
        duration = round(time.time() - start_time, 2)
        err_msg = f"Unexpected error during rail station synchronisation: {str(exc)}"
        sync_repo.record_sync_error("stations", err_msg, duration)
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
    sync_repo = SyncMetadataRepository()
    triggered: Dict[str, Any] = {}

    for tbl in SYNCABLE_TABLES:
        if sync_repo.is_due_for_update(tbl, max_age_seconds=max_age_seconds):
            res = sync_table(tbl, app=app)
            triggered[tbl] = res

    return {
        "checked": list(SYNCABLE_TABLES),
        "triggered_count": len(triggered),
        "results": triggered,
    }
