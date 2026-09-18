"""Corridor clustering and timetable construction for bus trips.

Groups raw vehicle trips by line and operating days, resolves directional corridors,
and aligns trips onto master stop sequences.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from app.datasources.bods.sequence_aligner import (
    align_times_to_master,
    can_merge_corridor,
    merge_stop_sequences,
)


def group_trips_into_timetables(
    raw_trips: List[Dict[str, Any]],
    stops_map: Dict[str, Dict[str, Any]],
    lookup: Dict[str, Dict[str, Any]],
    target_codes: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Group trips into Timetables by Line, Operating Days, and Directional Corridors."""
    trips_by_line_days: Dict[Tuple[str, Tuple[bool, ...]], List[Dict[str, Any]]] = {}

    for trip in raw_trips:
        l_name = trip["line_name"]
        d_dict = trip["days"]
        days_tuple = (
            bool(d_dict.get("monday", True)),
            bool(d_dict.get("tuesday", True)),
            bool(d_dict.get("wednesday", True)),
            bool(d_dict.get("thursday", True)),
            bool(d_dict.get("friday", True)),
            bool(d_dict.get("saturday", True)),
            bool(d_dict.get("sunday", True)),
            bool(d_dict.get("bank_holiday", True)),
        )
        trips_by_line_days.setdefault((l_name, days_tuple), []).append(trip)

    timetables: List[Dict[str, Any]] = []

    for (l_name, days_tuple), line_trips in trips_by_line_days.items():
        has_circular = any(
            (t["stops"][0] == t["stops"][-1] and len(t["stops"]) > 1)
            or t.get("direction") in ("circular", "clockwise", "anticlockwise")
            for t in line_trips
        )

        # Sort trips descending by stop count so longer routes form initial master sequences
        sorted_line_trips = sorted(
            line_trips, key=lambda t: len(t.get("stops", [])), reverse=True
        )

        corridors: List[Dict[str, Any]] = []

        for trip in sorted_line_trips:
            t_stops = trip["stops"]
            if not t_stops:
                continue

            t_dir = trip.get("direction", "").strip().lower()
            is_trip_circular = (
                has_circular
                or (t_stops[0] == t_stops[-1] and len(t_stops) > 1)
                or t_dir in ("circular", "clockwise", "anticlockwise")
            )

            merged = False
            for corr in corridors:
                if is_trip_circular:
                    if corr["is_circular"]:
                        corr["master_stops"] = merge_stop_sequences(
                            corr["master_stops"], t_stops
                        )
                        corr["trips"].append(trip)
                        merged = True
                        break
                else:
                    if not corr["is_circular"]:
                        if (
                            not t_dir
                            or not corr["direction"]
                            or t_dir == corr["direction"]
                        ):
                            if can_merge_corridor(corr["master_stops"], t_stops):
                                corr["master_stops"] = merge_stop_sequences(
                                    corr["master_stops"], t_stops
                                )
                                corr["trips"].append(trip)
                                if not corr["direction"] and t_dir:
                                    corr["direction"] = t_dir
                                merged = True
                                break

            if not merged:
                corridors.append(
                    {
                        "is_circular": is_trip_circular,
                        "direction": t_dir,
                        "master_stops": list(t_stops),
                        "trips": [trip],
                    }
                )

        for corr in corridors:
            master_stops = corr["master_stops"]
            corr_trips = corr["trips"]
            if not master_stops or not corr_trips:
                continue

            # Filter by target stops if requested
            if target_codes is not None:
                covers_target = any(
                    s.upper().strip() in target_codes for s in master_stops
                )
                if not covers_target:
                    continue

            stops_list: List[Dict[str, Any]] = []
            for s_ref in master_stops:
                st_meta = stops_map.get(s_ref) or lookup.get(s_ref.upper()) or {}
                stops_list.append(
                    {
                        "id": s_ref,
                        "name": st_meta.get("name") or s_ref,
                        "type": "bus",
                        "indicator": st_meta.get("indicator") or "Bus Stop",
                        "icon": "directions_bus",
                        "latitude": st_meta.get("latitude"),
                        "longitude": st_meta.get("longitude"),
                    }
                )

            first_name = stops_list[0]["name"] if stops_list else "Origin"
            last_name = stops_list[-1]["name"] if stops_list else "Destination"
            first_id = stops_list[0]["id"] if stops_list else ""
            last_id = stops_list[-1]["id"] if stops_list else ""

            if corr["is_circular"] or (
                first_id and last_id and first_id == last_id and len(stops_list) > 1
            ):
                timetable_name = f"Bus {l_name}: {first_name} (Circular)"
            else:
                timetable_name = f"Bus {l_name}: {first_name} to {last_name}"

            # Align each trip's times onto the master stop sequence
            aligned_trips: List[Dict[str, Any]] = []
            seen_trip_ids: Set[str] = set()

            sorted_trips = sorted(corr_trips, key=lambda t: t.get("dep_sec", 0))

            for idx, t in enumerate(sorted_trips):
                tid = t.get("id") or f"trip_{idx + 1}"
                if tid in seen_trip_ids:
                    continue
                seen_trip_ids.add(tid)

                aligned_times = align_times_to_master(
                    t["stops"], t["times"], master_stops
                )
                aligned_trips.append(
                    {
                        "id": tid,
                        "headsign": f"{l_name} to {last_name}".strip(),
                        "operator": t.get("operator", ""),
                        "times": aligned_times,
                    }
                )

            start_date = corr_trips[0].get("start_date")
            end_date = corr_trips[0].get("end_date")

            (
                mon,
                tue,
                wed,
                thu,
                fri,
                sat,
                sun,
                bh,
            ) = days_tuple

            timetables.append(
                {
                    "name": timetable_name,
                    "transport_type": "bus",
                    "start_date": start_date,
                    "end_date": end_date,
                    "monday": mon,
                    "tuesday": tue,
                    "wednesday": wed,
                    "thursday": thu,
                    "friday": fri,
                    "saturday": sat,
                    "sunday": sun,
                    "bank_holiday": bh,
                    "auto_added": True,
                    "content": {
                        "stops": stops_list,
                        "trips": aligned_trips,
                    },
                }
            )

    return timetables


def merge_timetable_into_collection(
    timetables_by_key: Dict[Tuple[str, Tuple[bool, ...]], Dict[str, Any]],
    parsed_tt: List[Dict[str, Any]],
) -> None:
    """Merge newly parsed timetables into the existing collection by route name and days."""
    for tt in parsed_tt:
        name = tt.get("name") or "Bus"
        days_key = (
            bool(tt.get("monday")),
            bool(tt.get("tuesday")),
            bool(tt.get("wednesday")),
            bool(tt.get("thursday")),
            bool(tt.get("friday")),
            bool(tt.get("saturday")),
            bool(tt.get("sunday")),
            bool(tt.get("bank_holiday")),
        )
        key = (name, days_key)

        if key in timetables_by_key:
            existing = timetables_by_key[key]
            existing_stops = [
                s.get("id", "") for s in existing.get("content", {}).get("stops", [])
            ]
            new_stops = [
                s.get("id", "") for s in tt.get("content", {}).get("stops", [])
            ]

            combined_stops = merge_stop_sequences(existing_stops, new_stops)

            stop_meta_by_id = {
                s.get("id"): s for s in existing.get("content", {}).get("stops", [])
            }
            for s in tt.get("content", {}).get("stops", []):
                if s.get("id") and s.get("id") not in stop_meta_by_id:
                    stop_meta_by_id[s.get("id")] = s

            combined_stops_list = [
                stop_meta_by_id.get(
                    sid,
                    {"id": sid, "name": sid, "type": "bus"},
                )
                for sid in combined_stops
            ]

            existing_trips = existing.get("content", {}).get("trips", [])
            for t in existing_trips:
                t["times"] = align_times_to_master(
                    existing_stops,
                    t.get("times", []),
                    combined_stops,
                )

            new_trips = tt.get("content", {}).get("trips", [])
            seen_trip_ids = {t.get("id") for t in existing_trips if t.get("id")}

            for nt in new_trips:
                tid = nt.get("id")
                if not tid or tid not in seen_trip_ids:
                    if tid:
                        seen_trip_ids.add(tid)
                    nt["times"] = align_times_to_master(
                        new_stops,
                        nt.get("times", []),
                        combined_stops,
                    )
                    existing_trips.append(nt)

            def _first_time_val(trip: Dict[str, Any]) -> str:
                for tm in trip.get("times", []):
                    if isinstance(tm, str) and tm.strip():
                        return tm.strip()
                return "99:99"

            existing_trips.sort(key=_first_time_val)
            existing["content"]["stops"] = combined_stops_list
            existing["content"]["trips"] = existing_trips
        else:
            timetables_by_key[key] = tt
