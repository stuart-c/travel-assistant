"""Transfer, location endpoint, and date/time resolution utilities."""

from __future__ import annotations

import datetime
from typing import List, Optional, Tuple, Union

from app.models.location import Location
from app.models.timetable import Timetable
from app.models.transfer import PlatformTransfer
from app.models.transit import Stop, StopInterchange
from app.models.walking import Walking

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


def parse_time_to_minutes(time_str: str) -> Optional[int]:
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


def normalise_id(raw_id: str) -> str:
    """Strip standard prefix from identifiers for lookup compatibility."""
    s = str(raw_id).strip()
    for prefix in ("atco:", "naptan:", "ha:", "custom:"):
        if s.startswith(prefix):
            return s[len(prefix) :]
    return s


def resolve_endpoint_name(endpoint_type: str, endpoint_id: str) -> str:
    """Resolve human-readable name for a location, stop, or station endpoint."""
    t = str(endpoint_type).strip().lower()
    raw_id = str(endpoint_id).strip()
    norm = normalise_id(raw_id)

    # Check Location model for HA / Custom places
    if (
        t in ("ha", "custom")
        or raw_id.startswith("ha:")
        or raw_id.startswith("custom:")
    ):
        try:
            loc = (
                Location.get_or_none(Location.id == raw_id)
                or Location.get_or_none(Location.id == norm)
                or Location.get_or_none(Location.id == f"ha:{norm}")
                or Location.get_or_none(Location.id == f"custom:{norm}")
            )
            if loc:
                return loc.name
        except Exception:
            pass

    # Check Stop model for Transit stops
    try:
        stop = Stop.get_by_code(raw_id) or Stop.get_by_code(norm)
        if stop:
            indicator_str = f" ({stop.indicator})" if stop.indicator else ""
            return f"{stop.name}{indicator_str}"
    except Exception:
        pass

    return raw_id


def resolve_transfer_duration(
    from_type: str,
    from_id: str,
    to_type: str,
    to_id: str,
    from_platform: Optional[str] = None,
    to_platform: Optional[str] = None,
    default_platform_minutes: int = 5,
) -> Optional[Tuple[int, str, Optional[int]]]:
    """Determine transfer time using strict 3-tier precedence hierarchy.

    Hierarchy:
      1. Explicit match in `walking` or `platform_transfers` table.
      2. Nearby stop interchange in `stop_interchanges` table.
      3. Default fallback of 5 minutes for intra-station platform interchanges.

    Returns:
        Tuple of (duration_minutes, transfer_kind, distance_metres) or None.
    """
    f_type = str(from_type).strip().lower()
    f_id = str(from_id).strip()
    t_type = str(to_type).strip().lower()
    t_id = str(to_id).strip()

    f_norm = normalise_id(f_id)
    t_norm = normalise_id(t_id)

    # Rule 1a: Check PlatformTransfer table if platforms are specified or station match
    if (
        f_type == "rail" and t_type == "rail" and (f_id == t_id or f_norm == t_norm)
    ) or (from_platform is not None and to_platform is not None):
        station_id = f_norm
        if from_platform and to_platform:
            pt = PlatformTransfer.find_transfer(station_id, from_platform, to_platform)
            if pt:
                return (pt.transfer_time_minutes, "platform_transfer", None)

        # Rule 3 Fallback: Platform interchange default buffer
        return (default_platform_minutes, "platform_transfer", None)

    # Rule 1b: Check Walking table for explicit configured connection
    walk_entry = Walking.find_walking_route(f_type, f_id, t_type, t_id)
    if not walk_entry:
        walk_entry = Walking.find_walking_route(f_type, f_norm, t_type, t_norm)
    if walk_entry:
        return (walk_entry.time_needed_minutes, "walk", None)

    # Rule 2: Check StopInterchange table (nearby stops within walking distance)
    interchange = (
        StopInterchange.select()
        .where(
            (
                (StopInterchange.from_stop_atco == f_id)
                | (StopInterchange.from_stop_atco == f_norm)
            )
            & (
                (StopInterchange.to_stop_atco == t_id)
                | (StopInterchange.to_stop_atco == t_norm)
            )
        )
        .first()
    )
    if interchange:
        return (
            interchange.estimated_walk_minutes,
            "interchange",
            interchange.distance_metres,
        )

    # If same transit stop ID
    if (f_id == t_id or f_norm == t_norm) and f_type == t_type:
        return (0, "interchange", 0)

    return None


def resolve_active_days_and_date(
    days_of_week: Optional[List[str]] = None,
    target_date: Optional[Union[datetime.date, str]] = None,
) -> Tuple[List[str], Optional[datetime.date]]:
    """Normalise and resolve active day codes and optional date object."""
    date_obj: Optional[datetime.date] = None

    if target_date is not None:
        if isinstance(target_date, datetime.date):
            date_obj = target_date
        elif isinstance(target_date, str) and target_date.strip():
            try:
                date_obj = datetime.date.fromisoformat(target_date.strip())
            except ValueError:
                pass

    active_days: List[str] = []
    if days_of_week:
        for d in days_of_week:
            clean_d = str(d).strip().lower()
            if clean_d in VALID_DAYS:
                active_days.append(clean_d)
            elif clean_d in DAY_NAME_TO_CODE:
                active_days.append(DAY_NAME_TO_CODE[clean_d])

    if date_obj is not None and not active_days:
        day_name = date_obj.strftime("%A").lower()
        if day_name in DAY_NAME_TO_CODE:
            active_days.append(DAY_NAME_TO_CODE[day_name])

    if not active_days:
        # Default to all weekdays if unspecified
        active_days = ["mon", "tue", "wed", "thu", "fri"]

    return active_days, date_obj


def is_timetable_active(
    timetable: Timetable,
    active_days: List[str],
    target_date: Optional[datetime.date] = None,
) -> bool:
    """Check if a timetable operates on the specified days and date validity range."""
    # Check date validity
    if target_date:
        if timetable.start_date and target_date < timetable.start_date:
            return False
        if timetable.end_date and target_date > timetable.end_date:
            return False

    # Check day masks
    operates_on_day = False
    for code in active_days:
        attr_name = CODE_TO_TIMETABLE_ATTR.get(code)
        if attr_name and getattr(timetable, attr_name, False):
            operates_on_day = True
            break

    return operates_on_day


def get_access_edges(
    loc_type: str, loc_id: str, is_origin: bool
) -> List[Tuple[str, str, str, str, int, str]]:
    """Retrieve all access/egress walking connections from or to an endpoint.

    Returns list of tuples: (from_type, from_id, to_type, to_id, duration_minutes, kind)
    """
    edges: List[Tuple[str, str, str, str, int, str]] = []
    l_type = str(loc_type).strip().lower()
    l_id = str(loc_id).strip()
    l_norm = normalise_id(l_id)

    if (
        l_type in ("ha", "custom")
        or l_id.startswith("ha:")
        or l_id.startswith("custom:")
    ):
        # Query Walking table for location access
        walks = Walking.select().where(
            (Walking.start_id == l_id)
            | (Walking.start_id == l_norm)
            | (Walking.finish_id == l_id)
            | (Walking.finish_id == l_norm)
        )
        for w in walks:
            w_start_id = w.start_id
            w_finish_id = w.finish_id

            if is_origin:
                if (w_start_id in (l_id, l_norm)) or (
                    w.bidirectional and w_finish_id in (l_id, l_norm)
                ):
                    target_type = (
                        w.finish_type if w_start_id in (l_id, l_norm) else w.start_type
                    )
                    target_id = (
                        w.finish_id if w_start_id in (l_id, l_norm) else w.start_id
                    )
                    edges.append(
                        (
                            l_type,
                            l_id,
                            target_type,
                            target_id,
                            w.time_needed_minutes,
                            "walk",
                        )
                    )
            else:
                if (w_finish_id in (l_id, l_norm)) or (
                    w.bidirectional and w_start_id in (l_id, l_norm)
                ):
                    source_type = (
                        w.start_type if w_finish_id in (l_id, l_norm) else w.finish_type
                    )
                    source_id = (
                        w.start_id if w_finish_id in (l_id, l_norm) else w.finish_id
                    )
                    edges.append(
                        (
                            source_type,
                            source_id,
                            l_type,
                            l_id,
                            w.time_needed_minutes,
                            "walk",
                        )
                    )
    else:
        # Direct transit stop endpoint: 0-minute self walk
        edges.append((l_type, l_id, l_type, l_id, 0, "walk"))

    return edges


__all__ = [
    "VALID_DAYS",
    "DAY_NAME_TO_CODE",
    "CODE_TO_TIMETABLE_ATTR",
    "parse_time_to_minutes",
    "format_minutes_to_time",
    "normalise_id",
    "resolve_endpoint_name",
    "resolve_transfer_duration",
    "resolve_active_days_and_date",
    "is_timetable_active",
    "get_access_edges",
]
