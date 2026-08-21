"""Transit dataset synchronisation manager and orchestrator.

Orchestrates background and on-demand synchronisation for bus routes,
bus stops, and rail station datasets using modular datasource clients.
"""

import logging
from typing import Any, Dict, Optional, Set
from flask import Flask

from app.datasources import (
    BodsClient,
    NaptanClient,
    RailReferencesClient,
    TrainS3Client,
)
from app.db import db
from app.models import (
    BusRoute,
    Journey,
    RailReference,
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
        target_naptan_codes: Set[str] = set()
        target_atco_codes: Set[str] = set()
        target_generic_codes: Set[str] = set()

        def _add_candidate(stop_id: Optional[str], stop_type: Optional[str]) -> None:
            if not stop_id:
                return
            s_id = str(stop_id).strip()
            if s_id.startswith("naptan:"):
                code = s_id.split(":", 1)[1].strip()
                if code:
                    target_naptan_codes.add(code)
            elif s_id.startswith("atco:"):
                code = s_id.split(":", 1)[1].strip()
                if code:
                    target_atco_codes.add(code)
            elif stop_type == "bus" or s_id.startswith("bus:"):
                code = s_id.split(":", 1)[1].strip() if ":" in s_id else s_id
                if code:
                    target_generic_codes.add(code)

        # From Walking table
        for w in Walking.select():
            _add_candidate(w.start_id, w.start_type)
            _add_candidate(w.finish_id, w.finish_type)

        # From Journey table
        for j in Journey.select():
            _add_candidate(j.from_id, j.from_type)
            _add_candidate(j.to_id, j.to_type)

        if not (target_naptan_codes or target_atco_codes or target_generic_codes):
            return 0

        # 2. Build stop lookup dictionary, target ATCO codes, and admin areas
        # from cached bus stops
        stop_lookup: Dict[str, Dict[str, Any]] = {}
        admin_areas: Set[str] = set()
        resolved_atco_codes: Set[str] = set()

        upper_naptan = {c.upper() for c in target_naptan_codes}
        upper_atco = {c.upper() for c in target_atco_codes}
        upper_generic = {c.upper() for c in target_generic_codes}

        # Direct ATCO codes requested are added to target ATCO set
        for c in target_atco_codes:
            c_clean = c.upper().strip()
            resolved_atco_codes.add(c_clean)
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
            atco_clean = stp.atco_code.upper().strip() if stp.atco_code else ""
            naptan_clean = stp.naptan_code.upper().strip() if stp.naptan_code else ""
            name_clean = stp.name.upper().strip() if stp.name else ""

            if atco_clean:
                stop_lookup[atco_clean] = meta
            if naptan_clean:
                stop_lookup[naptan_clean] = meta
            if name_clean:
                stop_lookup[name_clean] = meta

            is_target = (
                (naptan_clean and naptan_clean in upper_naptan)
                or (atco_clean and atco_clean in upper_atco)
                or (naptan_clean and naptan_clean in upper_generic)
                or (atco_clean and atco_clean in upper_generic)
                or (name_clean and name_clean in upper_generic)
            )
            if is_target:
                if atco_clean:
                    resolved_atco_codes.add(atco_clean)
                    if len(atco_clean) >= 3 and atco_clean[:3].isdigit():
                        admin_areas.add(atco_clean[:3])
                if naptan_clean:
                    resolved_atco_codes.add(naptan_clean)

        # 3. Fetch matching timetables from BODS
        parsed_timetables = client.fetch_timetables(
            target_stop_codes=resolved_atco_codes if resolved_atco_codes else None,
            admin_areas=sorted(list(admin_areas)) if admin_areas else None,
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


def sync_rail_references(app: Optional[Flask] = None) -> Dict[str, Any]:
    """Synchronise TIPLOC/ATCO/CRS rail reference mappings from NaPTAN RailReferences.csv.

    Performs a full replace of the ``rail_references`` table on each run: all
    existing rows are deleted and the latest dataset is inserted atomically.
    This ensures stale entries from previous syncs are never retained.
    """

    def _perform_sync() -> int:
        client = RailReferencesClient.from_settings()
        refs = client.fetch_rail_references()
        return RailReference.bulk_replace(refs)

    return run_sync_task(
        table_name="rail_references",
        sync_operation=_perform_sync,
        connection_error_template=(
            "Network or connection error while fetching rail references from NaPTAN: {error}"
        ),
        success_message_factory=lambda cnt: (
            f"Successfully synchronised {cnt} rail reference mappings from NaPTAN."
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
    elif norm_name == "rail_references":
        return sync_rail_references(app=app)
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
