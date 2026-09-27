"""Transfer, location endpoint, and date/time resolution utilities."""

from __future__ import annotations

import datetime
from typing import List, Optional, Tuple, Union

from app.models.location import Location
from app.models.timetable import Timetable
from app.models.transit import Stop
from app.models.walking import Walking

from app.utils.transit_time import (
    CODE_TO_TIMETABLE_ATTR,
    DAY_NAME_TO_CODE,
    VALID_DAYS,
)


def normalise_id(raw_id: str) -> str:
    """Strip standard prefix from identifiers for lookup compatibility."""
    s = str(raw_id).strip()
    for prefix in ("atco:", "naptan:", "ha:", "custom:"):
        if s.startswith(prefix):
            return s[len(prefix) :]
    return s


def extract_route_base_name(line_name: Optional[str]) -> str:
    """Extract normalised base route identifier from a line or service name.

    Examples:
        "Bus SB1: Woodcock Road to Bus Station" -> "sb1"
        "Bus 37X: The Crown Inn to Bus Station" -> "37x"
        "Route 73" -> "73"
        "Bus 73" -> "73"
        "Rail: London to Cambridge" -> "london to cambridge"
    """
    if not line_name:
        return ""
    name = str(line_name).strip()
    for mode_prefix in ("rail:", "train:", "bus:", "coach:"):
        if name.lower().startswith(mode_prefix):
            name = name[len(mode_prefix) :].strip()

    if ":" in name:
        prefix_part = name.split(":", 1)[0].strip()
        for p in ("bus ", "route ", "line "):
            if prefix_part.lower().startswith(p):
                prefix_part = prefix_part[len(p) :].strip()
        if (
            prefix_part
            and len(prefix_part) <= 20
            and prefix_part.lower() not in ("rail", "train")
            and " to " not in prefix_part.lower()
        ):
            return prefix_part.lower()
        name = name.split(":", 1)[1].strip()

    for prefix in ("bus ", "route ", "line "):
        if name.lower().startswith(prefix):
            name = name[len(prefix) :].strip()
    return name.lower()


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


def get_active_timetables(
    active_days: List[str],
    target_date: Optional[datetime.date] = None,
) -> List[Timetable]:
    """Retrieve active timetables using database-level filtering for days and dates."""
    query = Timetable.select()
    if active_days:
        day_conditions = []
        for code in active_days:
            attr_name = CODE_TO_TIMETABLE_ATTR.get(code)
            if attr_name and hasattr(Timetable, attr_name):
                day_conditions.append(getattr(Timetable, attr_name) == 1)
        if day_conditions:
            import functools
            import operator

            query = query.where(functools.reduce(operator.or_, day_conditions))
    if target_date:
        query = query.where(
            (Timetable.start_date.is_null() | (Timetable.start_date <= target_date))
            & (Timetable.end_date.is_null() | (Timetable.end_date >= target_date))
        )
    return list(query)


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
    "normalise_id",
    "extract_route_base_name",
    "resolve_endpoint_name",
    "resolve_active_days_and_date",
    "get_active_timetables",
    "get_access_edges",
]
