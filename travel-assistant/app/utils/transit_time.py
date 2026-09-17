"""Transit date, time, and duration parsing utilities."""

import datetime
import re
from typing import Optional, Union
import isoduration

# Canonical transport days
VALID_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun", "bank_holiday")

DAY_NAME_TO_CODE = {
    "monday": "mon",
    "tuesday": "tue",
    "wednesday": "wed",
    "thursday": "thu",
    "friday": "fri",
    "saturday": "sat",
    "sunday": "sun",
}

CODE_TO_TIMETABLE_ATTR = {
    "mon": "monday",
    "tue": "tuesday",
    "wed": "wednesday",
    "thu": "thursday",
    "fri": "friday",
    "sat": "saturday",
    "sun": "sunday",
    "bank_holiday": "bank_holiday",
}


def get_day_code(dt: Union[datetime.datetime, datetime.date]) -> str:
    """Return the canonical 3-letter day code ('mon'..'sun') for a given date or datetime."""
    weekday_idx = dt.weekday()
    day_codes = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    return day_codes[weekday_idx]


def parse_time_to_minutes(time_str: Optional[str]) -> Optional[int]:
    """Parse 'HH:MM' or 'HH:MM:SS' time string to minutes past midnight."""
    if not time_str:
        return None
    s = str(time_str).strip()
    if not s:
        return None
    parts = s.split(":")
    try:
        hours = int(parts[0])
        minutes = int(parts[1]) if len(parts) > 1 else 0
        return hours * 60 + minutes
    except (ValueError, IndexError):
        return None


def format_minutes_to_time(minutes: int) -> str:
    """Format minutes past midnight back to 'HH:MM' string."""
    norm = minutes % (24 * 60)
    hours = norm // 60
    mins = norm % 60
    return f"{hours:02d}:{mins:02d}"


def parse_iso_duration_seconds(dur_str: Optional[str]) -> int:
    """Parse ISO 8601 duration string (e.g. PT10M, PT1H30M, PT45S, PT1M30S) into seconds."""
    if not dur_str:
        return 0
    s = str(dur_str).strip().upper()
    if not s.startswith("P"):
        return 0
    try:
        parsed = isoduration.parse_duration(s)
        total_seconds = 0
        if parsed.date:
            total_seconds += int(parsed.date.days or 0) * 86400
        if parsed.time:
            total_seconds += int(parsed.time.hours or 0) * 3600
            total_seconds += int(parsed.time.minutes or 0) * 60
            total_seconds += int(parsed.time.seconds or 0)
        return total_seconds
    except Exception:
        match = re.search(
            r"PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?",
            s,
        )
        if not match:
            return 0
        hours = int(match.group("hours") or 0)
        minutes = int(match.group("minutes") or 0)
        seconds = int(match.group("seconds") or 0)
        return hours * 3600 + minutes * 60 + seconds


def parse_time_str_to_seconds(time_str: Optional[str]) -> Optional[int]:
    """Parse 'HH:MM:SS' or 'HH:MM' string into seconds from midnight."""
    if not time_str:
        return None
    parts = str(time_str).strip().split(":")
    if len(parts) >= 2:
        try:
            h = int(parts[0])
            m = int(parts[1])
            s = int(parts[2]) if len(parts) >= 3 else 0
            return h * 3600 + m * 60 + s
        except ValueError:
            return None
    return None


def format_seconds_to_hh_mm(seconds: int) -> str:
    """Format seconds past midnight to 'HH:MM' string."""
    m = (seconds // 60) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"
