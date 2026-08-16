"""Journeys configuration endpoints."""

import json
from typing import Any, Dict, List
from flask import (
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from app.models import Journey
from app.views.config import config_bp


@config_bp.route("/journeys", methods=["GET", "POST"])
def journeys() -> Any:
    """Manage configured travel journeys and multi-time-window schedules."""
    if request.method == "POST":
        journeys_raw = request.form.get("journeys_json", "[]").strip()
        try:
            items = json.loads(journeys_raw)
            if not isinstance(items, list):
                raise ValueError("Payload must be a list of journey objects.")

            cleaned_items: List[Dict[str, Any]] = []
            for entry in items:
                if not isinstance(entry, dict):
                    continue

                VALID_LOCATION_TYPES = (
                    "rail",
                    "bus",
                    "tram",
                    "metro",
                    "ferry",
                    "air",
                    "ha",
                    "custom",
                )

                name = str(entry.get("name", "")).strip()
                from_type = str(entry.get("from_type", "rail")).strip().lower()
                if from_type not in VALID_LOCATION_TYPES:
                    from_type = "rail"

                from_id = str(entry.get("from_id", "")).strip()
                from_name = str(entry.get("from_name", "")).strip()

                to_type = str(entry.get("to_type", "rail")).strip().lower()
                if to_type not in VALID_LOCATION_TYPES:
                    to_type = "rail"

                to_id = str(entry.get("to_id", "")).strip()
                to_name = str(entry.get("to_name", "")).strip()

                if not name:
                    continue
                if not (from_id and from_name and to_id and to_name):
                    continue

                raw_time_settings = entry.get("time_settings", [])
                cleaned_time_settings: List[Dict[str, Any]] = []
                if isinstance(raw_time_settings, list):
                    for tw in raw_time_settings:
                        if not isinstance(tw, dict):
                            continue
                        days = tw.get("days", [])
                        if not isinstance(days, list):
                            days = []
                        valid_days = [
                            str(d).lower().strip()
                            for d in days
                            if str(d).lower().strip()
                            in (
                                "mon",
                                "tue",
                                "wed",
                                "thu",
                                "fri",
                                "sat",
                                "sun",
                                "bank_holiday",
                            )
                        ]
                        mode = str(tw.get("mode", "depart")).lower().strip()
                        if mode not in ("depart", "arrive"):
                            mode = "depart"
                        start_time = str(tw.get("start_time", "")).strip()
                        end_time = str(tw.get("end_time", "")).strip()

                        cleaned_time_settings.append(
                            {
                                "days": valid_days,
                                "mode": mode,
                                "start_time": start_time,
                                "end_time": end_time,
                            }
                        )

                cleaned_items.append(
                    {
                        "name": name,
                        "from_type": from_type or "station",
                        "from_id": from_id,
                        "from_name": from_name,
                        "to_type": to_type or "station",
                        "to_id": to_id,
                        "to_name": to_name,
                        "time_settings": json.dumps(cleaned_time_settings),
                    }
                )

            with Journey._meta.database.atomic():
                Journey.delete().execute()
                if cleaned_items:
                    Journey.insert_many(cleaned_items).execute()

            flash("Journeys saved successfully.", "success")
        except Exception as e:
            flash(f"Failed to save journeys: {str(e)}", "error")

        return redirect(url_for("config.journeys"), code=303)

    current_journeys = [j.to_dict() for j in Journey.select()]
    return render_template(
        "config_journeys.html",
        journeys=current_journeys,
        active_tab="journeys",
    )
