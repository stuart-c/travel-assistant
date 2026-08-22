"""Transit dataset synchronisation manager and orchestrator.

Orchestrates background and on-demand synchronisation for bus routes,
bus stops, and rail station datasets using modular datasource clients.
"""

import logging
import math
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
    StopInterchange,
    Timetable,
    Walking,
)
from app.sync.common import run_sync_task

logger = logging.getLogger(__name__)

DEFAULT_INTERCHANGE_RADIUS_METRES = 250.0
WALKING_METRES_PER_MINUTE = 80.0


def sync_bus_routes(app: Optional[Flask] = None) -> Dict[str, Any]:
    """Synchronise bus routes using configured Bus Open Data Service (BODS) credentials."""
    client = BodsClient.from_settings()

    def _check_credentials() -> Optional[str]:
        if not client.api_key:
            return "Bus API Key not configured in Settings > API Credentials"
        return None

    def _perform_sync() -> int:
        logger.info("Fetching bus routes from Bus Open Data Service (BODS)...")
        routes_to_upsert = client.fetch_routes(limit=25)
        if routes_to_upsert:
            logger.info(
                "Upserting %d bus route records into database...", len(routes_to_upsert)
            )
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
        logger.info("Fetching UK public transport stops from NaPTAN dataset...")
        client = NaptanClient.from_settings()
        stops_to_upsert = client.fetch_stops()
        if stops_to_upsert:
            logger.info(
                "Upserting %d transit stop records into database...",
                len(stops_to_upsert),
            )
            Stop.bulk_upsert(stops_to_upsert)
            try:
                from app.sync.worker import request_sync

                logger.info(
                    "Triggering automatic stop interchanges discovery following stops update..."
                )
                request_sync("stop_interchanges")
            except Exception as sync_exc:
                logger.warning(
                    "Failed to queue stop_interchanges sync after stops sync: %s",
                    sync_exc,
                )
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
        logger.info(
            "Connecting to AWS S3 bucket '%s' for Darwin timetable snapshots...",
            client.bucket_name,
        )
        # Build stop lookup dictionary from cached rail stops
        stop_lookup: Dict[str, Dict[str, Any]] = {}
        for stp in Stop.select().where(Stop.stop_type == "rail"):
            canonical_id = (
                f"naptan:{stp.naptan_code}"
                if stp.naptan_code
                else f"atco:{stp.atco_code}"
            )
            meta = {
                "id": canonical_id,
                "name": stp.name,
                "type": "rail",
                "indicator": stp.indicator or "Station",
                "icon": "train",
                "latitude": stp.latitude,
                "longitude": stp.longitude,
            }
            if stp.atco_code:
                atco_clean = stp.atco_code.upper().strip()
                stop_lookup[atco_clean] = meta
                if atco_clean.startswith("9100"):
                    # Index by bare TIPLOC (e.g. 9100STEVNGE -> STEVNGE)
                    stop_lookup[atco_clean[4:]] = meta
            if stp.naptan_code:
                stop_lookup[stp.naptan_code.upper().strip()] = meta
            if stp.name:
                stop_lookup[stp.name.upper().strip()] = meta

        parsed_timetables = client.fetch_timetables(stop_lookup=stop_lookup)
        count = len(parsed_timetables)
        logger.info(
            "Reconciling %d Darwin train route timetable(s) in database...", count
        )

        with db.atomic():
            # Reconcile auto_added train timetables while preserving custom and bus timetables
            Timetable.delete().where(
                (Timetable.auto_added == True)  # noqa: E712
                & (Timetable.transport_type == "rail")
            ).execute()
            if parsed_timetables:
                Timetable.insert_many(parsed_timetables).execute()

        return count

    result = run_sync_task(
        table_name="train_timetables",
        sync_operation=_perform_sync,
        client_check=_check_credentials,
        provider_name="AWS S3",
        success_message_factory=lambda cnt: (
            f"Successfully synchronised {cnt} train route timetable(s) from Darwin S3."
        ),
        app=app,
    )

    if result.get("status") == "success":
        try:
            from app.sync.worker import request_sync

            logger.info(
                "Triggering automatic journey routes calculation following train timetables update..."
            )
            request_sync("journey_routes")
        except Exception as sync_exc:
            logger.warning(
                "Failed to queue journey routes sync after train timetables: %s",
                sync_exc,
            )

    return result


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
                "id": (
                    f"naptan:{stp.naptan_code}"
                    if stp.naptan_code
                    else f"atco:{stp.atco_code}"
                ),
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
        logger.info(
            "Found %d target bus stops across %d admin area(s) (%s). Fetching TransXChange datasets from BODS...",
            len(resolved_atco_codes),
            len(admin_areas),
            ", ".join(sorted(admin_areas)) if admin_areas else "none",
        )
        parsed_timetables = client.fetch_timetables(
            target_stop_codes=resolved_atco_codes if resolved_atco_codes else None,
            admin_areas=sorted(list(admin_areas)) if admin_areas else None,
            stop_lookup=stop_lookup,
        )
        count = len(parsed_timetables)
        logger.info(
            "Reconciling %d bus route timetable(s) from BODS TransXChange XML in database...",
            count,
        )

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

    result = run_sync_task(
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

    if result.get("status") == "success":
        try:
            from app.sync.worker import request_sync

            logger.info(
                "Triggering automatic journey routes calculation following bus timetables update..."
            )
            request_sync("journey_routes")
        except Exception as sync_exc:
            logger.warning(
                "Failed to queue journey routes sync after bus timetables: %s",
                sync_exc,
            )

    return result


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


def find_nearby_stop_interchanges(
    radius_metres: float = DEFAULT_INTERCHANGE_RADIUS_METRES,
    database: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Query nearby transit stop interchanges within radius_metres using SQLite R*Tree.

    Performs a spatial bounding-box join against stops_rtree using British National Grid
    easting and northing coordinates, followed by exact Euclidean distance filtering
    and walking duration estimation.
    """
    db_conn = database or db.obj
    populate_stops_rtree(database=db_conn)

    query = """
        SELECT
            s1.atco_code AS from_stop_atco,
            s1.name AS from_stop_name,
            s1.stop_type AS from_stop_type,
            s2.atco_code AS to_stop_atco,
            s2.name AS to_stop_name,
            s2.stop_type AS to_stop_type,
            s1.easting AS s1_east,
            s1.northing AS s1_north,
            s2.easting AS s2_east,
            s2.northing AS s2_north
        FROM "stops" s1
        JOIN "stops_rtree" r ON (
            r.min_easting <= s1.easting + :radius
            AND r.max_easting >= s1.easting - :radius
            AND r.min_northing <= s1.northing + :radius
            AND r.max_northing >= s1.northing - :radius
        )
        JOIN "stops" s2 ON s2.id = r.id
        WHERE s1.id != s2.id
          AND s1.easting IS NOT NULL
          AND s1.northing IS NOT NULL
    """

    interchanges: List[Dict[str, Any]] = []
    with db_conn.connection_context():
        cursor = db_conn.execute_sql(query, {"radius": float(radius_metres)})
        rows = cursor.fetchall()
        for row in rows:
            (
                from_atco,
                from_name,
                from_type,
                to_atco,
                to_name,
                to_type,
                s1_e,
                s1_n,
                s2_e,
                s2_n,
            ) = row
            dx = float(s2_e - s1_e)
            dy = float(s2_n - s1_n)
            distance_m = math.hypot(dx, dy)
            if distance_m <= radius_metres:
                dist_int = int(round(distance_m))
                walk_min = max(1, math.ceil(distance_m / WALKING_METRES_PER_MINUTE))
                interchanges.append(
                    {
                        "from_stop_atco": from_atco,
                        "from_stop_name": from_name,
                        "from_stop_type": from_type or "bus",
                        "to_stop_atco": to_atco,
                        "to_stop_name": to_name,
                        "to_stop_type": to_type or "bus",
                        "distance_metres": dist_int,
                        "estimated_walk_minutes": walk_min,
                    }
                )

    return interchanges


def sync_stop_interchanges(
    app: Optional[Flask] = None,
    radius_metres: float = DEFAULT_INTERCHANGE_RADIUS_METRES,
) -> Dict[str, Any]:
    """Discover nearby stop interchanges using NaPTAN easting/northing coordinates and SQLite R*Tree."""

    def _perform_sync() -> int:
        logger.info(
            "Calculating nearby transit stop interchanges within %.0fm radius using spatial index...",
            radius_metres,
        )
        interchanges = find_nearby_stop_interchanges(radius_metres=radius_metres)
        logger.info(
            "Persisting %d discovered transit stop interchange connections...",
            len(interchanges),
        )
        return StopInterchange.bulk_replace(interchanges)

    return run_sync_task(
        table_name="stop_interchanges",
        sync_operation=_perform_sync,
        success_message_factory=lambda cnt: (
            f"Successfully synchronised {cnt} nearby stop interchange pairs."
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
    from app.sync.journey_sync import sync_journey_routes
    from app.sync.walking_sync import sync_walking_routes
    from app.sync.worker import SYNC_REGISTRY

    norm_name = table_name.lower().strip()
    valid_names = [e.table_name for e in SYNC_REGISTRY]

    if norm_name == "bus_routes":
        return sync_bus_routes(app=app)
    elif norm_name in ("stops", "transit_stops", "naptan"):
        return sync_stops(app=app)
    elif norm_name in ("stop_interchanges", "interchanges", "stop_interchange"):
        return sync_stop_interchanges(app=app)
    elif norm_name in ("ha_locations", "locations", "homeassistant"):
        return sync_ha_locations(app=app)
    elif norm_name == "train_timetables":
        return sync_train_timetables(app=app)
    elif norm_name in ("bus_timetables", "bus_timetable"):
        return sync_bus_timetables(app=app)
    elif norm_name in ("walking", "walking_routes"):
        return sync_walking_routes(app=app, force=force)
    elif norm_name in ("journey_routes", "journeys", "calculated_routes"):
        return sync_journey_routes(app=app)
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
