"""Transfers configuration endpoints."""

import json
from typing import Any, Dict, List
from flask import (
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from app.models import LocationTransfer, PlatformTransfer
from app.views.config import config_bp


@config_bp.route("/transfers", methods=["GET", "POST"])
def transfers() -> Any:
    """Manage inter-location walking links and station platform transfers."""
    if request.method == "POST":
        loc_raw = request.form.get("location_transfers_json", "[]").strip()
        plat_raw = request.form.get("platform_transfers_json", "[]").strip()

        try:
            loc_items = json.loads(loc_raw)
            plat_items = json.loads(plat_raw)

            if not isinstance(loc_items, list) or not isinstance(plat_items, list):
                raise ValueError(
                    "Payload must contain valid location and platform transfer lists."
                )

            cleaned_location_transfers: List[Dict[str, Any]] = []
            for entry in loc_items:
                if not isinstance(entry, dict):
                    continue
                from_type = str(entry.get("from_type", "station")).lower().strip()
                if from_type in ("rail", "train", "station"):
                    from_type = "station"
                elif from_type in ("bus", "bus_stop", "stop"):
                    from_type = "bus_stop"
                elif from_type in ("ha", "ha_location", "home_assistant"):
                    from_type = "ha_location"
                elif from_type in ("custom", "custom_location"):
                    from_type = "custom_location"
                else:
                    from_type = "station"

                from_id = str(entry.get("from_id", "")).strip()
                from_name = str(entry.get("from_name", "")).strip()

                to_type = str(entry.get("to_type", "bus_stop")).lower().strip()
                if to_type in ("rail", "train", "station"):
                    to_type = "station"
                elif to_type in ("bus", "bus_stop", "stop"):
                    to_type = "bus_stop"
                elif to_type in ("ha", "ha_location", "home_assistant"):
                    to_type = "ha_location"
                elif to_type in ("custom", "custom_location"):
                    to_type = "custom_location"
                else:
                    to_type = "bus_stop"

                to_id = str(entry.get("to_id", "")).strip()
                to_name = str(entry.get("to_name", "")).strip()

                try:
                    transfer_time = max(1, int(entry.get("transfer_time_minutes", 5)))
                except (ValueError, TypeError):
                    transfer_time = 5

                bidirectional = bool(entry.get("bidirectional", True))
                step_free = bool(entry.get("step_free", False))
                notes = str(entry.get("notes", "")).strip()

                if from_id and to_id and from_name and to_name:
                    cleaned_location_transfers.append(
                        {
                            "from_type": from_type,
                            "from_id": from_id,
                            "from_name": from_name,
                            "to_type": to_type,
                            "to_id": to_id,
                            "to_name": to_name,
                            "transfer_time_minutes": transfer_time,
                            "bidirectional": bidirectional,
                            "step_free": step_free,
                            "notes": notes,
                        }
                    )

            cleaned_platform_transfers: List[Dict[str, Any]] = []
            for entry in plat_items:
                if not isinstance(entry, dict):
                    continue
                loc_type = str(entry.get("location_type", "station")).lower().strip()
                if loc_type in ("rail", "train", "station"):
                    loc_type = "station"
                elif loc_type in ("bus", "bus_stop", "stop"):
                    loc_type = "bus_stop"
                elif loc_type in ("ha", "ha_location", "home_assistant"):
                    loc_type = "ha_location"
                elif loc_type in ("custom", "custom_location"):
                    loc_type = "custom_location"
                else:
                    loc_type = "station"

                location_id = str(entry.get("location_id", "")).strip()
                location_name = str(entry.get("location_name", "")).strip()
                from_platform = str(entry.get("from_platform", "")).strip()
                to_platform = str(entry.get("to_platform", "")).strip()

                try:
                    transfer_time = max(1, int(entry.get("transfer_time_minutes", 2)))
                except (ValueError, TypeError):
                    transfer_time = 2

                bidirectional = bool(entry.get("bidirectional", True))
                step_free = bool(entry.get("step_free", False))
                notes = str(entry.get("notes", "")).strip()

                if location_id and location_name and from_platform and to_platform:
                    cleaned_platform_transfers.append(
                        {
                            "location_type": loc_type,
                            "location_id": location_id,
                            "location_name": location_name,
                            "from_platform": from_platform,
                            "to_platform": to_platform,
                            "transfer_time_minutes": transfer_time,
                            "bidirectional": bidirectional,
                            "step_free": step_free,
                            "notes": notes,
                        }
                    )

            with LocationTransfer._meta.database.atomic():
                LocationTransfer.delete().execute()
                PlatformTransfer.delete().execute()
                if cleaned_location_transfers:
                    LocationTransfer.insert_many(cleaned_location_transfers).execute()
                if cleaned_platform_transfers:
                    PlatformTransfer.insert_many(cleaned_platform_transfers).execute()

            flash("Transfers saved successfully.", "success")
        except Exception as e:
            flash(f"Failed to save transfers: {str(e)}", "error")

        return redirect(url_for("config.transfers"), code=303)

    location_transfers = [t.to_dict() for t in LocationTransfer.select()]
    platform_transfers = [t.to_dict() for t in PlatformTransfer.select()]

    return render_template(
        "config_transfers.html",
        location_transfers=location_transfers,
        platform_transfers=platform_transfers,
        active_tab="transfers",
    )
