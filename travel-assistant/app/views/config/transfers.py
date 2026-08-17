"""Transfers configuration endpoints."""

from typing import Any, Dict, List, Optional
from flask import flash, redirect, render_template, request, url_for

from app.models import PlatformTransfer
from app.models.base import LOCATION_TYPES
from app.views.config import config_bp
from app.views.config.common import parse_json_form_list


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
    """Manage intra-station platform and stand interchange transfers."""
    if request.method == "POST":
        try:
            plat_items = parse_json_form_list("platform_transfers_json")

            cleaned_platform_transfers: List[Dict[str, Any]] = [
                c
                for item in plat_items
                if (c := clean_platform_transfer_item(item)) is not None
            ]

            with PlatformTransfer._meta.database.atomic():
                PlatformTransfer.delete().execute()
                if cleaned_platform_transfers:
                    PlatformTransfer.insert_many(cleaned_platform_transfers).execute()

            flash("Transfers saved successfully.", "success")
        except Exception as e:
            flash(f"Failed to save transfers: {str(e)}", "error")

        return redirect(url_for("config.transfers"), code=303)

    platform_transfers = [t.to_dict() for t in PlatformTransfer.select()]

    return render_template(
        "config_transfers.html",
        platform_transfers=platform_transfers,
        active_tab="transfers",
    )
