"""Timetables configuration endpoints."""

import datetime
import json
from typing import Any, Dict, Optional

from app.models import (
    Timetable,
    TimetableContent,
    TimetableStop,
    TimetableTrip,
    TripTiming,
)
from app.models.base import TRANSPORT_MODES
from app.views.config import config_bp
from app.views.config.common import PageConfig, register_config_page


def clean_timetable_item(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate and sanitise a single timetable input item."""
    if not isinstance(entry, dict):
        return None

    name = str(entry.get("name", "")).strip()
    if not name:
        return None

    item_id: Optional[int] = None
    if entry.get("id") is not None and str(entry.get("id")).strip():
        try:
            item_id = int(entry.get("id"))
        except (ValueError, TypeError):
            item_id = None

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

    raw_stops = (
        parsed_content.get("stops", []) if isinstance(parsed_content, dict) else []
    )
    raw_trips = (
        parsed_content.get("trips", []) if isinstance(parsed_content, dict) else []
    )

    clean_stops = []
    if isinstance(raw_stops, list):
        for s in raw_stops:
            if isinstance(s, dict):
                try:
                    clean_stops.append(TimetableStop.model_validate(s))
                except Exception:
                    continue
            elif isinstance(s, str) and s.strip():
                clean_stops.append(
                    TimetableStop(
                        id=s.strip(),
                        name=s.strip(),
                        type=transport_type,
                        indicator="Stop",
                        icon="place",
                    )
                )

    def _clean_time_str(val: Any) -> str:
        if val is None:
            return ""
        s = str(val).strip()
        if not s:
            return ""
        parts = s.split(":")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            h, m = int(parts[0]), int(parts[1])
            if 0 <= h <= 23 and 0 <= m <= 59:
                return f"{h:02d}:{m:02d}"
        return s

    clean_trips = []
    if isinstance(raw_trips, list):
        for idx, t in enumerate(raw_trips):
            if not isinstance(t, dict):
                continue
            trip_id = str(t.get("id") or f"trip_{idx + 1}").strip()
            headsign = str(t.get("headsign") or "").strip()
            raw_times = t.get("times", [])
            if not isinstance(raw_times, list) and t.get("time"):
                raw_times = [t.get("time")]
            elif not isinstance(raw_times, list):
                raw_times = []

            cleaned_times = []
            for tm in raw_times:
                if isinstance(tm, dict):
                    arr_val = _clean_time_str(
                        tm.get("arr") if "arr" in tm else tm.get("arrival")
                    )
                    dep_val = _clean_time_str(
                        tm.get("dep") if "dep" in tm else tm.get("departure")
                    )
                    if arr_val or dep_val:
                        cleaned_times.append(TripTiming(arr=arr_val, dep=dep_val))
                    else:
                        cleaned_times.append("")
                elif isinstance(tm, str):
                    cleaned_times.append(_clean_time_str(tm))
                else:
                    cleaned_times.append("")

            trip_dict: Dict[str, Any] = {
                "id": trip_id,
                "headsign": headsign,
                "times": cleaned_times,
            }
            if t.get("toc"):
                trip_dict["toc"] = str(t.get("toc")).strip().upper()
            if t.get("operator"):
                trip_dict["operator"] = str(t.get("operator")).strip()

            try:
                clean_trips.append(TimetableTrip(**trip_dict))
            except Exception:
                continue

    content_obj = TimetableContent(stops=clean_stops, trips=clean_trips)
    content_clean = content_obj.model_dump()

    result: Dict[str, Any] = {
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
        "auto_added": bool(entry.get("auto_added", False)),
        "content": content_clean,
    }
    if item_id is not None:
        result["id"] = item_id

    return result


register_config_page(
    config_bp,
    PageConfig(
        route="/timetables",
        endpoint="timetables",
        template="config_timetables.html",
        model_class=Timetable,
        clean_item_func=clean_timetable_item,
        entity_label="Timetables",
        scope_filter=(Timetable.auto_added == False),  # noqa: E712
    ),
)
