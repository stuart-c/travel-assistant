"""Timetables configuration endpoints."""

import datetime
import json
from typing import Any, Dict, List, Optional
from flask import (
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from app.models import Timetable
from app.views.config import config_bp


@config_bp.route("/timetables", methods=["GET", "POST"])
def timetables() -> Any:
    """Manage configured timetable schedules and operating days."""
    if request.method == "POST":
        timetables_raw = request.form.get("timetables_json", "[]").strip()
        try:
            items = json.loads(timetables_raw)
            if not isinstance(items, list):
                raise ValueError("Payload must be a list of timetable objects.")

            cleaned_items: List[Dict[str, Any]] = []
            for entry in items:
                if not isinstance(entry, dict):
                    continue
                name = str(entry.get("name", "")).strip()
                if not name:
                    continue

                start_date_val: Optional[datetime.date] = None
                start_date_raw = entry.get("start_date")
                if start_date_raw and str(start_date_raw).strip():
                    try:
                        start_date_val = datetime.date.fromisoformat(
                            str(start_date_raw).strip()
                        )
                    except ValueError:
                        raise ValueError(
                            f"Invalid start date format: {start_date_raw}. Expected YYYY-MM-DD."
                        )

                end_date_val: Optional[datetime.date] = None
                end_date_raw = entry.get("end_date")
                if end_date_raw and str(end_date_raw).strip():
                    try:
                        end_date_val = datetime.date.fromisoformat(
                            str(end_date_raw).strip()
                        )
                    except ValueError:
                        raise ValueError(
                            f"Invalid end date format: {end_date_raw}. Expected YYYY-MM-DD."
                        )

                if start_date_val and end_date_val and end_date_val < start_date_val:
                    raise ValueError(
                        f"End date ({end_date_val}) cannot be before "
                        f"start date ({start_date_val}) for timetable '{name}'."
                    )

                transport_type = (
                    str(entry.get("transport_type", "bus")).strip().lower() or "bus"
                )
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
                        parsed_content.get("stops", [])
                        if isinstance(parsed_content, dict)
                        else []
                    ),
                    "trips": (
                        parsed_content.get("trips", [])
                        if isinstance(parsed_content, dict)
                        else []
                    ),
                }

                cleaned_items.append(
                    {
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
                        "content": json.dumps(content_clean),
                    }
                )

            with Timetable._meta.database.atomic():
                Timetable.delete().execute()
                if cleaned_items:
                    Timetable.insert_many(cleaned_items).execute()

            flash("Timetables saved successfully.", "success")
        except Exception as e:
            flash(f"Failed to save timetables: {str(e)}", "error")

        return redirect(url_for("config.timetables"), code=303)

    current_timetables = [t.to_dict() for t in Timetable.select()]
    return render_template(
        "config_timetables.html",
        timetables=current_timetables,
        active_tab="timetables",
    )
