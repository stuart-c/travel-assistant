"""Home Assistant locations synchronisation manager.

Fetches configured Home Assistant zones via Supervisor / Core REST API
and reconciles them into the SQLite locations table.
"""

import logging
import time
from typing import Any, Dict, Optional
from flask import Flask

from app.datasources import (
    DataSourceAuthError,
    DataSourceConfigError,
    DataSourceConnectionError,
    HomeAssistantClient,
)
from app.db import db, init_db
from app.models import Location, SyncMetadata

logger = logging.getLogger(__name__)


def _ensure_db_initialized(app: Optional[Flask] = None) -> None:
    """Ensure Peewee DatabaseProxy has been initialised."""
    if db.obj is None:
        init_db(app)


def sync_ha_locations(app: Optional[Flask] = None) -> Dict[str, Any]:
    """Synchronise geographic locations from Home Assistant zones."""
    _ensure_db_initialized(app)
    start_time = time.time()

    with db.connection_context():
        client = HomeAssistantClient.from_settings()
        if not client.token:
            msg = "Home Assistant Supervisor token (SUPERVISOR_TOKEN) or HA_TOKEN not configured"
            SyncMetadata.record_skipped("ha_locations", msg)
            return {
                "table": "ha_locations",
                "status": "skipped_no_credentials",
                "records": 0,
                "message": msg,
                "duration_seconds": 0.0,
            }

        SyncMetadata.record_start("ha_locations")

        try:
            zones = client.fetch_zones()
            count = len(zones)

            with db.atomic():
                # Build lookup of existing locations by ID and name
                existing_map = {loc.id: loc for loc in Location.select()}
                existing_name_map = {loc.name: loc for loc in Location.select()}
                seen_ids = set()

                for zone in zones:
                    entity_id = zone.get("entity_id", "")
                    if entity_id.startswith("zone."):
                        obj_id = entity_id[5:]
                    else:
                        obj_id = entity_id or zone["name"].lower().replace(" ", "_")
                    ha_id = f"ha:{obj_id}"
                    name = zone["name"]
                    lat = zone["latitude"]
                    lon = zone["longitude"]
                    seen_ids.add(ha_id)

                    if ha_id in existing_map:
                        loc = existing_map[ha_id]
                        loc.name = name
                        loc.latitude = lat
                        loc.longitude = lon
                        loc.ha = True
                        loc.save()
                    elif name in existing_name_map:
                        # Existing record matching name without ha: id format - convert to HA zone
                        old_loc = existing_name_map[name]
                        if old_loc.id != ha_id:
                            Location.delete().where(Location.id == old_loc.id).execute()
                            new_loc = Location.create(
                                id=ha_id,
                                name=name,
                                latitude=lat,
                                longitude=lon,
                                ha=True,
                            )
                            existing_map[ha_id] = new_loc
                        else:
                            old_loc.latitude = lat
                            old_loc.longitude = lon
                            old_loc.ha = True
                            old_loc.save()
                    else:
                        new_loc = Location.create(
                            id=ha_id,
                            name=name,
                            latitude=lat,
                            longitude=lon,
                            ha=True,
                        )
                        existing_map[ha_id] = new_loc

                # Remove HA-synced locations that no longer exist in Home Assistant
                if seen_ids:
                    Location.delete().where(
                        (Location.ha == True)  # noqa: E712
                        & (~(Location.id.in_(list(seen_ids))))
                    ).execute()
                else:
                    Location.delete().where(Location.ha == True).execute()  # noqa: E712

            duration = round(time.time() - start_time, 2)
            SyncMetadata.record_success("ha_locations", count, duration)
            return {
                "table": "ha_locations",
                "status": "success",
                "records": count,
                "message": (
                    f"Successfully synchronised {count} location(s) "
                    "from Home Assistant zones."
                ),
                "duration_seconds": duration,
            }
        except (DataSourceAuthError, DataSourceConfigError) as exc:
            duration = round(time.time() - start_time, 2)
            err_msg = str(exc)
            SyncMetadata.record_error("ha_locations", err_msg, duration)
            return {
                "table": "ha_locations",
                "status": "error",
                "records": 0,
                "message": err_msg,
                "duration_seconds": duration,
            }
        except DataSourceConnectionError as exc:
            duration = round(time.time() - start_time, 2)
            err_msg = (
                f"Network or connection error contacting Home Assistant: {str(exc)}"
            )
            SyncMetadata.record_error("ha_locations", err_msg, duration)
            return {
                "table": "ha_locations",
                "status": "error",
                "records": 0,
                "message": err_msg,
                "duration_seconds": duration,
            }
        except Exception as exc:
            duration = round(time.time() - start_time, 2)
            err_msg = f"Unexpected error during Home Assistant location synchronisation: {str(exc)}"
            SyncMetadata.record_error("ha_locations", err_msg, duration)
            return {
                "table": "ha_locations",
                "status": "error",
                "records": 0,
                "message": err_msg,
                "duration_seconds": duration,
            }
