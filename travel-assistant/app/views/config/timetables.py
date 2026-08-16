"""Timetables configuration endpoints."""

import datetime
import json
from typing import Any, Dict, Optional
from flask import render_template, request

from app.models import Timetable
from app.models.base import TRANSPORT_MODES
from app.views.config import config_bp
from app.views.config.common import save_bulk_config


def clean_timetable_item(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate and sanitize a single timetable input item."""
    if not isinstance(entry, dict):
        return None

    name = str(entry.get("name", "")).strip()
    if not name:
        return None

    start_date_val: Optional[datetime.date] = None
    start_date_raw = entry.get("start_date")
    if start_date_raw and str(start_date_raw).strip():
        try:
            start_date_val = datetime.date.fromisoformat(str(start_date_raw).strip())
        except ValueError:
            raise ValueError(
                f"Invalid start date format: {start_date_raw}. Expected YYYY-MM-DD."
            )

    end_date_val: Optional[datetime.date] = None
    end_date_raw = entry.get("end_date")
    if end_date_raw and str(end_date_raw).strip():
        try:
            end_date_val = datetime.date.fromisoformat(str(end_date_raw).strip())
        except ValueError:
            raise ValueError(
                f"Invalid end date format: {end_date_raw}. Expected YYYY-MM-DD."
            )

    if start_date_val and end_date_val and end_date_val < start_date_val:
        raise ValueError(
            f"End date ({end_date_val}) cannot be before "
            f"start date ({start_date_val}) for timetable '{name}'."
        )

    raw_type = str(entry.get("transport_type", "bus")).strip().lower()
    transport_type = raw_type if raw_type in TRANSPORT_MODES else "bus"

    raw_content = entry.get("content")
    if isinstance(raw_content, str):
        try:
            parsed_content = json.loads(raw_content)
        except Exception:
            parsed_content = {"stops": [], "trips": []}
    elif isinstance(raw_content, dict):
        parsed_content = raw_content
    else:
        parsed_content = {"stops": [], "trips": []}

    content_clean = {
        "stops": (
            parsed_content.get("stops", []) if isinstance(parsed_content, dict) else []
        ),
        "trips": (
            parsed_content.get("trips", []) if isinstance(parsed_content, dict) else []
        ),
    }

    return {
        "name": name,
        "transport_type": transport_type,
        "start_date": start_date_val,
        "end_date": end_date_val,
        "monday": bool(entry.get("monday", True)),
        "tuesday": bool(entry.get("tuesday", True)),
        "wednesday": bool(entry.get("wednesday", True)),
        "thursday": bool(entry.get("thursday", True)),
        "friday": bool(entry.get("friday", True)),
        "saturday": bool(entry.get("saturday", True)),
        "sunday": bool(entry.get("sunday", True)),
        "bank_holiday": bool(entry.get("bank_holiday", True)),
        "content": content_clean,
    }


@config_bp.route("/timetables", methods=["GET", "POST"])
def timetables() -> Any:
    """Manage configured timetable schedules and operating days."""
    if request.method == "POST":
        return save_bulk_config(
            form_key="timetables_json",
            model_class=Timetable,
            clean_item_func=clean_timetable_item,
            entity_label="Timetables",
            redirect_endpoint="config.timetables",
        )

    current_timetables = [t.to_dict() for t in Timetable.select()]
    return render_template(
        "config_timetables.html",
        timetables=current_timetables,
        active_tab="timetables",
    )
