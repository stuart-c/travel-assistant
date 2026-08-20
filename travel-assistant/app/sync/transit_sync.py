"""Transit dataset synchronisation manager and orchestrator.

Orchestrates background and on-demand synchronisation for bus routes,
bus stops, and rail station datasets using modular datasource clients.
"""

import logging
from typing import Any, Dict, List, Optional, Set
from flask import Flask

from app.datasources import (
    BodsClient,
    NaptanClient,
    TrainS3Client,
)
from app.db import db
from app.models import (
    BusRoute,
    Journey,
    Stop,
    Timetable,
    Walking,
)
from app.sync.common import run_sync_task

logger = logging.getLogger(__name__)


def sync_bus_routes(app: Optional[Flask] = None) -> Dict[str, Any]:
    """Synchronise bus routes using configured Bus Open Data Service (BODS) credentials."""
    client = BodsClient.from_settings()

    def _check_credentials() -> Optional[str]:
        if not client.api_key:
            return "Bus API Key not configured in Settings > API Credentials"
        return None

    def _perform_sync() -> int:
        routes_to_upsert = client.fetch_routes(limit=25)
        if routes_to_upsert:
            BusRoute.bulk_upsert(routes_to_upsert)
        return len(routes_to_upsert)

    return run_sync_task(
        table_name="bus_routes",
        sync_operation=_perform_sync,
        client_check=_check_credentials,
        provider_name="BODS",
        success_message_factory=lambda cnt: (
            f"Successfully synchronised {cnt} bus route datasets from BODS."
        ),
        app=app,
    )


def sync_stops(app: Optional[Flask] = None) -> Dict[str, Any]:
    """Synchronise transit access nodes (bus, rail, metro, tram, ferry) using UK NaPTAN dataset."""

    def _perform_sync() -> int:
        client = NaptanClient.from_settings()
        stops_to_upsert = client.fetch_stops()
        if stops_to_upsert:
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


def sync_train_timetables(app: Optional[Flask] = None) -> Dict[str, Any]:
    """Synchronise train timetables from AWS S3 Darwin XML snapshots."""
    client = TrainS3Client.from_settings()

    def _check_credentials() -> Optional[str]:
        if not client.bucket_name:
            return "Train S3 Bucket not configured in Settings > API Credentials"
        return None

    def _perform_sync() -> int:
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
            # Reconcile auto_added train timetables while preserving custom and bus timetables
            Timetable.delete().where(
                (Timetable.auto_added == True)  # noqa: E712
                & (Timetable.transport_type == "rail")
            ).execute()
            if parsed_timetables:
                Timetable.insert_many(parsed_timetables).execute()

        return count

    return run_sync_task(
        table_name="train_timetables",
        sync_operation=_perform_sync,
        client_check=_check_credentials,
        provider_name="AWS S3",
        success_message_factory=lambda cnt: (
            f"Successfully synchronised {cnt} train route timetable(s) from Darwin S3."
        ),
        app=app,
    )


def sync_bus_timetables(app: Optional[Flask] = None) -> Dict[str, Any]:
    """Synchronise bus timetables for routes covering stops in walking or journey tables."""
    client = BodsClient.from_settings()

    def _check_credentials() -> Optional[str]:
        if not client.api_key:
            return "Bus API Key not configured in Settings > API Credentials"
        return None

    def _perform_sync() -> int:
        # 1. Collect all bus stop IDs/codes referenced in Walking and Journey tables
        target_stop_codes: Set[str] = set()

        # From Walking table
        for w in Walking.select():
            if w.start_type == "bus" or (
                w.start_id
                and (w.start_id.startswith("naptan:") or w.start_id.startswith("atco:"))
            ):
                raw_id = (
                    w.start_id.split(":", 1)[1] if ":" in w.start_id else w.start_id
                )
                if raw_id:
                    target_stop_codes.add(raw_id.strip())
            if w.finish_type == "bus" or (
                w.finish_id
                and (
                    w.finish_id.startswith("naptan:") or w.finish_id.startswith("atco:")
                )
            ):
                raw_id = (
                    w.finish_id.split(":", 1)[1] if ":" in w.finish_id else w.finish_id
                )
                if raw_id:
                    target_stop_codes.add(raw_id.strip())

        # From Journey table
        for j in Journey.select():
            if j.from_type == "bus" or (
                j.from_id
                and (j.from_id.startswith("naptan:") or j.from_id.startswith("atco:"))
            ):
                raw_id = j.from_id.split(":", 1)[1] if ":" in j.from_id else j.from_id
                if raw_id:
                    target_stop_codes.add(raw_id.strip())
            if j.to_type == "bus" or (
                j.to_id
                and (j.to_id.startswith("naptan:") or j.to_id.startswith("atco:"))
            ):
                raw_id = j.to_id.split(":", 1)[1] if ":" in j.to_id else j.to_id
                if raw_id:
                    target_stop_codes.add(raw_id.strip())

        if not target_stop_codes:
            return 0

        # 2. Build stop lookup dictionary, admin areas, and bounding box from cached bus stops
        stop_lookup: Dict[str, Dict[str, Any]] = {}
        admin_areas: Set[str] = set()
        lats: List[float] = []
        lons: List[float] = []
        target_upper = {c.upper() for c in target_stop_codes}

        for c in target_stop_codes:
            c_clean = c.upper().strip()
            if len(c_clean) >= 3 and c_clean[:3].isdigit():
                admin_areas.add(c_clean[:3])

        for stp in Stop.select().where(Stop.stop_type == "bus"):
            meta = {
                "id": stp.atco_code or stp.naptan_code,
                "name": stp.name,
                "type": "bus",
                "indicator": stp.indicator or "Bus Stop",
                "icon": "directions_bus",
                "latitude": stp.latitude,
                "longitude": stp.longitude,
            }
            if stp.atco_code:
                code_clean = stp.atco_code.upper().strip()
                stop_lookup[code_clean] = meta
            if stp.naptan_code:
                stop_lookup[stp.naptan_code.upper().strip()] = meta
            if stp.name:
                stop_lookup[stp.name.upper().strip()] = meta

            is_target = (
                (stp.atco_code and stp.atco_code.upper().strip() in target_upper)
                or (stp.naptan_code and stp.naptan_code.upper().strip() in target_upper)
                or (stp.name and stp.name.upper().strip() in target_upper)
            )
            if is_target:
                if stp.atco_code:
                    code_clean = stp.atco_code.upper().strip()
                    if len(code_clean) >= 3 and code_clean[:3].isdigit():
                        admin_areas.add(code_clean[:3])
                if stp.latitude is not None and stp.longitude is not None:
                    try:
                        lats.append(float(stp.latitude))
                        lons.append(float(stp.longitude))
                    except (ValueError, TypeError):
                        pass

        bounding_box = None
        if lats and lons:
            bounding_box = (
                round(min(lons) - 0.05, 4),
                round(min(lats) - 0.05, 4),
                round(max(lons) + 0.05, 4),
                round(max(lats) + 0.05, 4),
            )

        # 3. Fetch matching timetables from BODS
        parsed_timetables = client.fetch_timetables(
            target_stop_codes=target_stop_codes,
            admin_areas=sorted(list(admin_areas)) if admin_areas else None,
            bounding_box=bounding_box,
            stop_lookup=stop_lookup,
        )
        count = len(parsed_timetables)

        with db.atomic():
            # Reconcile auto_added bus timetables while preserving
            # custom timetables and rail timetables
            Timetable.delete().where(
                (Timetable.auto_added == True)  # noqa: E712
                & (Timetable.transport_type == "bus")
            ).execute()
            if parsed_timetables:
                Timetable.insert_many(parsed_timetables).execute()

        return count

    return run_sync_task(
        table_name="bus_timetables",
        sync_operation=_perform_sync,
        client_check=_check_credentials,
        provider_name="BODS",
        success_message_factory=lambda cnt: (
            f"Successfully synchronised {cnt} bus route timetable(s) from BODS."
            if cnt > 0
            else "No bus stops found in walking or journey tables for timetable discovery."
        ),
        app=app,
    )


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

    if norm_name == "bus_routes":
        return sync_bus_routes(app=app)
    elif norm_name in ("stops", "transit_stops", "naptan"):
        return sync_stops(app=app)
    elif norm_name in ("ha_locations", "locations", "homeassistant"):
        return sync_ha_locations(app=app)
    elif norm_name == "train_timetables":
        return sync_train_timetables(app=app)
    elif norm_name in ("bus_timetables", "bus_timetable"):
        return sync_bus_timetables(app=app)
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
