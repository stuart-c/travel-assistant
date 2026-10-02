"""Dynamic transit route planner powered by Google Routes API v2, custom timetables, and live feeds."""

from __future__ import annotations

import datetime
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.datasources.bus_live import BodsLiveClient
from app.datasources.google_maps import GoogleMapsClient
from app.datasources.train_live import TrainLiveClient
from app.models.journey import Journey
from app.models.timetable import Timetable
from app.models.transit import Stop
from app.services.planner.models import (
    ItineraryEndpoint,
    ItineraryLeg,
    ScheduledItinerary,
)
from app.services.planner.transfers import normalise_id
from app.utils.geo import haversine_distance_m, resolve_endpoint_coordinates
from app.utils.transit_time import (
    format_minutes_to_time,
    get_day_code,
    parse_duration_seconds,
    parse_time_to_minutes,
)

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
    """Determine the optimal target departure or arrival datetime for transit routing."""
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

    # Fallback to next weekday morning commute (08:30)
    for offset in range(0, 8):
        target_date = reference_dt.date() + datetime.timedelta(days=offset)
        if target_date.weekday() < 5:  # Mon-Fri
            target_dt = datetime.datetime.combine(target_date, datetime.time(8, 30))
            if offset == 0 and target_dt <= reference_dt:
                continue
            return target_dt, None

    return reference_dt, None


def map_vehicle_type(vehicle_type: Optional[str]) -> str:
    """Map Google Routes vehicle type to internal transit mode."""
    if not vehicle_type:
        return "rail"
    vt = vehicle_type.upper()
    if any(w in vt for w in ("BUS", "INTERCITY_BUS", "TROLLEYBUS")):
        return "bus"
    if any(w in vt for w in ("SUBWAY", "METRO", "UNDERGROUND")):
        return "subway"
    if any(w in vt for w in ("TRAM", "LIGHT_RAIL")):
        return "tram"
    return "rail"


def resolve_or_create_stop(
    name: str,
    lat: Optional[float],
    lng: Optional[float],
    stop_type: str = "rail",
) -> Tuple[str, str, str]:
    """Resolve an existing database Stop or return synthetic endpoint identifiers."""
    clean_name = (name or "Transit Stop").strip()
    norm_type = "bus" if stop_type == "bus" else "rail"

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

    slug = re.sub(r"[^a-z0-9]+", "_", clean_name.lower()).strip("_")
    coord_part = f"{round(lat or 0.0, 4)}_{round(lng or 0.0, 4)}".replace(".", "_")
    atco_code = f"google:{slug[:30]}_{coord_part}"

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
            name=clean_name,
            stop_type=norm_type,
            latitude=lat,
            longitude=lng,
        )
        return new_stop.stop_type, new_stop.atco_code, new_stop.name
    except Exception as exc:
        logger.debug("Could not create Stop for '%s': %s", clean_name, exc)
        return norm_type, atco_code, clean_name


def _rfc3339_to_hhmm(rfc_str: Optional[str]) -> Optional[str]:
    """Extract HH:MM from an RFC3339 timestamp string."""
    if not rfc_str or not isinstance(rfc_str, str):
        return None
    # Look for THH:MM
    match = re.search(r"T(\d{2}):(\d{2})", rfc_str)
    if match:
        return f"{match.group(1)}:{match.group(2)}"
    return None


class DynamicRoutePlanner:
    """Calculates live transit itineraries dynamically using Google Routes API and custom timetables."""

    def __init__(
        self,
        google_client: Optional[GoogleMapsClient] = None,
        train_live_client: Optional[TrainLiveClient] = None,
        bus_live_client: Optional[BodsLiveClient] = None,
    ) -> None:
        self.google_client = google_client or GoogleMapsClient.from_settings()
        self.train_live_client = train_live_client or TrainLiveClient.from_settings()
        self.bus_live_client = bus_live_client or BodsLiveClient.from_settings()

    def plan_transit(
        self,
        journey: Journey,
        departure_time: Optional[datetime.datetime] = None,
        arrival_time: Optional[datetime.datetime] = None,
        current_lat: Optional[float] = None,
        current_lon: Optional[float] = None,
        current_name: Optional[str] = None,
        enrich_live: bool = True,
        max_results: int = 5,
    ) -> List[ScheduledItinerary]:
        """Compute live transit itineraries for a Journey.

        Args:
            journey: Configured Journey model.
            departure_time: Departure datetime.
            arrival_time: Target arrival datetime (mutually exclusive with departure_time).
            current_lat: Optional live GPS latitude (for en-route rerouting).
            current_lon: Optional live GPS longitude (for en-route rerouting).
            current_name: Optional label of the current departure location.
            enrich_live: Whether to probe Darwin/BODS for live platforms and delay minutes.
            max_results: Maximum number of candidate itineraries to return.

        Returns:
            List of ScheduledItinerary objects ranked by departure timing and duration.
        """
        now = datetime.datetime.now()
        effective_dep = departure_time
        effective_arr = arrival_time

        # If neither departure nor arrival is provided, determine from journey time_settings or default to now
        if not effective_dep and not effective_arr:
            effective_dep = self._resolve_journey_default_time(journey, now)

        # Check for first-mile or last-mile custom timetables (e.g. campus shuttle bus)
        custom_shuttle = self._find_custom_timetable_for_journey(journey)

        if custom_shuttle and current_lat is None:
            itineraries = self._plan_hybrid_custom_shuttle(
                journey=journey,
                shuttle_tt=custom_shuttle,
                dep_dt=effective_dep,
                arr_dt=effective_arr,
            )
            if itineraries:
                if enrich_live:
                    for itin in itineraries:
                        self.enrich_itinerary_live(itin)
                return itineraries[:max_results]

        # Direct Google Routes calculation
        orig_lat, orig_lng, orig_name = (
            (current_lat, current_lon, current_name or "Current Location")
            if (current_lat is not None and current_lon is not None)
            else resolve_endpoint_coordinates(journey.from_type, journey.from_id)
        )
        dest_lat, dest_lng, dest_name = resolve_endpoint_coordinates(
            journey.to_type, journey.to_id
        )

        if not orig_lat or not orig_lng or not dest_lat or not dest_lng:
            logger.warning(
                "Could not resolve coordinates for journey %d (%s -> %s)",
                journey.id,
                journey.from_id,
                journey.to_id,
            )
            return []

        itineraries: List[ScheduledItinerary] = []
        try:
            resp = self.google_client.compute_transit_routes(
                origin=(orig_lat, orig_lng),
                destination=(dest_lat, dest_lng),
                departure_time=effective_dep,
                arrival_time=effective_arr,
                compute_alternative_routes=True,
            )
            for r in resp.get("routes", []):
                itin = self._parse_google_route_to_itinerary(
                    route=r,
                    from_id=(
                        journey.from_id if current_lat is None else "current_location"
                    ),
                    from_name=orig_name or journey.from_name,
                    to_id=journey.to_id,
                    to_name=dest_name or journey.to_name,
                    reference_time=effective_dep or now,
                )
                if itin:
                    itineraries.append(itin)
        except Exception as exc:
            logger.debug(
                "Google Routes API call failed or unavailable for journey %d: %s",
                journey.id,
                exc,
            )

        # Fallback to local synthetic RAPTOR if Google Routes is unavailable (e.g. offline unit tests)
        if not itineraries and current_lat is None:
            try:
                from app.services.planner.raptor import plan_journey

                ref_time = effective_dep or now
                t_str = ref_time.strftime("%H:%M")
                day_code = get_day_code(ref_time)
                raptor_plans = plan_journey(
                    from_type=journey.from_type,
                    from_id=journey.from_id,
                    to_type=journey.to_type,
                    to_id=journey.to_id,
                    timing_mode="depart",
                    time_str=t_str,
                    days_of_week=[day_code],
                    target_date=ref_time.date(),
                    max_itineraries=max_results,
                )
                if raptor_plans:
                    itineraries.extend(raptor_plans)
            except Exception as raptor_exc:
                logger.debug(
                    "RAPTOR fallback in DynamicRoutePlanner skipped: %s", raptor_exc
                )

        if enrich_live:
            for itin in itineraries:
                self.enrich_itinerary_live(itin)

        return itineraries[:max_results]

    def _resolve_journey_default_time(
        self, journey: Journey, now_dt: datetime.datetime
    ) -> datetime.datetime:
        """Derive the next scheduled departure time from journey time settings."""
        settings = journey.get_time_settings()
        if not settings:
            return now_dt

        current_min = now_dt.hour * 60 + now_dt.minute
        today_code = get_day_code(now_dt)

        for ts in settings:
            days = [
                d.lower()
                for d in (
                    ts.get("days", [])
                    if isinstance(ts, dict)
                    else getattr(ts, "days", [])
                )
            ]
            if today_code in days:
                s_str = (
                    ts.get("start_time")
                    if isinstance(ts, dict)
                    else getattr(ts, "start_time", None)
                )
                e_str = (
                    ts.get("end_time")
                    if isinstance(ts, dict)
                    else getattr(ts, "end_time", None)
                )
                s_min = parse_time_to_minutes(s_str)
                e_min = parse_time_to_minutes(e_str)
                if s_min is not None:
                    # If we are before or inside the window
                    if current_min <= (e_min if e_min is not None else s_min + 60):
                        target_min = max(current_min, s_min)
                        return now_dt.replace(
                            hour=target_min // 60,
                            minute=target_min % 60,
                            second=0,
                            microsecond=0,
                        )

        # Fallback to current time
        return now_dt

    def _find_custom_timetable_for_journey(
        self, journey: Journey
    ) -> Optional[Dict[str, Any]]:
        """Identify if a private custom timetable links directly to journey origin or destination."""
        custom_timetables = list(
            Timetable.select().where(Timetable.auto_added == False)  # noqa: E712
        )
        if not custom_timetables:
            return None

        norm_from = normalise_id(journey.from_id)
        norm_to = normalise_id(journey.to_id)

        for tt in custom_timetables:
            content = tt.get_content()
            stops = content.get("stops", [])
            if len(stops) < 2:
                continue

            first_id = normalise_id(stops[0].get("id", ""))
            last_id = normalise_id(stops[-1].get("id", ""))

            # First-mile match: shuttle starts at journey origin
            if first_id == norm_from:
                return {
                    "timetable": tt,
                    "direction": "first_mile",
                    "origin_stop": stops[0],
                    "interchange_stop": stops[-1],
                }

            # Last-mile match: shuttle ends at journey destination
            if last_id == norm_to:
                return {
                    "timetable": tt,
                    "direction": "last_mile",
                    "interchange_stop": stops[0],
                    "dest_stop": stops[-1],
                }

        return None

    def _plan_hybrid_custom_shuttle(
        self,
        journey: Journey,
        shuttle_tt: Dict[str, Any],
        dep_dt: Optional[datetime.datetime],
        arr_dt: Optional[datetime.datetime],
    ) -> List[ScheduledItinerary]:
        """Synthesise a multi-modal route combining custom shuttle bus and Google public transit."""
        tt: Timetable = shuttle_tt["timetable"]
        direction = shuttle_tt["direction"]
        content = tt.get_content()
        trips = content.get("trips", [])
        stops = content.get("stops", [])
        if not trips:
            return []

        now = datetime.datetime.now()
        target_dt = dep_dt or now
        target_min = target_dt.hour * 60 + target_dt.minute

        itineraries: List[ScheduledItinerary] = []

        if direction == "first_mile":
            # 1. Find suitable shuttle trip departing at or after target_min
            valid_trips = []
            for t in trips:
                times = t.get("times", [])
                if len(times) >= 2:
                    t_dep = times[0]
                    t_arr = times[-1]
                    dep_m = parse_time_to_minutes(
                        t_dep.get("dep") if isinstance(t_dep, dict) else t_dep
                    )
                    arr_m = parse_time_to_minutes(
                        t_arr.get("arr") if isinstance(t_arr, dict) else t_arr
                    )
                    if dep_m is not None and dep_m >= target_min - 5:
                        valid_trips.append((dep_m, arr_m, t, t_dep, t_arr))

            valid_trips.sort(key=lambda x: x[0])
            if not valid_trips:
                return []

            best_trip = valid_trips[0]
            shuttle_dep_m, shuttle_arr_m, trip_obj, t_dep_raw, t_arr_raw = best_trip
            shuttle_dep_str = (
                t_dep_raw.get("dep") if isinstance(t_dep_raw, dict) else t_dep_raw
            )
            shuttle_arr_str = (
                t_arr_raw.get("arr") if isinstance(t_arr_raw, dict) else t_arr_raw
            )
            shuttle_dur_mins = max(1, (shuttle_arr_m or 0) - shuttle_dep_m)

            # Build Shuttle Leg
            shuttle_leg = ItineraryLeg(
                leg_index=1,
                mode="bus",
                origin=ItineraryEndpoint(
                    id=stops[0].get("id", journey.from_id),
                    name=stops[0].get("name", journey.from_name),
                    platform="Shuttle Bay",
                ),
                destination=ItineraryEndpoint(
                    id=stops[-1].get("id", "interchange"),
                    name=stops[-1].get("name", "Rail Station"),
                ),
                dep_time=str(shuttle_dep_str),
                arr_time=str(shuttle_arr_str),
                duration_minutes=shuttle_dur_mins,
                line=tt.name,
                operator=trip_obj.get("operator") or "Campus Shuttle",
                headsign=stops[-1].get("name", "Station"),
                stops_count=len(stops),
            )

            # 2. Query Google Routes from the shuttle drop-off station to journey destination
            interchange = shuttle_tt["interchange_stop"]
            i_lat, i_lng, i_name = resolve_endpoint_coordinates(
                interchange.get("type", "rail"), interchange.get("id")
            )
            d_lat, d_lng, d_name = resolve_endpoint_coordinates(
                journey.to_type, journey.to_id
            )

            if not i_lat or not i_lng or not d_lat or not d_lng:
                return []

            shuttle_arr_dt = target_dt.replace(
                hour=(shuttle_arr_m or 0) // 60,
                minute=(shuttle_arr_m or 0) % 60,
                second=0,
                microsecond=0,
            )

            try:
                sub_resp = self.google_client.compute_transit_routes(
                    origin=(i_lat, i_lng),
                    destination=(d_lat, d_lng),
                    departure_time=shuttle_arr_dt,
                    compute_alternative_routes=True,
                )
            except Exception as exc:
                logger.error("Failed Google transit query for shuttle link: %s", exc)
                return []

            for r in sub_resp.get("routes", []):
                sub_itin = self._parse_google_route_to_itinerary(
                    route=r,
                    from_id=interchange.get("id", "interchange"),
                    from_name=i_name or interchange.get("name", "Station"),
                    to_id=journey.to_id,
                    to_name=d_name or journey.to_name,
                    reference_time=shuttle_arr_dt,
                )
                if sub_itin and sub_itin.legs:
                    # Prepend shuttle leg
                    combined_legs = [shuttle_leg]
                    for idx, leg in enumerate(sub_itin.legs, start=2):
                        leg.leg_index = idx
                        combined_legs.append(leg)

                    arr_min = parse_time_to_minutes(combined_legs[-1].arr_time) or 0
                    total_dur = max(1, arr_min - shuttle_dep_m)

                    combined_itin = ScheduledItinerary(
                        departure_time=str(shuttle_dep_str),
                        arrival_time=combined_legs[-1].arr_time,
                        total_duration_minutes=total_dur,
                        transfers_count=len(
                            [lg for lg in combined_legs if lg.mode != "walk"]
                        )
                        - 1,
                        robustness_score="high",
                        legs=combined_legs,
                    )
                    itineraries.append(combined_itin)

        elif direction == "last_mile":
            # 1. Query Google Routes from journey origin to the shuttle interchange station
            interchange = shuttle_tt["interchange_stop"]
            o_lat, o_lng, o_name = resolve_endpoint_coordinates(
                journey.from_type, journey.from_id
            )
            i_lat, i_lng, i_name = resolve_endpoint_coordinates(
                interchange.get("type", "rail"), interchange.get("id")
            )
            if not i_lat or not i_lng:
                i_lat = interchange.get("latitude")
                i_lng = interchange.get("longitude")

            if not o_lat or not o_lng or not i_lat or not i_lng:
                return []

            try:
                sub_resp = self.google_client.compute_transit_routes(
                    origin=(o_lat, o_lng),
                    destination=(i_lat, i_lng),
                    departure_time=target_dt,
                    compute_alternative_routes=True,
                )
            except Exception as exc:
                logger.error("Failed Google transit query for shuttle link: %s", exc)
                return []

            for r in sub_resp.get("routes", []):
                sub_itin = self._parse_google_route_to_itinerary(
                    route=r,
                    from_id=journey.from_id,
                    from_name=o_name or journey.from_name,
                    to_id=interchange.get("id", "interchange"),
                    to_name=i_name or interchange.get("name", "Station"),
                    reference_time=target_dt,
                )
                if not sub_itin or not sub_itin.legs:
                    continue

                transit_arr_m = (
                    parse_time_to_minutes(sub_itin.arrival_time) or target_min
                )

                # 2. Find earliest shuttle trip departing at or after public transit arrival
                valid_trips = []
                for t in trips:
                    times = t.get("times", [])
                    if len(times) >= 2:
                        t_dep = times[0]
                        t_arr = times[-1]
                        dep_m = parse_time_to_minutes(
                            t_dep.get("dep") if isinstance(t_dep, dict) else t_dep
                        )
                        arr_m = parse_time_to_minutes(
                            t_arr.get("arr") if isinstance(t_arr, dict) else t_arr
                        )
                        if dep_m is not None and dep_m >= transit_arr_m:
                            valid_trips.append((dep_m, arr_m, t, t_dep, t_arr))

                valid_trips.sort(key=lambda x: x[0])
                if not valid_trips:
                    continue

                best_trip = valid_trips[0]
                shuttle_dep_m, shuttle_arr_m, trip_obj, t_dep_raw, t_arr_raw = best_trip
                shuttle_dep_str = (
                    t_dep_raw.get("dep") if isinstance(t_dep_raw, dict) else t_dep_raw
                )
                shuttle_arr_str = (
                    t_arr_raw.get("arr") if isinstance(t_arr_raw, dict) else t_arr_raw
                )
                shuttle_dur_mins = max(1, (shuttle_arr_m or 0) - shuttle_dep_m)

                # Build Shuttle Leg
                shuttle_leg = ItineraryLeg(
                    leg_index=len(sub_itin.legs) + 1,
                    mode="bus",
                    origin=ItineraryEndpoint(
                        id=stops[0].get("id", "interchange"),
                        name=stops[0].get("name", i_name or "Station"),
                        platform="Shuttle Bay",
                    ),
                    destination=ItineraryEndpoint(
                        id=stops[-1].get("id", journey.to_id),
                        name=stops[-1].get("name", journey.to_name),
                    ),
                    dep_time=str(shuttle_dep_str),
                    arr_time=str(shuttle_arr_str),
                    duration_minutes=shuttle_dur_mins,
                    line=tt.name,
                    operator=trip_obj.get("operator") or "Campus Shuttle",
                    headsign=stops[-1].get("name", journey.to_name),
                    stops_count=len(stops),
                )

                combined_legs = list(sub_itin.legs) + [shuttle_leg]
                dep_m = parse_time_to_minutes(combined_legs[0].dep_time) or target_min
                arr_m = parse_time_to_minutes(shuttle_leg.arr_time) or shuttle_dep_m
                total_dur = max(1, arr_m - dep_m)

                combined_itin = ScheduledItinerary(
                    departure_time=combined_legs[0].dep_time,
                    arrival_time=shuttle_leg.arr_time,
                    total_duration_minutes=total_dur,
                    transfers_count=len(
                        [lg for lg in combined_legs if lg.mode != "walk"]
                    )
                    - 1,
                    robustness_score="high",
                    legs=combined_legs,
                )
                itineraries.append(combined_itin)

        return itineraries

    def _parse_google_route_to_itinerary(
        self,
        route: Dict[str, Any],
        from_id: str,
        from_name: str,
        to_id: str,
        to_name: str,
        reference_time: datetime.datetime,
    ) -> Optional[ScheduledItinerary]:
        """Convert a Google Routes API v2 route JSON into a ScheduledItinerary."""
        route_legs = route.get("legs", [])
        if not route_legs:
            return None

        total_duration_sec = parse_duration_seconds(route.get("duration"))
        total_duration_mins = max(1, total_duration_sec // 60)

        raw_steps: List[Dict[str, Any]] = []
        for r_leg in route_legs:
            raw_steps.extend(r_leg.get("steps", []))

        # Partition into contiguous walk and transit segments
        segments: List[Dict[str, Any]] = []
        walk_acc: List[Dict[str, Any]] = []

        for step in raw_steps:
            tm = str(step.get("travelMode", "")).upper()
            if tm == "TRANSIT":
                if walk_acc:
                    segments.append({"type": "walk", "steps": walk_acc})
                    walk_acc = []
                segments.append({"type": "transit", "step": step})
            else:
                walk_acc.append(step)

        if walk_acc:
            segments.append({"type": "walk", "steps": walk_acc})

        legs: List[ItineraryLeg] = []
        current_time_min = reference_time.hour * 60 + reference_time.minute
        curr_endpoint_id = from_id
        curr_endpoint_name = from_name

        for seg_idx, seg in enumerate(segments, start=1):
            if seg["type"] == "transit":
                step = seg["step"]
                td = step.get("transitDetails", {})
                sd = td.get("stopDetails", {})
                tl = td.get("transitLine", {})

                dep_stop = sd.get("departureStop", {})
                arr_stop = sd.get("arrivalStop", {})

                dep_time_raw = _rfc3339_to_hhmm(sd.get("departureTime"))
                arr_time_raw = _rfc3339_to_hhmm(sd.get("arrivalTime"))

                step_dur_sec = parse_duration_seconds(step.get("staticDuration"))
                dur_mins = max(1, step_dur_sec // 60) if step_dur_sec else 1

                dep_min = (
                    parse_time_to_minutes(dep_time_raw)
                    if dep_time_raw
                    else current_time_min
                )
                arr_min = (
                    parse_time_to_minutes(arr_time_raw)
                    if arr_time_raw
                    else (dep_min + dur_mins)
                )

                dep_time_str = format_minutes_to_time(dep_min)
                arr_time_str = format_minutes_to_time(arr_min)
                current_time_min = arr_min

                v_type = tl.get("vehicle", {}).get("type")
                mode = map_vehicle_type(v_type)
                line_name = tl.get("nameShort") or tl.get("name") or "Transit"
                agency = tl.get("transitAgency", {}).get("name")
                headsign = td.get("headsign") or arr_stop.get("name")

                dep_lat = dep_stop.get("location", {}).get("latLng", {}).get("latitude")
                dep_lng = (
                    dep_stop.get("location", {}).get("latLng", {}).get("longitude")
                )
                arr_lat = arr_stop.get("location", {}).get("latLng", {}).get("latitude")
                arr_lng = (
                    arr_stop.get("location", {}).get("latLng", {}).get("longitude")
                )

                _, dep_stop_id, dep_stop_name = resolve_or_create_stop(
                    dep_stop.get("name", "Boarding Stop"),
                    dep_lat,
                    dep_lng,
                    stop_type=mode,
                )
                _, arr_stop_id, arr_stop_name = resolve_or_create_stop(
                    arr_stop.get("name", "Alight Stop"),
                    arr_lat,
                    arr_lng,
                    stop_type=mode,
                )

                poly = step.get("polyline", {}).get("encodedPolyline")

                leg = ItineraryLeg(
                    leg_index=seg_idx,
                    mode=mode,
                    origin=ItineraryEndpoint(id=dep_stop_id, name=dep_stop_name),
                    destination=ItineraryEndpoint(id=arr_stop_id, name=arr_stop_name),
                    dep_time=dep_time_str,
                    arr_time=arr_time_str,
                    duration_minutes=dur_mins,
                    line=line_name,
                    operator=agency,
                    headsign=headsign,
                    stops_count=td.get("stopCount"),
                    polyline=poly,
                )
                legs.append(leg)
                curr_endpoint_id = arr_stop_id
                curr_endpoint_name = arr_stop_name

            else:
                # Walk segment
                walk_steps = seg["steps"]
                walk_dur_sec = sum(
                    parse_duration_seconds(st.get("staticDuration"))
                    for st in walk_steps
                )
                walk_dur_mins = max(1, walk_dur_sec // 60) if walk_dur_sec else 1
                dep_time_str = format_minutes_to_time(current_time_min)
                arr_time_str = format_minutes_to_time(current_time_min + walk_dur_mins)
                current_time_min += walk_dur_mins

                next_transit = next(
                    (s for s in segments[seg_idx:] if s["type"] == "transit"),
                    None,
                )
                if next_transit:
                    ns = (
                        next_transit["step"]
                        .get("transitDetails", {})
                        .get("stopDetails", {})
                        .get("departureStop", {})
                    )
                    n_lat = ns.get("location", {}).get("latLng", {}).get("latitude")
                    n_lng = ns.get("location", {}).get("latLng", {}).get("longitude")
                    _, next_id, next_name = resolve_or_create_stop(
                        ns.get("name", "Stop"), n_lat, n_lng
                    )
                else:
                    next_id = to_id
                    next_name = to_name

                leg = ItineraryLeg(
                    leg_index=seg_idx,
                    mode="walk",
                    origin=ItineraryEndpoint(
                        id=curr_endpoint_id, name=curr_endpoint_name
                    ),
                    destination=ItineraryEndpoint(id=next_id, name=next_name),
                    dep_time=dep_time_str,
                    arr_time=arr_time_str,
                    duration_minutes=walk_dur_mins,
                )
                legs.append(leg)
                curr_endpoint_id = next_id
                curr_endpoint_name = next_name

        if not legs:
            return None

        itin_dep = legs[0].dep_time
        itin_arr = legs[-1].arr_time
        dep_m = parse_time_to_minutes(itin_dep) or 0
        arr_m = parse_time_to_minutes(itin_arr) or 0
        calculated_dur = (
            max(1, arr_m - dep_m) if arr_m >= dep_m else total_duration_mins
        )

        return ScheduledItinerary(
            departure_time=itin_dep,
            arrival_time=itin_arr,
            total_duration_minutes=calculated_dur,
            transfers_count=max(0, len([lg for lg in legs if lg.mode != "walk"]) - 1),
            robustness_score="high",
            legs=legs,
        )

    def enrich_itinerary_live(self, itinerary: ScheduledItinerary) -> None:
        """Enrich rail legs with Darwin live platforms and bus legs with BODS delay data."""
        from app.services.dispatcher.station_resolver import resolve_station_crs

        for leg in itinerary.legs:
            if leg.mode == "rail" and self.train_live_client:
                crs = resolve_station_crs(leg.origin.id)
                if crs:
                    try:
                        board = self.train_live_client.get_departure_board(
                            crs=crs, num_rows=10
                        )
                        services = (
                            board.get("GetStationBoardResult", {})
                            .get("trainServices", {})
                            .get("service", [])
                        )
                        if isinstance(services, dict):
                            services = [services]
                        for s in services:
                            std = s.get("std")
                            plat = s.get("platform")
                            if std == leg.dep_time:
                                if plat:
                                    leg.origin.platform = f"Platform {plat}"
                                break
                    except Exception as exc:
                        logger.debug(
                            "Darwin live platform probe failed for %s: %s", crs, exc
                        )

            elif leg.mode == "bus" and self.bus_live_client:
                # Bus platform indicator from stop metadata
                try:
                    stp = Stop.get_by_code(leg.origin.id)
                    if stp and stp.indicator:
                        ind = stp.indicator.strip()
                        leg.origin.platform = (
                            ind
                            if any(w in ind.lower() for w in ("stop", "stand", "bay"))
                            else f"Stop {ind}"
                        )
                except Exception:
                    pass


__all__ = [
    "DynamicRoutePlanner",
    "map_vehicle_type",
    "resolve_or_create_stop",
    "resolve_target_commute_datetime",
]
