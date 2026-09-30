"""Corridor learner service for discovering, parsing, auditing, and persisting transit routes."""

import datetime
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.datasources.exceptions import DataSourceConfigError
from app.datasources.google_maps import GoogleMapsClient
from app.models.journey import Journey
from app.models.journey_route import JourneyRoute
from app.models.route_query_log import RouteQueryLog
from app.models.timetable import Timetable
from app.models.transit import Stop
from app.models.walking import Walking
from app.services.planner.transfers import normalise_id
from app.utils.geo import haversine_distance_m, resolve_endpoint_coordinates
from app.utils.transit_time import parse_duration_seconds, parse_time_to_minutes

logger = logging.getLogger(__name__)

DAY_NAME_MAP = {
    0: "mon",
    1: "tue",
    2: "wed",
    3: "thu",
    4: "fri",
    5: "sat",
    6: "sun",
}


def resolve_target_commute_datetime(
    journey: Journey,
    reference_dt: Optional[datetime.datetime] = None,
) -> Tuple[Optional[datetime.datetime], Optional[datetime.datetime]]:
    """Determine the optimal target departure or arrival datetime for transit routing discovery.

    Inspects configured journey time settings to evaluate the upcoming commute window
    (targeting daytime service hours, peak trains, and campus shuttles) rather than
    evaluating routes at midnight or off-peak hours.

    Args:
        journey: Configured Journey model.
        reference_dt: Reference datetime (defaults to current local time).

    Returns:
        Tuple of (departure_time, arrival_time) where at most one is non-None.
    """
    if reference_dt is None:
        reference_dt = datetime.datetime.now()

    time_settings = journey.get_time_settings()
    if time_settings:
        for offset in range(0, 8):
            target_date = reference_dt.date() + datetime.timedelta(days=offset)
            day_code = DAY_NAME_MAP.get(target_date.weekday())
            for setting in time_settings:
                setting_days = setting.get("days", [])
                if day_code not in setting_days:
                    continue

                mode = str(setting.get("mode", "depart")).lower().strip()
                start_time_str = setting.get("start_time") or ""
                end_time_str = setting.get("end_time") or ""

                if mode == "arrive":
                    time_str = end_time_str or start_time_str or "09:00"
                    try:
                        h, m = map(int, time_str.split(":"))
                    except Exception:
                        h, m = 9, 0
                    target_dt = datetime.datetime.combine(
                        target_date, datetime.time(h, m)
                    )
                    if offset == 0 and target_dt <= reference_dt:
                        continue
                    return None, target_dt
                else:
                    time_str = start_time_str or end_time_str or "08:00"
                    try:
                        h, m = map(int, time_str.split(":"))
                    except Exception:
                        h, m = 8, 0
                    target_dt = datetime.datetime.combine(
                        target_date, datetime.time(h, m)
                    )
                    if offset == 0 and target_dt <= reference_dt:
                        continue
                    return target_dt, None

    # Fallback to the next upcoming weekday morning commute (08:30)
    for offset in range(0, 8):
        target_date = reference_dt.date() + datetime.timedelta(days=offset)
        if target_date.weekday() < 5:  # Mon-Fri
            target_dt = datetime.datetime.combine(target_date, datetime.time(8, 30))
            if offset == 0 and target_dt <= reference_dt:
                continue
            return target_dt, None

    # Ultimate fallback
    return reference_dt, None


VEHICLE_TYPE_MAP = {
    "bus": "bus",
    "intercity_bus": "bus",
    "trolleybus": "bus",
    "subway": "metro",
    "metro_rail": "metro",
    "monorail": "metro",
    "heavy_rail": "rail",
    "commuter_train": "rail",
    "high_speed_train": "rail",
    "long_distance_train": "rail",
    "rail": "rail",
    "train": "rail",
    "tram": "tram",
    "light_rail": "tram",
    "ferry": "ferry",
}


def map_vehicle_type(google_vehicle_type: Optional[str]) -> str:
    """Map Google Routes API vehicle type to canonical transport mode."""
    v_type = str(google_vehicle_type or "").strip().lower()
    return VEHICLE_TYPE_MAP.get(v_type, "bus")


def resolve_or_create_stop(
    name: str,
    lat: Optional[float],
    lng: Optional[float],
    stop_type: str = "bus",
) -> Tuple[str, str, str]:
    """Resolve an existing transit stop or create a new Stop entity.

    Returns:
        Tuple of (stop_type, atco_code, stop_name).
    """
    clean_name = (name or "").strip()
    norm_type = (stop_type or "bus").strip().lower()

    if clean_name:
        existing = Stop.search(clean_name, stop_type=norm_type, limit=1)
        if existing:
            return existing[0].stop_type, existing[0].atco_code, existing[0].name

    # Check for real existing NaPTAN stop nearby before creating synthetic ID
    if lat is not None and lng is not None:
        try:
            nearby = list(
                Stop.select().where(
                    (Stop.latitude.is_null(False))
                    & (Stop.latitude >= lat - 0.001)
                    & (Stop.latitude <= lat + 0.001)
                    & (Stop.longitude >= lng - 0.0015)
                    & (Stop.longitude <= lng + 0.0015)
                    & (Stop.stop_type == norm_type)
                )
            )
            real_nearby = [s for s in nearby if not s.atco_code.startswith("google:")]
            if real_nearby:
                real_nearby.sort(
                    key=lambda s: haversine_distance_m(
                        lat, lng, float(s.latitude or 0.0), float(s.longitude or 0.0)
                    )
                )
                closest = real_nearby[0]
                dist = haversine_distance_m(
                    lat,
                    lng,
                    float(closest.latitude or 0.0),
                    float(closest.longitude or 0.0),
                )
                if dist <= 100.0:
                    return closest.stop_type, closest.atco_code, closest.name
        except Exception:
            pass

    # Generate synthetic ATCO code from name and coordinates
    slug = re.sub(r"[^a-z0-9]+", "_", clean_name.lower()).strip("_")
    coord_part = f"{round(lat or 0.0, 4)}_{round(lng or 0.0, 4)}".replace(".", "_")
    atco_code = f"google:{slug[:30]}_{coord_part}"

    # Check if this ATCO already exists
    existing_by_atco = Stop.get_by_atco(atco_code)
    if existing_by_atco:
        return (
            existing_by_atco.stop_type,
            existing_by_atco.atco_code,
            existing_by_atco.name,
        )

    try:
        new_stop = Stop.create(
            atco_code=atco_code,
            name=clean_name or "Transit Stop",
            stop_type=norm_type,
            latitude=lat,
            longitude=lng,
        )
        return new_stop.stop_type, new_stop.atco_code, new_stop.name
    except Exception as exc:
        logger.debug("Could not create Stop for '%s': %s", clean_name, exc)
        return norm_type, atco_code, clean_name


def _combine_polylines(polylines: List[Optional[str]]) -> Optional[str]:
    """Combine multiple encoded polylines into a single continuous polyline."""
    valid = [p for p in polylines if p]
    if not valid:
        return None
    if len(valid) == 1:
        return valid[0]
    try:
        import polyline

        all_pts: List[Tuple[float, float]] = []
        for p in valid:
            all_pts.extend(polyline.decode(p))
        if all_pts:
            return polyline.encode(all_pts)
    except Exception:
        pass
    return valid[0]


def ensure_walking_connection(
    from_type: str,
    from_id: str,
    from_name: str,
    to_type: str,
    to_id: str,
    to_name: str,
    duration_minutes: int,
    distance_m: int = 0,
) -> None:
    """Ensure walking connection exists in the walking table."""
    try:
        if not from_id or not to_id:
            return
        if from_type == to_type and normalise_id(from_id) == normalise_id(to_id):
            return
        if distance_m > 5000:
            return
        existing = Walking.find_walking_route(from_type, from_id, to_type, to_id)
        if not existing:
            Walking.create(
                start_type=from_type,
                start_id=from_id,
                start_name=from_name,
                finish_type=to_type,
                finish_id=to_id,
                finish_name=to_name,
                time_needed_minutes=max(1, duration_minutes),
                bidirectional=True,
                auto_generated=True,
            )

        # Also connect real NaPTAN stop aliases if synthetic ID was passed
        from app.services.planner.transfers import resolve_stop_id_aliases

        from_aliases = resolve_stop_id_aliases(from_id, from_name)
        to_aliases = resolve_stop_id_aliases(to_id, to_name)
        for f_alt in from_aliases:
            for t_alt in to_aliases:
                if (
                    f_alt != t_alt
                    and not f_alt.startswith("google:")
                    and not t_alt.startswith("google:")
                    and not f_alt.startswith("atco:")
                    and not t_alt.startswith("atco:")
                ):
                    if not Walking.find_walking_route(from_type, f_alt, to_type, t_alt):
                        Walking.create(
                            start_type=from_type,
                            start_id=f_alt,
                            start_name=from_name,
                            finish_type=to_type,
                            finish_id=t_alt,
                            finish_name=to_name,
                            time_needed_minutes=max(1, duration_minutes),
                            bidirectional=True,
                            auto_generated=True,
                        )
    except Exception as exc:
        logger.debug("Could not ensure walking connection: %s", exc)


def _parse_google_route_to_legs(
    route: Dict[str, Any],
    from_type: str,
    from_id: str,
    from_name: str,
    to_type: str,
    to_id: str,
    to_name: str,
) -> Tuple[List[Dict[str, Any]], int, List[str], int, str]:
    """Parse a Google Routes API route dictionary into standardised transit legs."""
    total_duration_sec = parse_duration_seconds(route.get("duration"))
    total_duration_mins = max(1, total_duration_sec // 60)
    route_desc = route.get("description", "").strip()

    legs_data: List[Dict[str, Any]] = []
    transit_modes_used: List[str] = []
    transit_count = 0

    route_legs = route.get("legs", [])
    stage_idx = 1
    step_idx = 1

    raw_steps: List[Dict[str, Any]] = []
    for r_leg in route_legs:
        raw_steps.extend(r_leg.get("steps", []))

    segments: List[Dict[str, Any]] = []
    walk_accumulator: List[Dict[str, Any]] = []

    for step in raw_steps:
        travel_mode = str(step.get("travelMode", "")).upper()
        if travel_mode == "TRANSIT":
            if walk_accumulator:
                segments.append({"type": "walk", "steps": walk_accumulator})
                walk_accumulator = []
            segments.append({"type": "transit", "step": step})
        else:
            walk_accumulator.append(step)

    if walk_accumulator:
        segments.append({"type": "walk", "steps": walk_accumulator})

    current_endpoint_type = from_type
    current_endpoint_id = from_id
    current_endpoint_name = from_name

    for seg_idx, seg in enumerate(segments):
        if seg["type"] == "transit":
            transit_count += 1
            step = seg["step"]
            step_dur_sec = parse_duration_seconds(step.get("staticDuration"))
            step_dur_mins = max(1, round(step_dur_sec / 60)) if step_dur_sec else 1
            step_dist_m = int(step.get("distanceMeters", 0))

            transit_details = step.get("transitDetails", {})
            stop_details = transit_details.get("stopDetails", {})
            dep_stop_raw = stop_details.get("departureStop", {})
            arr_stop_raw = stop_details.get("arrivalStop", {})

            line_info = transit_details.get("transitLine", {})
            line_name = line_info.get("nameShort") or line_info.get("name") or "Transit"
            agency = line_info.get("transitAgency", {}).get("name")
            vehicle_type = line_info.get("vehicle", {}).get("type")
            canonical_mode = map_vehicle_type(vehicle_type)
            transit_modes_used.append(canonical_mode)

            dep_lat = dep_stop_raw.get("location", {}).get("latLng", {}).get("latitude")
            dep_lng = (
                dep_stop_raw.get("location", {}).get("latLng", {}).get("longitude")
            )
            arr_lat = arr_stop_raw.get("location", {}).get("latLng", {}).get("latitude")
            arr_lng = (
                arr_stop_raw.get("location", {}).get("latLng", {}).get("longitude")
            )

            dep_type, dep_id, dep_name = resolve_or_create_stop(
                dep_stop_raw.get("name", "Boarding Stop"),
                dep_lat,
                dep_lng,
                stop_type=canonical_mode,
            )
            arr_type, arr_id, arr_name = resolve_or_create_stop(
                arr_stop_raw.get("name", "Alight Stop"),
                arr_lat,
                arr_lng,
                stop_type=canonical_mode,
            )

            leg_dict = {
                "stage_index": stage_idx,
                "step_index": step_idx,
                "leg_type": "transit",
                "transport_mode": canonical_mode,
                "line_name": line_name,
                "operator_name": agency,
                "from_type": dep_type,
                "from_id": dep_id,
                "from_name": dep_name,
                "to_type": arr_type,
                "to_id": arr_id,
                "to_name": arr_name,
                "duration_minutes": step_dur_mins,
                "distance_m": step_dist_m,
                "stops_count": int(transit_details.get("stopCount", 0)),
            }
            step_poly = step.get("polyline", {}).get("encodedPolyline")
            if not step_poly and isinstance(route.get("polyline"), dict):
                step_poly = route["polyline"].get("encodedPolyline")
            if step_poly:
                leg_dict["polyline"] = step_poly
            legs_data.append(leg_dict)

            current_endpoint_type = arr_type
            current_endpoint_id = arr_id
            current_endpoint_name = arr_name
            stage_idx += 1
            step_idx += 1

        else:
            walk_steps = seg["steps"]
            total_dur_sec = sum(
                parse_duration_seconds(st.get("staticDuration")) for st in walk_steps
            )
            total_dur_mins = max(1, round(total_dur_sec / 60)) if total_dur_sec else 1
            total_dist_m = sum(int(st.get("distanceMeters", 0)) for st in walk_steps)

            next_transit = next(
                (s for s in segments[seg_idx + 1 :] if s["type"] == "transit"),
                None,
            )

            if next_transit:
                n_dep = (
                    next_transit["step"]
                    .get("transitDetails", {})
                    .get("stopDetails", {})
                    .get("departureStop", {})
                )
                n_lat = n_dep.get("location", {}).get("latLng", {}).get("latitude")
                n_lng = n_dep.get("location", {}).get("latLng", {}).get("longitude")
                n_vehicle = (
                    next_transit["step"]
                    .get("transitDetails", {})
                    .get("transitLine", {})
                    .get("vehicle", {})
                    .get("type")
                )
                next_type, next_id, next_name = resolve_or_create_stop(
                    n_dep.get("name", "Transit Stop"),
                    n_lat,
                    n_lng,
                    stop_type=map_vehicle_type(n_vehicle),
                )
            else:
                next_type = to_type
                next_id = to_id
                next_name = to_name

            if current_endpoint_type == next_type and normalise_id(
                current_endpoint_id
            ) == normalise_id(next_id):
                continue

            step_polys = [
                st.get("polyline", {}).get("encodedPolyline") for st in walk_steps
            ]
            comb_poly = _combine_polylines(step_polys)

            leg_dict = {
                "stage_index": stage_idx,
                "step_index": step_idx,
                "leg_type": "walk",
                "from_type": current_endpoint_type,
                "from_id": current_endpoint_id,
                "from_name": current_endpoint_name,
                "to_type": next_type,
                "to_id": next_id,
                "to_name": next_name,
                "duration_minutes": total_dur_mins,
                "distance_m": total_dist_m,
            }
            if comb_poly:
                leg_dict["polyline"] = comb_poly
            legs_data.append(leg_dict)

            ensure_walking_connection(
                current_endpoint_type,
                current_endpoint_id,
                current_endpoint_name,
                next_type,
                next_id,
                next_name,
                total_dur_mins,
                total_dist_m,
            )

            current_endpoint_type = next_type
            current_endpoint_id = next_id
            current_endpoint_name = next_name
            stage_idx += 1
            step_idx += 1

    return legs_data, total_duration_mins, transit_modes_used, transit_count, route_desc


def _get_timetable_trip_stats(tt: Timetable) -> Tuple[int, int]:
    """Calculate duration in minutes and approximate distance in metres from a timetable."""
    content = tt.get_content()
    trips = content.get("trips", [])
    dur_mins = 10
    for tr in trips:
        times = tr.get("times", [])
        if len(times) >= 2:
            t_first = times[0]
            t_last = times[-1]
            first_s = (
                t_first.get("dep") or t_first.get("arr")
                if isinstance(t_first, dict)
                else str(t_first)
            )
            last_s = (
                t_last.get("arr") or t_last.get("dep")
                if isinstance(t_last, dict)
                else str(t_last)
            )
            m_start = parse_time_to_minutes(first_s)
            m_end = parse_time_to_minutes(last_s)
            if m_start is not None and m_end is not None and m_end > m_start:
                dur_mins = m_end - m_start
                break

    dist_m = 1500
    stops = content.get("stops", [])
    if len(stops) >= 2:
        try:
            s0 = stops[0]
            s1 = stops[-1]
            lat0, lon0 = s0.get("latitude"), s0.get("longitude")
            lat1, lon1 = s1.get("latitude"), s1.get("longitude")
            if lat0 and lon0 and lat1 and lon1:
                dist_m = max(
                    100,
                    int(
                        haversine_distance_m(
                            float(lat0), float(lon0), float(lat1), float(lon1)
                        )
                    ),
                )
        except Exception:
            pass
    return dur_mins, dist_m


def _is_stop_connected_to_endpoint(
    stop: Dict[str, Any],
    endpoint_type: str,
    endpoint_id: str,
    is_origin: bool,
) -> Tuple[bool, int, int]:
    """Check if a timetable stop matches a journey endpoint directly or via walking link."""
    s_id = str(stop.get("id", ""))
    s_type = str(stop.get("type", "bus"))
    if not s_id or not endpoint_id:
        return False, 0, 0

    norm_s = normalise_id(s_id).lower()
    norm_ep = normalise_id(endpoint_id).lower()

    if norm_s == norm_ep:
        return True, 0, 0

    if is_origin:
        walk = Walking.find_walking_route(endpoint_type, endpoint_id, s_type, s_id)
        if not walk:
            walk = Walking.find_walking_route(endpoint_type, norm_ep, s_type, norm_s)
    else:
        walk = Walking.find_walking_route(s_type, s_id, endpoint_type, endpoint_id)
        if not walk:
            walk = Walking.find_walking_route(s_type, norm_s, endpoint_type, norm_ep)

    if walk and walk.time_needed_minutes <= 25:
        return True, walk.time_needed_minutes, 0

    return False, 0, 0


def _matches_interchange(
    leg_stop_id: str,
    leg_stop_type: str,
    interchange_stop: Dict[str, Any],
) -> Tuple[bool, int]:
    """Check if a route leg stop matches the custom timetable interchange stop."""
    t_id = str(interchange_stop.get("id", ""))
    t_type = str(interchange_stop.get("type", "rail"))
    if not leg_stop_id or not t_id:
        return False, 0

    norm_leg = normalise_id(leg_stop_id).lower()
    norm_t = normalise_id(t_id).lower()

    if norm_leg == norm_t:
        return True, 0

    walk = Walking.find_walking_route(leg_stop_type, leg_stop_id, t_type, t_id)
    if not walk:
        walk = Walking.find_walking_route(leg_stop_type, norm_leg, t_type, norm_t)

    if walk and walk.time_needed_minutes <= 5:
        return True, walk.time_needed_minutes

    return False, 0


def _add_synthesized_route(
    synthesized_list: List[Dict[str, Any]],
    seen_signatures: Set[Any],
    legs_data: List[Dict[str, Any]],
    journey: Journey,
    timetable_name: str,
    primary_mode: str,
    active_days: List[str],
) -> bool:
    """Validate, index, format, and add a synthesised route dictionary."""
    if not legs_data:
        return False

    for idx, l_item in enumerate(legs_data):
        l_item["stage_index"] = idx + 1
        l_item["step_index"] = idx + 1

    sig = tuple(
        (
            leg_entry.get("leg_type"),
            leg_entry.get("transport_mode"),
            leg_entry.get("line_name"),
            normalise_id(str(leg_entry.get("from_id", ""))).lower(),
            normalise_id(str(leg_entry.get("to_id", ""))).lower(),
        )
        for leg_entry in legs_data
    )
    if sig in seen_signatures:
        return False
    seen_signatures.add(sig)

    total_dur_mins = sum(
        int(leg_entry.get("duration_minutes", 1) or 1) for leg_entry in legs_data
    )
    transit_count = sum(
        1 for leg_entry in legs_data if leg_entry.get("leg_type") == "transit"
    )
    transfer_count = max(0, transit_count - 1)

    transit_modes = [
        leg_entry.get("transport_mode")
        for leg_entry in legs_data
        if leg_entry.get("leg_type") == "transit" and leg_entry.get("transport_mode")
    ]
    p_mode = (
        "rail"
        if "rail" in transit_modes
        else ("metro" if "metro" in transit_modes else (primary_mode or "bus"))
    )

    summary_parts = []
    for l_item in legs_data:
        if l_item.get("leg_type") == "transit":
            summary_parts.append(
                f"{l_item.get('transport_mode', '').title()} {l_item.get('line_name', '')}"
            )
        else:
            summary_parts.append(f"Walk ({l_item.get('duration_minutes', 1)}m)")
    summary_text = " → ".join(summary_parts)

    route_idx = len(synthesized_list) + 1
    route_name = (
        f"{p_mode.title()} via {timetable_name}"
        if route_idx == 1
        else f"{p_mode.title()} via {timetable_name} {route_idx}"
    )

    synthesized_list.append(
        {
            "journey_id": journey.id,
            "name": route_name,
            "is_preferred": False,
            "is_enabled": True,
            "auto_generated": True,
            "total_duration_est_minutes": total_dur_mins,
            "transfer_count": transfer_count,
            "stages_count": len(legs_data),
            "primary_mode": p_mode,
            "legs": legs_data,
            "active_days": active_days,
            "summary_text": summary_text,
        }
    )
    return True


def _synthesize_custom_timetable_routes(
    journey: Journey,
    parsed_routes: List[Dict[str, Any]],
    active_days: List[str],
    client: Optional[GoogleMapsClient] = None,
    departure_time: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Synthesise hybrid transit corridors combining public routes with custom/manual timetables."""
    try:
        custom_timetables = list(
            Timetable.select().where(
                (Timetable.auto_added == False)  # noqa: E712
                | (Timetable.auto_added == 0)
                | (Timetable.auto_added.is_null(True))
            )
        )
    except Exception as exc:
        logger.debug("Could not query custom timetables: %s", exc)
        return []

    active_tts: List[Timetable] = []
    for tt in custom_timetables:
        day_map = {
            "mon": tt.monday,
            "tue": tt.tuesday,
            "wed": tt.wednesday,
            "thu": tt.thursday,
            "fri": tt.friday,
            "sat": tt.saturday,
            "sun": tt.sunday,
            "bank_holiday": tt.bank_holiday,
        }
        if any(day_map.get(d) for d in active_days):
            active_tts.append(tt)

    if not active_tts:
        return []

    synthesized: List[Dict[str, Any]] = []
    seen_signatures: Set[Any] = set()

    for tt in active_tts:
        content = tt.get_content()
        stops = content.get("stops", [])
        trips = content.get("trips", [])
        if len(stops) < 2 or not trips:
            continue

        s_first = stops[0]
        s_last = stops[-1]
        tt_dur_mins, tt_dist_m = _get_timetable_trip_stats(tt)

        is_last_mile, egress_walk_mins, _ = _is_stop_connected_to_endpoint(
            s_last, journey.to_type, journey.to_id, is_origin=False
        )
        is_first_mile, access_walk_mins, _ = _is_stop_connected_to_endpoint(
            s_first, journey.from_type, journey.from_id, is_origin=True
        )

        # 1. Direct connection (starts near origin AND ends near destination)
        if is_first_mile and is_last_mile:
            legs: List[Dict[str, Any]] = []
            if access_walk_mins > 0:
                legs.append(
                    {
                        "leg_type": "walk",
                        "from_type": journey.from_type,
                        "from_id": journey.from_id,
                        "from_name": journey.from_name,
                        "to_type": s_first.get("type", "bus"),
                        "to_id": s_first["id"],
                        "to_name": s_first.get("name", "Boarding Stop"),
                        "duration_minutes": access_walk_mins,
                        "distance_m": 0,
                    }
                )
            legs.append(
                {
                    "leg_type": "transit",
                    "transport_mode": tt.transport_type or "bus",
                    "line_name": tt.name,
                    "operator_name": None,
                    "from_type": s_first.get("type", "bus"),
                    "from_id": s_first["id"],
                    "from_name": s_first.get("name", journey.from_name),
                    "to_type": s_last.get("type", "bus"),
                    "to_id": s_last["id"],
                    "to_name": s_last.get("name", journey.to_name),
                    "duration_minutes": tt_dur_mins,
                    "distance_m": tt_dist_m,
                    "stops_count": max(1, len(stops) - 1),
                }
            )
            if egress_walk_mins > 0:
                legs.append(
                    {
                        "leg_type": "walk",
                        "from_type": s_last.get("type", "bus"),
                        "from_id": s_last["id"],
                        "from_name": s_last.get("name", "Alighting Stop"),
                        "to_type": journey.to_type,
                        "to_id": journey.to_id,
                        "to_name": journey.to_name,
                        "duration_minutes": egress_walk_mins,
                        "distance_m": 0,
                    }
                )
            _add_synthesized_route(
                synthesized,
                seen_signatures,
                legs,
                journey,
                tt.name,
                tt.transport_type or "bus",
                active_days,
            )
            continue

        # 2. Splicing into existing parsed Google routes
        spliced_for_tt = 0
        if is_last_mile:
            t_stop = s_first
            for r_data in parsed_routes:
                orig_legs = r_data["legs_data"]
                for l_idx, leg in enumerate(orig_legs):
                    matches, xfer_walk = _matches_interchange(
                        leg.get("to_id", ""), leg.get("to_type", ""), t_stop
                    )
                    if matches:
                        new_legs = [
                            dict(leg_part) for leg_part in orig_legs[: l_idx + 1]
                        ]
                        if xfer_walk > 0:
                            new_legs.append(
                                {
                                    "leg_type": "walk",
                                    "from_type": leg.get("to_type", "bus"),
                                    "from_id": leg.get("to_id", ""),
                                    "from_name": leg.get("to_name", "Transfer"),
                                    "to_type": t_stop.get("type", "rail"),
                                    "to_id": t_stop["id"],
                                    "to_name": t_stop.get("name", "Interchange"),
                                    "duration_minutes": xfer_walk,
                                    "distance_m": 0,
                                }
                            )
                        new_legs.append(
                            {
                                "leg_type": "transit",
                                "transport_mode": tt.transport_type or "bus",
                                "line_name": tt.name,
                                "operator_name": None,
                                "from_type": t_stop.get("type", "rail"),
                                "from_id": t_stop["id"],
                                "from_name": t_stop.get("name", "Interchange"),
                                "to_type": s_last.get("type", "ha"),
                                "to_id": s_last["id"],
                                "to_name": s_last.get("name", journey.to_name),
                                "duration_minutes": tt_dur_mins,
                                "distance_m": tt_dist_m,
                                "stops_count": max(1, len(stops) - 1),
                            }
                        )
                        if egress_walk_mins > 0:
                            new_legs.append(
                                {
                                    "leg_type": "walk",
                                    "from_type": s_last.get("type", "ha"),
                                    "from_id": s_last["id"],
                                    "from_name": s_last.get("name", "Alighting Stop"),
                                    "to_type": journey.to_type,
                                    "to_id": journey.to_id,
                                    "to_name": journey.to_name,
                                    "duration_minutes": egress_walk_mins,
                                    "distance_m": 0,
                                }
                            )
                        if _add_synthesized_route(
                            synthesized,
                            seen_signatures,
                            new_legs,
                            journey,
                            tt.name,
                            r_data.get("primary_mode", "rail"),
                            active_days,
                        ):
                            spliced_for_tt += 1
                        break

        elif is_first_mile:
            t_stop = s_last
            for r_data in parsed_routes:
                orig_legs = r_data["legs_data"]
                for l_idx, leg in enumerate(orig_legs):
                    matches, xfer_walk = _matches_interchange(
                        leg.get("from_id", ""),
                        leg.get("from_type", ""),
                        t_stop,
                    )
                    if matches:
                        new_legs = []
                        if access_walk_mins > 0:
                            new_legs.append(
                                {
                                    "leg_type": "walk",
                                    "from_type": journey.from_type,
                                    "from_id": journey.from_id,
                                    "from_name": journey.from_name,
                                    "to_type": s_first.get("type", "ha"),
                                    "to_id": s_first["id"],
                                    "to_name": s_first.get("name", "Boarding Stop"),
                                    "duration_minutes": access_walk_mins,
                                    "distance_m": 0,
                                }
                            )
                        new_legs.append(
                            {
                                "leg_type": "transit",
                                "transport_mode": tt.transport_type or "bus",
                                "line_name": tt.name,
                                "operator_name": None,
                                "from_type": s_first.get("type", "ha"),
                                "from_id": s_first["id"],
                                "from_name": s_first.get("name", journey.from_name),
                                "to_type": t_stop.get("type", "rail"),
                                "to_id": t_stop["id"],
                                "to_name": t_stop.get("name", "Interchange"),
                                "duration_minutes": tt_dur_mins,
                                "distance_m": tt_dist_m,
                                "stops_count": max(1, len(stops) - 1),
                            }
                        )
                        if xfer_walk > 0:
                            new_legs.append(
                                {
                                    "leg_type": "walk",
                                    "from_type": t_stop.get("type", "rail"),
                                    "from_id": t_stop["id"],
                                    "from_name": t_stop.get("name", "Interchange"),
                                    "to_type": leg.get("from_type", "rail"),
                                    "to_id": leg.get("from_id", ""),
                                    "to_name": leg.get("from_name", "Platform"),
                                    "duration_minutes": xfer_walk,
                                    "distance_m": 0,
                                }
                            )
                        new_legs.extend(
                            [dict(leg_part) for leg_part in orig_legs[l_idx:]]
                        )
                        if _add_synthesized_route(
                            synthesized,
                            seen_signatures,
                            new_legs,
                            journey,
                            tt.name,
                            r_data.get("primary_mode", "rail"),
                            active_days,
                        ):
                            spliced_for_tt += 1
                        break

        # 3. Fallback: Query Google Routes for complementary segment if no routes spliced
        if spliced_for_tt == 0 and client is not None:
            try:
                if is_last_mile:
                    t_lat, t_lng, t_name = resolve_endpoint_coordinates(
                        s_first.get("type", "rail"), s_first["id"]
                    )
                    o_lat, o_lng, o_name = resolve_endpoint_coordinates(
                        journey.from_type, journey.from_id
                    )
                    if t_lat and t_lng and o_lat and o_lng:
                        sub_resp = client.compute_transit_routes(
                            origin=(o_lat, o_lng),
                            destination=(t_lat, t_lng),
                            departure_time=departure_time,
                            compute_alternative_routes=True,
                        )
                        for sub_r in sub_resp.get("routes", []):
                            sub_legs, _, sub_modes, _, _ = _parse_google_route_to_legs(
                                sub_r,
                                journey.from_type,
                                journey.from_id,
                                o_name or journey.from_name,
                                s_first.get("type", "rail"),
                                s_first["id"],
                                t_name or s_first.get("name", "Interchange"),
                            )
                            sub_legs.append(
                                {
                                    "leg_type": "transit",
                                    "transport_mode": tt.transport_type or "bus",
                                    "line_name": tt.name,
                                    "operator_name": None,
                                    "from_type": s_first.get("type", "rail"),
                                    "from_id": s_first["id"],
                                    "from_name": s_first.get("name", "Interchange"),
                                    "to_type": s_last.get("type", "ha"),
                                    "to_id": s_last["id"],
                                    "to_name": s_last.get("name", journey.to_name),
                                    "duration_minutes": tt_dur_mins,
                                    "distance_m": tt_dist_m,
                                    "stops_count": max(1, len(stops) - 1),
                                }
                            )
                            if egress_walk_mins > 0:
                                sub_legs.append(
                                    {
                                        "leg_type": "walk",
                                        "from_type": s_last.get("type", "ha"),
                                        "from_id": s_last["id"],
                                        "from_name": s_last.get(
                                            "name", "Alighting Stop"
                                        ),
                                        "to_type": journey.to_type,
                                        "to_id": journey.to_id,
                                        "to_name": journey.to_name,
                                        "duration_minutes": egress_walk_mins,
                                        "distance_m": 0,
                                    }
                                )
                            pm = sub_modes[0] if sub_modes else "rail"
                            _add_synthesized_route(
                                synthesized,
                                seen_signatures,
                                sub_legs,
                                journey,
                                tt.name,
                                pm,
                                active_days,
                            )
                elif is_first_mile:
                    t_lat, t_lng, t_name = resolve_endpoint_coordinates(
                        s_last.get("type", "rail"), s_last["id"]
                    )
                    d_lat, d_lng, d_name = resolve_endpoint_coordinates(
                        journey.to_type, journey.to_id
                    )
                    if t_lat and t_lng and d_lat and d_lng:
                        sub_resp = client.compute_transit_routes(
                            origin=(t_lat, t_lng),
                            destination=(d_lat, d_lng),
                            departure_time=departure_time,
                            compute_alternative_routes=True,
                        )
                        for sub_r in sub_resp.get("routes", []):
                            sub_legs, _, sub_modes, _, _ = _parse_google_route_to_legs(
                                sub_r,
                                s_last.get("type", "rail"),
                                s_last["id"],
                                t_name or s_last.get("name", "Interchange"),
                                journey.to_type,
                                journey.to_id,
                                d_name or journey.to_name,
                            )
                            comp_legs = []
                            if access_walk_mins > 0:
                                comp_legs.append(
                                    {
                                        "leg_type": "walk",
                                        "from_type": journey.from_type,
                                        "from_id": journey.from_id,
                                        "from_name": journey.from_name,
                                        "to_type": s_first.get("type", "ha"),
                                        "to_id": s_first["id"],
                                        "to_name": s_first.get("name", "Boarding Stop"),
                                        "duration_minutes": access_walk_mins,
                                        "distance_m": 0,
                                    }
                                )
                            comp_legs.append(
                                {
                                    "leg_type": "transit",
                                    "transport_mode": tt.transport_type or "bus",
                                    "line_name": tt.name,
                                    "operator_name": None,
                                    "from_type": s_first.get("type", "ha"),
                                    "from_id": s_first["id"],
                                    "from_name": s_first.get("name", journey.from_name),
                                    "to_type": s_last.get("type", "rail"),
                                    "to_id": s_last["id"],
                                    "to_name": s_last.get("name", "Interchange"),
                                    "duration_minutes": tt_dur_mins,
                                    "distance_m": tt_dist_m,
                                    "stops_count": max(1, len(stops) - 1),
                                }
                            )
                            comp_legs.extend(sub_legs)
                            pm = sub_modes[0] if sub_modes else "rail"
                            _add_synthesized_route(
                                synthesized,
                                seen_signatures,
                                comp_legs,
                                journey,
                                tt.name,
                                pm,
                                active_days,
                            )
            except Exception as exc:
                logger.debug(
                    "Could not query complementary segment for custom timetable: %s",
                    exc,
                )

    return synthesized


class CorridorLearner:
    """Service to discover, audit, parse, and persist transit corridors for journeys."""

    def __init__(self, client: Optional[GoogleMapsClient] = None) -> None:
        self._client = client

    def get_client(self) -> GoogleMapsClient:
        """Lazily retrieve or initialise GoogleMapsClient."""
        if self._client is not None:
            return self._client
        self._client = GoogleMapsClient.from_settings()
        return self._client

    def discover_and_persist_corridors(
        self,
        journey: Journey,
        query_type: str = "initial_discovery",
        trigger_reason: str = "automated_journey_creation",
        departure_time: Optional[Any] = None,
        arrival_time: Optional[Any] = None,
        replace_existing: bool = True,
    ) -> List[JourneyRoute]:
        """Discover transit routes via Google Routes API, audit query, and persist templates.

        Args:
            journey: Journey model to discover routes for.
            query_type: Classification of the routing query.
            trigger_reason: Explanatory trigger reason for the audit log.
            departure_time: Optional departure datetime or RFC3339 string.
            arrival_time: Optional arrival datetime or RFC3339 string.
            replace_existing: Whether to remove previously auto-generated templates.

        Returns:
            List of persisted JourneyRoute instances.
        """
        origin_lat, origin_lng, origin_name = resolve_endpoint_coordinates(
            journey.from_type, journey.from_id
        )
        dest_lat, dest_lng, dest_name = resolve_endpoint_coordinates(
            journey.to_type, journey.to_id
        )

        if replace_existing:
            JourneyRoute.delete().where(
                (JourneyRoute.journey_id == journey.id)
                & (JourneyRoute.auto_generated == True)  # noqa: E712
            ).execute()

        persisted_routes: List[JourneyRoute] = []
        parsed_summary: List[Dict[str, Any]] = []

        active_days = ["mon", "tue", "wed", "thu", "fri"]
        time_windows = journey.get_time_settings()
        if time_windows and time_windows[0].get("days"):
            active_days = time_windows[0]["days"]

        # Check for direct walking link between endpoints
        direct_walk = Walking.find_walking_route(
            journey.from_type, journey.from_id, journey.to_type, journey.to_id
        )
        if direct_walk:
            walk_min = direct_walk.time_needed_minutes
            route_name = f"Direct Walk ({walk_min}m)"
            legs_data = [
                {
                    "stage_index": 1,
                    "step_index": 1,
                    "leg_type": "walk",
                    "from_type": journey.from_type,
                    "from_id": journey.from_id,
                    "from_name": journey.from_name,
                    "to_type": journey.to_type,
                    "to_id": journey.to_id,
                    "to_name": journey.to_name,
                    "duration_minutes": walk_min,
                    "distance_m": 0,
                }
            ]
            saved_walk = JourneyRoute.create(
                journey_id=journey.id,
                name=route_name,
                is_preferred=True,
                is_enabled=True,
                auto_generated=True,
                total_duration_est_minutes=walk_min,
                transfer_count=0,
                stages_count=1,
                primary_mode="walk",
                legs=legs_data,
                active_days=active_days,
                summary_text=f"Walk ({walk_min}m)",
            )
            persisted_routes.append(saved_walk)
            parsed_summary.append(
                {
                    "route_id": saved_walk.id,
                    "name": route_name,
                    "duration_minutes": walk_min,
                    "primary_mode": "walk",
                    "transfer_count": 0,
                }
            )

        if origin_lat is None or origin_lng is None:
            if persisted_routes:
                journey.set_calculated_routes([r.to_dict() for r in persisted_routes])
                journey.save()
                return persisted_routes
            logger.warning(
                "Cannot compute routes for journey %d: origin coordinates unresolved.",
                journey.id,
            )
            return []
        if dest_lat is None or dest_lng is None:
            if persisted_routes:
                journey.set_calculated_routes([r.to_dict() for r in persisted_routes])
                journey.save()
                return persisted_routes
            logger.warning(
                "Cannot compute routes for journey %d: destination coordinates unresolved.",
                journey.id,
            )
            return []

        client = self.get_client()
        target_dep = departure_time
        target_arr = arrival_time
        if target_dep is None and target_arr is None:
            target_dep, target_arr = resolve_target_commute_datetime(journey)

        try:
            raw_response = client.compute_transit_routes(
                origin=(origin_lat, origin_lng),
                destination=(dest_lat, dest_lng),
                departure_time=target_dep,
                arrival_time=target_arr,
                compute_alternative_routes=True,
            )
        except DataSourceConfigError:
            logger.info(
                "Google Maps API key not configured. Skipping corridor discovery."
            )
            if persisted_routes:
                journey.set_calculated_routes([r.to_dict() for r in persisted_routes])
                journey.save()
                return persisted_routes
            return []
        except Exception as exc:
            logger.warning(
                "Failed to compute transit routes via Google Routes API for journey %d: %s",
                journey.id,
                exc,
            )
            if persisted_routes:
                journey.set_calculated_routes([r.to_dict() for r in persisted_routes])
                journey.save()
                return persisted_routes
            return []

        routes = raw_response.get("routes", [])
        if not routes:
            logger.info(
                "No transit routes returned by Google Routes API for journey %d.",
                journey.id,
            )
            RouteQueryLog.create(
                journey_id=journey.id,
                query_type=query_type,
                trigger_reason=trigger_reason,
                origin_lat=origin_lat,
                origin_lng=origin_lng,
                dest_lat=dest_lat,
                dest_lng=dest_lng,
                departure_time=(
                    str(target_dep)
                    if target_dep
                    else (str(target_arr) if target_arr else None)
                ),
                raw_response=raw_response,
                parsed_summary=parsed_summary,
                selected_route_id=persisted_routes[0].id if persisted_routes else None,
            )
            if persisted_routes:
                journey.set_calculated_routes([r.to_dict() for r in persisted_routes])
                journey.save()
                return persisted_routes
            return []

        # Audit log creation
        query_log = RouteQueryLog.create(
            journey_id=journey.id,
            query_type=query_type,
            trigger_reason=trigger_reason,
            origin_lat=origin_lat,
            origin_lng=origin_lng,
            dest_lat=dest_lat,
            dest_lng=dest_lng,
            departure_time=(
                str(target_dep)
                if target_dep
                else (str(target_arr) if target_arr else None)
            ),
            raw_response=raw_response,
            parsed_summary=[],
        )

        if routes and persisted_routes:
            for r in persisted_routes:
                r.is_preferred = False
                r.save()

        # Parse Google Routes
        parsed_google_routes: List[Dict[str, Any]] = []
        for route_idx, route in enumerate(routes):
            (
                legs_data,
                total_duration_mins,
                transit_modes_used,
                transit_count,
                route_desc,
            ) = _parse_google_route_to_legs(
                route,
                journey.from_type,
                journey.from_id,
                origin_name or journey.from_name,
                journey.to_type,
                journey.to_id,
                dest_name or journey.to_name,
            )
            primary_mode = transit_modes_used[0] if transit_modes_used else "bus"
            transfer_count = max(0, transit_count - 1)
            route_name = route_desc or f"{primary_mode.title()} Route {route_idx + 1}"

            summary_parts = []
            for l_item in legs_data:
                if l_item.get("leg_type") == "transit":
                    summary_parts.append(
                        f"{l_item.get('transport_mode', '').title()} {l_item.get('line_name', '')}"
                    )
                else:
                    summary_parts.append(f"Walk ({l_item.get('duration_minutes', 1)}m)")
            summary_text = " → ".join(summary_parts)

            parsed_google_routes.append(
                {
                    "route_desc": route_desc,
                    "legs_data": legs_data,
                    "total_duration_mins": total_duration_mins,
                    "transfer_count": transfer_count,
                    "primary_mode": primary_mode,
                    "route_name": route_name,
                    "summary_text": summary_text,
                }
            )

        # Synthesise custom timetable corridors (e.g. employer shuttles)
        synthesized_routes = _synthesize_custom_timetable_routes(
            journey,
            parsed_google_routes,
            active_days,
            client=client,
            departure_time=departure_time,
        )

        routes_to_save: List[Dict[str, Any]] = []
        if synthesized_routes:
            synthesized_routes.sort(key=lambda r: r["total_duration_est_minutes"])
            synthesized_routes[0]["is_preferred"] = True
            for r in synthesized_routes[1:]:
                r["is_preferred"] = False
            routes_to_save.extend(synthesized_routes)

            for g_route in parsed_google_routes:
                routes_to_save.append(
                    {
                        "journey_id": journey.id,
                        "name": g_route["route_name"],
                        "is_preferred": False,
                        "is_enabled": True,
                        "auto_generated": True,
                        "total_duration_est_minutes": g_route["total_duration_mins"],
                        "transfer_count": g_route["transfer_count"],
                        "stages_count": len(g_route["legs_data"]),
                        "primary_mode": g_route["primary_mode"],
                        "legs": g_route["legs_data"],
                        "active_days": active_days,
                        "summary_text": g_route["summary_text"],
                    }
                )
        else:
            for idx, g_route in enumerate(parsed_google_routes):
                routes_to_save.append(
                    {
                        "journey_id": journey.id,
                        "name": g_route["route_name"],
                        "is_preferred": (
                            idx == 0
                            and not any(r.is_preferred for r in persisted_routes)
                        ),
                        "is_enabled": True,
                        "auto_generated": True,
                        "total_duration_est_minutes": g_route["total_duration_mins"],
                        "transfer_count": g_route["transfer_count"],
                        "stages_count": len(g_route["legs_data"]),
                        "primary_mode": g_route["primary_mode"],
                        "legs": g_route["legs_data"],
                        "active_days": active_days,
                        "summary_text": g_route["summary_text"],
                    }
                )

        for r_dict in routes_to_save:
            saved_route = JourneyRoute.create(**r_dict)
            persisted_routes.append(saved_route)
            parsed_summary.append(
                {
                    "route_id": saved_route.id,
                    "name": saved_route.name,
                    "duration_minutes": saved_route.total_duration_est_minutes,
                    "primary_mode": saved_route.primary_mode,
                    "transfer_count": saved_route.transfer_count,
                }
            )

        # Update query audit log with parsed summary and primary route ID
        query_log.parsed_summary = parsed_summary
        if persisted_routes:
            query_log.selected_route_id = persisted_routes[0].id
        query_log.save()

        # Update legacy calculated_routes on Journey for backward compatibility
        journey.set_calculated_routes([r.to_dict() for r in persisted_routes])
        journey.save()

        logger.info(
            "Successfully discovered and persisted %d route template(s) for journey %d ('%s').",
            len(persisted_routes),
            journey.id,
            journey.name,
        )
        return persisted_routes


__all__ = [
    "CorridorLearner",
    "map_vehicle_type",
    "parse_duration_seconds",
    "resolve_or_create_stop",
]
