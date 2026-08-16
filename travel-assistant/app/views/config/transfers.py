"""Transfers configuration endpoints."""

from typing import Any, Dict, List, Optional
from flask import flash, redirect, render_template, request, url_for

from app.models import LocationTransfer, PlatformTransfer
from app.models.base import LOCATION_TYPES
from app.views.config import config_bp
from app.views.config.common import parse_json_form_list


def clean_location_transfer_item(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate and sanitize a single inter-location transfer item."""
    if not isinstance(entry, dict):
        return None

    from_type = str(entry.get("from_type", "rail")).lower().strip()
    if from_type not in LOCATION_TYPES:
        from_type = "rail"

    from_id = str(entry.get("from_id", "")).strip()
    from_name = str(entry.get("from_name", "")).strip()

    to_type = str(entry.get("to_type", "bus")).lower().strip()
    if to_type not in LOCATION_TYPES:
        to_type = "bus"

    to_id = str(entry.get("to_id", "")).strip()
    to_name = str(entry.get("to_name", "")).strip()

    try:
        transfer_time = max(1, int(entry.get("transfer_time_minutes", 5)))
    except (ValueError, TypeError):
        transfer_time = 5

    if not (from_id and to_id and from_name and to_name):
        return None

    return {
        "from_type": from_type,
        "from_id": from_id,
        "from_name": from_name,
        "to_type": to_type,
        "to_id": to_id,
        "to_name": to_name,
        "transfer_time_minutes": transfer_time,
        "bidirectional": bool(entry.get("bidirectional", True)),
        "step_free": bool(entry.get("step_free", False)),
        "notes": str(entry.get("notes", "")).strip(),
    }


def clean_platform_transfer_item(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate and sanitize a single platform/stand transfer item."""
    if not isinstance(entry, dict):
        return None

    loc_type = str(entry.get("location_type", "rail")).lower().strip()
    if loc_type not in LOCATION_TYPES:
        loc_type = "rail"

    location_id = str(entry.get("location_id", "")).strip()
    location_name = str(entry.get("location_name", "")).strip()
    from_platform = str(entry.get("from_platform", "")).strip()
    to_platform = str(entry.get("to_platform", "")).strip()

    try:
        transfer_time = max(1, int(entry.get("transfer_time_minutes", 2)))
    except (ValueError, TypeError):
        transfer_time = 2

    if not (location_id and location_name and from_platform and to_platform):
        return None

    return {
        "location_type": loc_type,
        "location_id": location_id,
        "location_name": location_name,
        "from_platform": from_platform,
        "to_platform": to_platform,
        "transfer_time_minutes": transfer_time,
        "bidirectional": bool(entry.get("bidirectional", True)),
        "step_free": bool(entry.get("step_free", False)),
        "notes": str(entry.get("notes", "")).strip(),
    }


@config_bp.route("/transfers", methods=["GET", "POST"])
def transfers() -> Any:
    """Manage inter-location walking links and station platform transfers."""
    if request.method == "POST":
        try:
            loc_items = parse_json_form_list("location_transfers_json")
            plat_items = parse_json_form_list("platform_transfers_json")

            cleaned_location_transfers: List[Dict[str, Any]] = [
                c
                for item in loc_items
                if (c := clean_location_transfer_item(item)) is not None
            ]
            cleaned_platform_transfers: List[Dict[str, Any]] = [
                c
                for item in plat_items
                if (c := clean_platform_transfer_item(item)) is not None
            ]

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
