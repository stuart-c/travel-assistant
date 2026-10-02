"""Transfer, location endpoint, and date/time resolution utilities."""

from __future__ import annotations

import datetime
from typing import Dict, List, Optional, Set, Tuple, Union

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


_STOP_ALIASES_CACHE: Dict[str, Set[str]] = {}

TOC_OPERATOR_MAP = {
    "thameslink": {"tl", "thameslink"},
    "great northern": {"gn", "great northern"},
    "greater anglia": {"le", "greater anglia", "ga"},
    "crosscountry": {"xc", "crosscountry", "cross country"},
    "lner": {"gr", "lner", "london north eastern railway"},
    "london north eastern railway": {"gr", "lner", "london north eastern railway"},
    "c2c": {"cc", "c2c"},
    "southern": {"sn", "southern"},
    "southeastern": {"se", "southeastern"},
    "elizabeth line": {"xr", "elizabeth line"},
    "overground": {"lo", "overground", "london overground"},
    "east midlands railway": {"em", "emr", "east midlands railway"},
    "avanti west coast": {"vt", "avanti", "avanti west coast"},
}


def clear_stop_aliases_cache() -> None:
    """Clear the in-memory stop alias resolution cache."""
    _STOP_ALIASES_CACHE.clear()


def resolve_stop_id_aliases(
    stop_id: str,
    stop_name: Optional[str] = None,
) -> Set[str]:
    """Resolve an identifier into candidate alias ATCO and NaPTAN codes.

    Handles:
    - Normalised and raw ID forms (stripping/adding standard prefixes).
    - Synthetic Google IDs (google:...) mapped to nearby NaPTAN stops or Walking links.
    - Linked interchanges via StopInterchange records (e.g. 0500CAMBDGE0 <-> 9100CAMBDGE).
    - Rail station counterparts sharing the same station name.
    """
    raw_id = str(stop_id or "").strip()
    if not raw_id:
        return set()

    norm_id = normalise_id(raw_id)
    cache_key = norm_id.lower()
    if cache_key in _STOP_ALIASES_CACHE:
        return _STOP_ALIASES_CACHE[cache_key]

    aliases: Set[str] = {
        raw_id,
        norm_id,
        raw_id.lower(),
        norm_id.lower(),
        f"atco:{norm_id}",
        f"naptan:{norm_id}",
    }

    try:
        from app.models.transit import Stop
        from app.models.walking import Walking

        # 1. Synthetic Google ID resolution
        if raw_id.startswith("google:") or norm_id.startswith("google:"):
            st = Stop.get_by_atco(raw_id) or Stop.get_by_atco(norm_id)
            if st and st.latitude is not None and st.longitude is not None:
                lat, lon = float(st.latitude), float(st.longitude)
                nearby = list(
                    Stop.select().where(
                        (Stop.latitude.is_null(False))
                        & (Stop.latitude >= lat - 0.001)
                        & (Stop.latitude <= lat + 0.001)
                        & (Stop.longitude >= lon - 0.0015)
                        & (Stop.longitude <= lon + 0.0015)
                    )
                )
                for nb in nearby:
                    if not nb.atco_code.startswith("google:"):
                        aliases.add(nb.atco_code)
                        aliases.add(normalise_id(nb.atco_code))
                        aliases.add(nb.atco_code.lower())
                        aliases.add(normalise_id(nb.atco_code).lower())

            walks = list(
                Walking.select().where(
                    (Walking.start_id == raw_id)
                    | (Walking.start_id == norm_id)
                    | (Walking.finish_id == raw_id)
                    | (Walking.finish_id == norm_id)
                )
            )
            for w in walks:
                other_id = (
                    w.finish_id if w.start_id in (raw_id, norm_id) else w.start_id
                )
                if other_id and not other_id.startswith("google:"):
                    aliases.add(other_id)
                    aliases.add(normalise_id(other_id))
                    aliases.add(other_id.lower())
                    aliases.add(normalise_id(other_id).lower())

        def _add_alias_forms(code: str) -> None:
            c = str(code).strip()
            if not c:
                return
            c_norm = normalise_id(c)
            aliases.add(c)
            aliases.add(c_norm)
            aliases.add(c.lower())
            aliases.add(c_norm.lower())
            aliases.add(f"atco:{c_norm}")
            aliases.add(f"naptan:{c_norm}")

        # 3. Rail station counterpart resolution by station name (e.g. 0500CAMBDGE0 <-> 9100CAMBDGE)
        st_obj = Stop.get_by_atco(raw_id) or Stop.get_by_atco(norm_id)
        search_name = (
            st_obj.name
            if (st_obj and st_obj.stop_type == "rail")
            else (
                stop_name
                if (
                    stop_name
                    and ("rail" in stop_name.lower() or "station" in stop_name.lower())
                )
                else None
            )
        )
        if search_name:
            import re

            base_stn = re.sub(
                r"(?i)\s+(railway|rail)?\s*station", "", search_name
            ).strip()
            if base_stn:
                pattern = f"%{base_stn}%"
                counterparts = list(
                    Stop.select()
                    .where((Stop.stop_type == "rail") & (Stop.name**pattern))
                    .limit(10)
                )
                for cp in counterparts:
                    _add_alias_forms(cp.atco_code)
                    if cp.naptan_code:
                        _add_alias_forms(cp.naptan_code)

    except Exception:
        pass

    _STOP_ALIASES_CACHE[cache_key] = aliases
    return aliases


def matches_transit_line_or_operator(
    leg_line_name: Optional[str],
    leg_operator_name: Optional[str],
    leg_mode: Optional[str],
    trip_line_name: str,
    trip_operator: Optional[str],
    trip_headsign: Optional[str],
    trip_mode: str,
) -> bool:
    """Check if a candidate trip matches a route leg's line, operator, or TOC code."""
    line_base = extract_route_base_name(leg_line_name)
    if not line_base:
        return True

    tr_line_base = extract_route_base_name(trip_line_name)
    if line_base in tr_line_base or tr_line_base in line_base:
        return True

    tr_op = (trip_operator or "").lower().strip()
    if tr_op and (line_base in tr_op or tr_op in line_base):
        return True

    tr_head = (trip_headsign or "").lower().strip()
    if tr_head and (line_base in tr_head):
        return True

    is_rail = leg_mode == "rail" or trip_mode == "rail"
    if is_rail:
        # Check if the leg specifically requests a known TOC
        leg_matched_tocs = set()
        for known_key, tokens in TOC_OPERATOR_MAP.items():
            if line_base == known_key or any(tok == line_base for tok in tokens):
                leg_matched_tocs.update(tokens)

        if leg_matched_tocs:
            if any(tok in tr_op for tok in leg_matched_tocs):
                return True
            head_tokens = tr_head.split()
            if any(tok in head_tokens for tok in leg_matched_tocs):
                return True
            if any(tok in tr_line_base for tok in leg_matched_tocs):
                return True
            # Leg specified a specific TOC, but trip belongs to a different TOC
            for other_key, other_tokens in TOC_OPERATOR_MAP.items():
                if other_key != line_base and not (other_tokens & leg_matched_tocs):
                    if any(tok in tr_op for tok in other_tokens) or any(
                        tok in tr_head.split() for tok in other_tokens
                    ):
                        return False
            return True

        for known_key, tokens in TOC_OPERATOR_MAP.items():
            if line_base == known_key or any(tok in line_base for tok in tokens):
                if any(tok in tr_op for tok in tokens):
                    return True
                head_tokens = tr_head.split()
                if any(tok in head_tokens for tok in tokens):
                    return True
                if any(tok in tr_line_base for tok in tokens):
                    return True
        return True

    return False


__all__ = [
    "normalise_id",
    "extract_route_base_name",
    "resolve_endpoint_name",
    "resolve_active_days_and_date",
    "get_active_timetables",
    "get_access_edges",
    "resolve_stop_id_aliases",
    "matches_transit_line_or_operator",
    "clear_stop_aliases_cache",
]
