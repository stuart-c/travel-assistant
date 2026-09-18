"""Trip extraction, indexing, and in-memory caching for the RAPTOR engine."""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from app.models.timetable import Timetable
from app.services.planner.raptor.models import _ParsedTrip
from app.services.planner.transfers import normalise_id, parse_time_to_minutes

_TRIPS_CACHE: Dict[
    Tuple[Tuple[str, ...], Optional[str]],
    Tuple[float, List[_ParsedTrip], Set[str]],
] = {}
_TRIPS_CACHE_TTL_SECONDS = 86400.0  # 24 hours (flushed via clear_raptor_cache)


def clear_raptor_cache() -> None:
    """Flush in-memory RAPTOR timetable trips and stops cache."""
    _TRIPS_CACHE.clear()


def _extract_parsed_trips(
    timetables: List[Timetable],
) -> Tuple[List[_ParsedTrip], Set[str]]:
    """Convert Peewee Timetable models to structured in-memory trips and collect stop IDs."""
    parsed_trips: List[_ParsedTrip] = []
    timetable_stop_ids: Set[str] = set()

    for tt in timetables:
        content_dict = tt.get_content()
        stops_raw = content_dict.get("stops", [])
        trips_raw = content_dict.get("trips", [])

        if not stops_raw or not trips_raw:
            continue

        stop_ids = [str(s.get("id", "")).strip() for s in stops_raw]
        for s in stops_raw:
            s_id = s.get("id", "") if isinstance(s, dict) else str(s)
            if s_id:
                timetable_stop_ids.add(normalise_id(s_id))

        stop_indices = {s: i for i, s in enumerate(stop_ids)}

        for tr in trips_raw:
            times = tr.get("times", [])
            arr_list: List[Optional[int]] = []
            dep_list: List[Optional[int]] = []
            rollover_offset = 0
            last_minute: Optional[int] = None

            for t_item in times:
                if isinstance(t_item, dict):
                    arr_s = t_item.get("arr") or ""
                    dep_s = t_item.get("dep") or ""
                else:
                    arr_s = str(t_item or "")
                    dep_s = str(t_item or "")

                raw_arr = parse_time_to_minutes(arr_s)
                raw_dep = parse_time_to_minutes(dep_s)

                if raw_arr is None and raw_dep is not None:
                    raw_arr = raw_dep
                elif raw_dep is None and raw_arr is not None:
                    raw_dep = raw_arr

                arr_m = raw_arr
                dep_m = raw_dep

                if arr_m is not None:
                    arr_m += rollover_offset
                    if last_minute is not None and arr_m < last_minute:
                        rollover_offset += 1440
                        arr_m += 1440
                    last_minute = arr_m

                if dep_m is not None:
                    dep_m += rollover_offset
                    if last_minute is not None and dep_m < last_minute:
                        rollover_offset += 1440
                        dep_m += 1440
                    last_minute = dep_m

                arr_list.append(arr_m)
                dep_list.append(dep_m)

            while len(arr_list) < len(stop_ids):
                arr_list.append(None)
                dep_list.append(None)

            parsed_trips.append(
                _ParsedTrip(
                    trip_id=str(tr.get("id", "")),
                    timetable_id=tt.id,
                    line_name=tt.name,
                    transport_mode=tt.transport_type,
                    operator=tr.get("operator") or tr.get("toc"),
                    headsign=tr.get("headsign"),
                    stops=stop_ids,
                    arr_times=arr_list,
                    dep_times=dep_list,
                    stop_indices=stop_indices,
                )
            )

    return parsed_trips, timetable_stop_ids


def _build_stop_to_trips(trips: List[_ParsedTrip]) -> Dict[str, List[_ParsedTrip]]:
    """Index trips by normalised stop identifier."""
    stop_to_trips: Dict[str, List[_ParsedTrip]] = {}
    for tr in trips:
        for s in tr.stops:
            s_norm = normalise_id(s)
            stop_to_trips.setdefault(s_norm, []).append(tr)
    return stop_to_trips
