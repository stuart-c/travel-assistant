"""Home Assistant locations synchronisation manager.

Fetches configured Home Assistant zones via Supervisor / Core REST API
and reconciles them into the SQLite locations table.
"""

import logging
from typing import Any, Dict, Optional
from flask import Flask

from app.datasources import HomeAssistantClient
from app.db import db
from app.models import Location
from app.sync.common import run_sync_task

logger = logging.getLogger(__name__)


def sync_ha_locations(app: Optional[Flask] = None) -> Dict[str, Any]:
    """Synchronise geographic locations from Home Assistant zones."""
    client = HomeAssistantClient.from_settings()

    def _check_credentials() -> Optional[str]:
        if not client.token:
            return (
                "Home Assistant Supervisor token (SUPERVISOR_TOKEN) "
                "or HA_TOKEN not configured"
            )
        return None

    def _perform_sync() -> int:
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

        return count

    return run_sync_task(
        table_name="ha_locations",
        sync_operation=_perform_sync,
        client_check=_check_credentials,
        connection_error_template="Network or connection error contacting Home Assistant: {error}",
        success_message_factory=lambda cnt: (
            f"Successfully synchronised {cnt} location(s) from Home Assistant zones."
        ),
        app=app,
    )
