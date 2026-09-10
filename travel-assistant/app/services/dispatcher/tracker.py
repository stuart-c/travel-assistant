"""Journey progress tracking, position monitoring, and live notification updates."""

import datetime
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from app.datasources.homeassistant import HomeAssistantClient
from app.datasources.train_live import TrainLiveClient
from app.models.journey import Journey
from app.models.setting import Setting
from app.services.dispatcher.proximity import (
    haversine_distance,
    is_person_near_origin,
    resolve_endpoint_coordinates,
)
from app.services.planner.models import ItineraryLeg, ScheduledItinerary
from app.services.planner.transfers import (
    DAY_NAME_TO_CODE,
    format_minutes_to_time,
    parse_time_to_minutes,
)

logger = logging.getLogger(__name__)

_UPCOMING_ITINERARY_CACHE: Dict[int, Tuple[float, str, Any]] = {}
_TRACKING_CACHE_TTL_SECONDS = 60.0


def clear_tracking_cache() -> None:
    """Flush in-memory planned itinerary cache for live tracking."""
    _UPCOMING_ITINERARY_CACHE.clear()


class JourneyStepStatus(str, Enum):
    """Lifecycle status of Stuart's progression through a journey."""

    PRE_DEPARTURE = "pre_departure"
    EN_ROUTE_TO_STOP = "en_route_to_stop"
    AT_DEPARTURE_STOP = "at_departure_stop"
    ON_TRANSIT = "on_transit"
    AT_INTERCHANGE = "at_interchange"
    EN_ROUTE_TO_DESTINATION = "en_route_to_destination"
    ARRIVED = "arrived"
    EXPIRED = "expired"


@dataclass
class ActiveJourney:
    """State of an in-progress journey being tracked for Stuart."""

    journey_id: int
    journey_name: str
    from_type: str
    from_id: str
    from_name: str
    to_type: str
    to_id: str
    to_name: str
    itinerary: ScheduledItinerary
    legs: List[ItineraryLeg] = field(default_factory=list)
    current_leg_index: int = 0
    current_status: JourneyStepStatus = JourneyStepStatus.PRE_DEPARTURE
    started_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    expected_arrival_time: str = ""
    last_notification_message: Optional[str] = None
    platform: Optional[str] = None
    live_status: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.legs and self.itinerary and self.itinerary.legs:
            self.legs = list(self.itinerary.legs)
        if not self.expected_arrival_time and self.itinerary:
            self.expected_arrival_time = self.itinerary.arrival_time


def resolve_live_rail_platform(
    origin_id: str,
    dest_id: str,
    scheduled_time: str,
    live_client: Optional[TrainLiveClient] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Probe Darwin Live Departure Boards for real-time platform and service status."""
    if not live_client:
        return None, None

    crs = origin_id.strip()
    if crs.startswith("naptan:"):
        crs = crs[len("naptan:") :]

    if len(crs) != 3 or not crs.isalpha():
        from app.models.transit import Stop

        stop = (
            Stop.select()
            .where((Stop.atco_code == origin_id) | (Stop.naptan_code == origin_id))
            .first()
        )
        if (
            stop
            and stop.naptan_code
            and len(stop.naptan_code) == 3
            and stop.naptan_code.isalpha()
        ):
            crs = stop.naptan_code
        else:
            return None, None

    dest_crs = dest_id.strip()
    if dest_crs.startswith("naptan:"):
        dest_crs = dest_crs[len("naptan:") :]

    if len(dest_crs) != 3 or not dest_crs.isalpha():
        from app.models.transit import Stop

        dest_stop = (
            Stop.select()
            .where((Stop.atco_code == dest_id) | (Stop.naptan_code == dest_id))
            .first()
        )
        if (
            dest_stop
            and dest_stop.naptan_code
            and len(dest_stop.naptan_code) == 3
            and dest_stop.naptan_code.isalpha()
        ):
            dest_crs = dest_stop.naptan_code

    filter_list = dest_crs if (len(dest_crs) == 3 and dest_crs.isalpha()) else None

    try:
        departures = live_client.get_fastest_departures(
            crs, [filter_list] if filter_list else None
        )
        if departures and isinstance(departures, list):
            for dep in departures:
                std = dep.get("std")
                if std == scheduled_time or not scheduled_time:
                    platform = dep.get("platform")
                    etd = dep.get("etd")
                    plat_str = str(platform).strip() if platform else None
                    status_str = str(etd).strip() if etd else None
                    return plat_str, status_str
    except Exception as exc:
        logger.debug("Live platform probe skipped for %s: %s", crs, exc)

    return None, None


def _format_transit_service_desc(mode: str, line: Optional[str]) -> str:
    """Format transit service description preventing duplicate mode keywords."""
    mode_label = mode.title() if mode else "Transit"
    line_name = (line or "").strip()
    if line_name:
        if mode_label.lower() in line_name.lower():
            return line_name
        return f"{mode_label} {line_name}"
    return mode_label


def format_progress_notification(
    active: ActiveJourney,
) -> Tuple[str, str, Dict[str, Any]]:
    """Generate user-facing notification title and message for the current journey step."""
    title = f"Travel Alert: {active.journey_name}"
    current_leg: Optional[ItineraryLeg] = (
        active.legs[active.current_leg_index]
        if active.current_leg_index < len(active.legs)
        else None
    )

    status = active.current_status
    message = ""

    if status == JourneyStepStatus.PRE_DEPARTURE:
        first_transit = next((leg for leg in active.legs if leg.mode != "walk"), None)
        walk_leg = (
            active.legs[0] if active.legs and active.legs[0].mode == "walk" else None
        )
        walk_mins = walk_leg.duration_minutes if walk_leg else 0
        walk_info = f"walk {walk_mins}m" if walk_mins > 0 else "direct departure"

        transit_desc = (
            _format_transit_service_desc(first_transit.mode, first_transit.line)
            if first_transit
            else "direct departure"
        )
        dep_time = (
            first_transit.dep_time if first_transit else active.itinerary.departure_time
        )
        origin_name = first_transit.origin.name if first_transit else active.from_name

        dep_min = parse_time_to_minutes(dep_time) or 0
        leave_min = dep_min - walk_mins
        leave_time_str = format_minutes_to_time(leave_min)

        plat_note = f" (Platform {active.platform})" if active.platform else ""
        live_note = f" ({active.live_status})" if active.live_status else ""

        message = (
            f"Leave by {leave_time_str} ({walk_info}) for {transit_desc}{plat_note}{live_note} "
            f"from {origin_name} departing at {dep_time}. "
            f"Estimated arrival at {active.to_name} by {active.expected_arrival_time}."
        )

    elif status == JourneyStepStatus.EN_ROUTE_TO_STOP:
        next_leg = (
            active.legs[active.current_leg_index + 1]
            if active.current_leg_index + 1 < len(active.legs)
            else current_leg
        )
        stop_name = next_leg.origin.name if next_leg else "departure stop"
        line_desc = (
            _format_transit_service_desc(next_leg.mode, next_leg.line)
            if next_leg
            else "Transit"
        )
        message = (
            f"On your way to {stop_name}. "
            f"{line_desc} departs at {next_leg.dep_time if next_leg else ''}. "
            f"Destination: {active.to_name}."
        )

    elif status == JourneyStepStatus.AT_DEPARTURE_STOP:
        if current_leg and current_leg.mode == "rail":
            plat_info = (
                f"Platform {active.platform}"
                if active.platform
                else "Platform to be announced"
            )
            live_note = f" ({active.live_status})" if active.live_status else ""
            line_desc = _format_transit_service_desc(current_leg.mode, current_leg.line)
            message = (
                f"At {current_leg.origin.name}. "
                f"{line_desc} to {current_leg.destination.name} departs at "
                f"{current_leg.dep_time} from {plat_info}{live_note}."
            )
        elif current_leg:
            line_desc = _format_transit_service_desc(current_leg.mode, current_leg.line)
            message = (
                f"At {current_leg.origin.name}. "
                f"{line_desc} to {current_leg.destination.name} departs at {current_leg.dep_time}."
            )
        else:
            message = f"At departure stop for {active.to_name}."

    elif status == JourneyStepStatus.ON_TRANSIT:
        if current_leg:
            line_desc = _format_transit_service_desc(current_leg.mode, current_leg.line)
            next_step_info = ""
            if active.current_leg_index + 1 < len(active.legs):
                next_leg = active.legs[active.current_leg_index + 1]
                if next_leg.mode == "walk":
                    next_step_info = f" Next step: Walk {next_leg.duration_minutes}m to {next_leg.destination.name}."
                else:
                    transfer_desc = _format_transit_service_desc(
                        next_leg.mode, next_leg.line
                    )
                    next_step_info = f" Transfer to {transfer_desc}."

            plat_note = f" (Platform {active.platform})" if active.platform else ""
            message = (
                f"On board {line_desc}{plat_note} towards {current_leg.destination.name}. "
                f"Expected arrival at {current_leg.arr_time}.{next_step_info}"
            )
        else:
            message = f"In transit towards {active.to_name}."

    elif status == JourneyStepStatus.AT_INTERCHANGE:
        if current_leg:
            line_desc = _format_transit_service_desc(current_leg.mode, current_leg.line)
            plat_info = (
                f"Platform {active.platform}"
                if active.platform
                else "Platform to be announced"
            )
            message = (
                f"Transfer at {current_leg.origin.name}: "
                f"Board {line_desc} departing at {current_leg.dep_time} from {plat_info}."
            )
        else:
            message = "Interchange stop: transfer to connecting service."

    elif status == JourneyStepStatus.EN_ROUTE_TO_DESTINATION:
        message = (
            f"Final leg: Walk to {active.to_name}. "
            f"Estimated arrival at {active.expected_arrival_time}."
        )

    elif status == JourneyStepStatus.ARRIVED:
        message = (
            f"Journey complete: Arrived at {active.to_name} ({active.expected_arrival_time}). "
            f"Have a great day!"
        )

    else:
        message = f"Journey update: en route to {active.to_name}."

    panel_slug = (
        Setting.get_val(
            "ingress_panel_slug",
            os.environ.get("ADDON_PANEL_PATH", ""),
        )
        or ""
    ).strip("/")
    nav_url = f"/{panel_slug}" if panel_slug else "/journey"

    data: Dict[str, Any] = {
        "url": nav_url,
        "clickAction": nav_url,
        "tag": f"journey_{active.journey_id}",
        "group": "travel_assistant_journeys",
    }

    return title, message, data


def _determine_transit_arrival_status(active: ActiveJourney) -> JourneyStepStatus:
    """Determine whether the next stage after reaching a stop is final walking or interchange."""
    if active.current_leg_index >= len(active.legs):
        return JourneyStepStatus.EN_ROUTE_TO_DESTINATION
    next_leg = active.legs[active.current_leg_index]
    if active.current_leg_index == len(active.legs) - 1 and next_leg.mode == "walk":
        return JourneyStepStatus.EN_ROUTE_TO_DESTINATION
    return JourneyStepStatus.AT_INTERCHANGE


def update_journey_progress(
    active: ActiveJourney,
    person_state: Optional[Dict[str, Any]],
    current_dt: datetime.datetime,
    ha_client: HomeAssistantClient,
    live_client: Optional[TrainLiveClient] = None,
    max_proximity_metres: float = 200.0,
) -> bool:
    """Evaluate Stuart's location against journey stages and dispatch notification updates.

    Returns True if a notification update was dispatched, False otherwise.
    """
    if not person_state or not isinstance(person_state, dict):
        return False

    current_minutes = current_dt.hour * 60 + current_dt.minute

    # Check journey expiration timeout (e.g. 90 minutes past expected arrival)
    arr_minutes = parse_time_to_minutes(active.expected_arrival_time)
    if arr_minutes is not None:
        if current_minutes > arr_minutes + 90:
            active.current_status = JourneyStepStatus.EXPIRED
            return False

    # Check if Stuart missed departure time while still in PRE_DEPARTURE
    if active.current_status == JourneyStepStatus.PRE_DEPARTURE:
        first_transit = next((leg for leg in active.legs if leg.mode != "walk"), None)
        walk_mins = (
            active.legs[0].duration_minutes
            if (active.legs and active.legs[0].mode == "walk")
            else 0
        )
        dep_time = (
            first_transit.dep_time if first_transit else active.itinerary.departure_time
        )
        dep_m = parse_time_to_minutes(dep_time)
        if dep_m is not None:
            leave_m = dep_m - walk_mins
            if current_minutes > leave_m + 2:
                # Stuart did not leave on time; expire active journey to allow next candidate evaluation
                active.current_status = JourneyStepStatus.EXPIRED
                return False

    # Check if Stuart has arrived at the final destination (only once journey has started)
    if active.current_status != JourneyStepStatus.PRE_DEPARTURE:
        is_at_final_dest = is_person_near_origin(
            person_state=person_state,
            from_type=active.to_type,
            from_id=active.to_id,
            max_distance_metres=max_proximity_metres,
        )
        if is_at_final_dest:
            if active.current_status != JourneyStepStatus.ARRIVED:
                active.current_status = JourneyStepStatus.ARRIVED
                title, msg, data = format_progress_notification(active)
                try:
                    ha_client.send_mobile_notification(
                        title=title, message=msg, data=data
                    )
                    active.last_notification_message = msg
                    logger.info(
                        "Dispatched journey arrival notification for journey %d (%s): %s",
                        active.journey_id,
                        active.journey_name,
                        msg,
                    )
                    return True
                except Exception as exc:
                    logger.error(
                        "Failed to send arrival notification for journey %d: %s",
                        active.journey_id,
                        exc,
                    )
                    return False
            return False

    # Extract Stuart's GPS coordinates
    attrs = person_state.get("attributes", {}) or {}
    raw_lat = attrs.get("latitude")
    raw_lon = attrs.get("longitude")
    person_lat = float(raw_lat) if raw_lat is not None else None
    person_lon = float(raw_lon) if raw_lon is not None else None

    # Step through legs progression
    old_status = active.current_status
    old_leg_idx = active.current_leg_index

    # Identify current leg
    if active.current_leg_index >= len(active.legs):
        active.current_status = JourneyStepStatus.EN_ROUTE_TO_DESTINATION
    else:
        leg = active.legs[active.current_leg_index]
        orig_lat, orig_lon, _ = resolve_endpoint_coordinates(leg.mode, leg.origin.id)
        dest_lat, dest_lon, _ = resolve_endpoint_coordinates(
            leg.mode, leg.destination.id
        )

        dist_to_orig = (
            haversine_distance(person_lat, person_lon, orig_lat, orig_lon)
            if (person_lat is not None and orig_lat is not None)
            else None
        )
        dist_to_dest = (
            haversine_distance(person_lat, person_lon, dest_lat, dest_lon)
            if (person_lat is not None and dest_lat is not None)
            else None
        )

        dep_min = parse_time_to_minutes(leg.dep_time)

        if leg.mode == "walk":
            if active.current_leg_index == 0:
                # First walking leg (origin -> departure stop)
                if dist_to_orig is not None and dist_to_orig <= max_proximity_metres:
                    active.current_status = JourneyStepStatus.PRE_DEPARTURE
                elif dist_to_dest is not None and dist_to_dest <= max_proximity_metres:
                    # Stuart reached the departure stop! Advance to first transit leg
                    active.current_leg_index += 1
                    active.current_status = JourneyStepStatus.AT_DEPARTURE_STOP
                else:
                    leg_dist = (
                        haversine_distance(orig_lat, orig_lon, dest_lat, dest_lon)
                        if (orig_lat is not None and dest_lat is not None)
                        else 1000.0
                    )
                    max_allowed = max(
                        leg_dist * 1.5, leg_dist + max_proximity_metres, 500.0
                    )
                    if dist_to_dest is not None and dist_to_dest <= max_allowed:
                        active.current_status = JourneyStepStatus.EN_ROUTE_TO_STOP
                    else:
                        active.current_status = JourneyStepStatus.EXPIRED
                        return False
            else:
                # Egress or intermediate walking transfer
                if dist_to_dest is not None and dist_to_dest <= max_proximity_metres:
                    active.current_leg_index += 1
                    active.current_status = _determine_transit_arrival_status(active)
                else:
                    active.current_status = JourneyStepStatus.EN_ROUTE_TO_DESTINATION

        else:
            # Transit leg (rail, bus, metro, tram)
            # 1. Proximity to transit origin stop
            if dist_to_orig is not None and dist_to_orig <= max_proximity_metres:
                if active.current_leg_index == 0 or (
                    active.current_leg_index == 1 and active.legs[0].mode == "walk"
                ):
                    active.current_status = JourneyStepStatus.AT_DEPARTURE_STOP
                else:
                    active.current_status = JourneyStepStatus.AT_INTERCHANGE

            # 2. Transit in progress: departure time reached and moving towards destination
            elif dep_min is not None and current_minutes >= dep_min:
                if dist_to_dest is not None and dist_to_dest <= max_proximity_metres:
                    # Reached transit destination stop
                    active.current_leg_index += 1
                    active.current_status = _determine_transit_arrival_status(active)
                else:
                    active.current_status = JourneyStepStatus.ON_TRANSIT
            else:
                # Prior to departure time
                if active.current_leg_index == 0 or (
                    active.current_leg_index == 1 and active.legs[0].mode == "walk"
                ):
                    active.current_status = JourneyStepStatus.AT_DEPARTURE_STOP
                else:
                    active.current_status = JourneyStepStatus.AT_INTERCHANGE

    # Check for live platform update if rail leg
    current_leg = (
        active.legs[active.current_leg_index]
        if active.current_leg_index < len(active.legs)
        else None
    )
    if current_leg and current_leg.mode == "rail" and live_client:
        plat, live_stat = resolve_live_rail_platform(
            origin_id=current_leg.origin.id,
            dest_id=current_leg.destination.id,
            scheduled_time=current_leg.dep_time,
            live_client=live_client,
        )
        if plat and plat != active.platform:
            active.platform = plat
        if live_stat:
            active.live_status = live_stat

    title, new_msg, data = format_progress_notification(active)

    # Dispatch notification if status changed, platform updated, or message changed
    if (
        active.current_status != old_status
        or active.current_leg_index != old_leg_idx
        or new_msg != active.last_notification_message
    ):
        try:
            ha_client.send_mobile_notification(title=title, message=new_msg, data=data)
            active.last_notification_message = new_msg
            logger.info(
                "Updated journey progress notification for journey %d (%s) [%s]: %s",
                active.journey_id,
                active.journey_name,
                active.current_status.value,
                new_msg,
            )
            return True
        except Exception as exc:
            logger.error(
                "Failed to send progress notification update for journey %d: %s",
                active.journey_id,
                exc,
            )

    return False


def detect_en_route_journey(
    journey: Journey,
    person_state: Optional[Dict[str, Any]],
    current_dt: datetime.datetime,
    live_client: Optional[TrainLiveClient] = None,
    max_proximity_metres: float = 200.0,
) -> Optional[ActiveJourney]:
    """Detect if Stuart is currently en route along a scheduled journey corridor.

    Evaluates recent scheduled itineraries for the journey to determine if Stuart's
    current GPS location matches any intermediate transit stop, interchange, or transit leg.
    If a matching progression stage is detected, instantiates and returns an ActiveJourney.
    """
    if not person_state or not isinstance(person_state, dict):
        return None

    # Stuart cannot be en route if still near the origin or already at destination
    if is_person_near_origin(person_state, journey.from_type, journey.from_id):
        return None
    if is_person_near_origin(person_state, journey.to_type, journey.to_id):
        return None

    attrs = person_state.get("attributes", {}) or {}
    raw_lat = attrs.get("latitude")
    raw_lon = attrs.get("longitude")
    if raw_lat is None or raw_lon is None:
        return None

    try:
        person_lat = float(raw_lat)
        person_lon = float(raw_lon)
    except (ValueError, TypeError):
        return None

    current_minutes = current_dt.hour * 60 + current_dt.minute
    weekday_idx = current_dt.weekday()
    day_names = [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ]
    day_code = DAY_NAME_TO_CODE.get(day_names[weekday_idx], "mon")

    # Search for candidate itineraries covering a 2-hour window up to 15 minutes ahead
    search_start_min = max(0, current_minutes - 120)
    search_time_str = format_minutes_to_time(search_start_min)
    search_end_min = min(1439, current_minutes + 15)
    search_end_str = format_minutes_to_time(search_end_min)

    try:
        from app.services.planner.raptor import plan_journey

        itineraries = plan_journey(
            from_type=journey.from_type,
            from_id=journey.from_id,
            to_type=journey.to_type,
            to_id=journey.to_id,
            timing_mode="window",
            time_str=search_time_str,
            time_window_end=search_end_str,
            days_of_week=[day_code],
            target_date=current_dt.date(),
            max_itineraries=8,
        )
    except Exception as exc:
        logger.debug(
            "Could not plan candidate itineraries for en-route detection on journey %d: %s",
            journey.id,
            exc,
        )
        return None

    if not itineraries:
        return None

    for itin in itineraries:
        if not itin.legs:
            continue

        dep_m = parse_time_to_minutes(itin.departure_time)
        arr_m = parse_time_to_minutes(itin.arrival_time)
        if dep_m is None or arr_m is None:
            continue

        if arr_m < dep_m:
            arr_m += 1440

        cur_m_effective = (
            current_minutes + 1440
            if (current_minutes < 120 and dep_m > 1200)
            else current_minutes
        )

        # Candidate must cover current time (dep_m <= cur_m_effective <= arr_m + 60)
        if dep_m > cur_m_effective or cur_m_effective > arr_m + 60:
            continue

        for leg_idx, leg in enumerate(itin.legs):
            orig_lat, orig_lon, _ = resolve_endpoint_coordinates(
                leg.mode, leg.origin.id
            )
            dest_lat, dest_lon, _ = resolve_endpoint_coordinates(
                leg.mode, leg.destination.id
            )

            dist_orig = (
                haversine_distance(person_lat, person_lon, orig_lat, orig_lon)
                if (orig_lat is not None and orig_lon is not None)
                else None
            )
            dist_dest = (
                haversine_distance(person_lat, person_lon, dest_lat, dest_lon)
                if (dest_lat is not None and dest_lon is not None)
                else None
            )

            leg_dep_m = parse_time_to_minutes(leg.dep_time)
            leg_arr_m = parse_time_to_minutes(leg.arr_time)
            if (
                leg_dep_m is not None
                and leg_arr_m is not None
                and leg_arr_m < leg_dep_m
            ):
                leg_arr_m += 1440

            # 1. At the departure stop or interchange for this leg
            if dist_orig is not None and dist_orig <= max_proximity_metres:
                if leg_idx == 0 or (leg_idx == 1 and itin.legs[0].mode == "walk"):
                    status = JourneyStepStatus.AT_DEPARTURE_STOP
                else:
                    status = JourneyStepStatus.AT_INTERCHANGE

                plat = None
                live_stat = None
                if leg.mode == "rail" and live_client:
                    plat, live_stat = resolve_live_rail_platform(
                        origin_id=leg.origin.id,
                        dest_id=leg.destination.id,
                        scheduled_time=leg.dep_time,
                        live_client=live_client,
                    )

                return ActiveJourney(
                    journey_id=journey.id,
                    journey_name=journey.name,
                    from_type=journey.from_type,
                    from_id=journey.from_id,
                    from_name=journey.from_name,
                    to_type=journey.to_type,
                    to_id=journey.to_id,
                    to_name=journey.to_name,
                    itinerary=itin,
                    legs=list(itin.legs),
                    current_leg_index=leg_idx,
                    current_status=status,
                    started_at=current_dt,
                    expected_arrival_time=itin.arrival_time,
                    platform=plat,
                    live_status=live_stat,
                )

            # 2. At the destination of this leg
            if dist_dest is not None and dist_dest <= max_proximity_metres:
                next_idx = leg_idx + 1
                if leg_idx == 0 and leg.mode == "walk":
                    status = JourneyStepStatus.AT_DEPARTURE_STOP
                elif next_idx >= len(itin.legs):
                    status = JourneyStepStatus.EN_ROUTE_TO_DESTINATION
                elif (
                    next_idx == len(itin.legs) - 1
                    and itin.legs[next_idx].mode == "walk"
                ):
                    status = JourneyStepStatus.EN_ROUTE_TO_DESTINATION
                else:
                    status = JourneyStepStatus.AT_INTERCHANGE

                plat = None
                live_stat = None
                next_leg = itin.legs[next_idx] if next_idx < len(itin.legs) else None
                if next_leg and next_leg.mode == "rail" and live_client:
                    plat, live_stat = resolve_live_rail_platform(
                        origin_id=next_leg.origin.id,
                        dest_id=next_leg.destination.id,
                        scheduled_time=next_leg.dep_time,
                        live_client=live_client,
                    )

                return ActiveJourney(
                    journey_id=journey.id,
                    journey_name=journey.name,
                    from_type=journey.from_type,
                    from_id=journey.from_id,
                    from_name=journey.from_name,
                    to_type=journey.to_type,
                    to_id=journey.to_id,
                    to_name=journey.to_name,
                    itinerary=itin,
                    legs=list(itin.legs),
                    current_leg_index=(
                        next_idx if next_idx < len(itin.legs) else leg_idx
                    ),
                    current_status=status,
                    started_at=current_dt,
                    expected_arrival_time=itin.arrival_time,
                    platform=plat,
                    live_status=live_stat,
                )

            # 3. En route on board transit during transit leg duration
            leg_cur_m = (
                current_minutes + 1440
                if (
                    leg_dep_m is not None and current_minutes < 120 and leg_dep_m > 1200
                )
                else current_minutes
            )
            if (
                leg_dep_m is not None
                and leg_arr_m is not None
                and leg_dep_m <= leg_cur_m <= leg_arr_m
                and leg.mode != "walk"
                and orig_lat is not None
                and dest_lat is not None
            ):
                leg_span = haversine_distance(orig_lat, orig_lon, dest_lat, dest_lon)
                if (
                    dist_orig is not None
                    and dist_dest is not None
                    and (dist_orig + dist_dest)
                    <= max(leg_span * 1.5, leg_span + 1000.0)
                ):
                    plat = None
                    live_stat = None
                    if leg.mode == "rail" and live_client:
                        plat, live_stat = resolve_live_rail_platform(
                            origin_id=leg.origin.id,
                            dest_id=leg.destination.id,
                            scheduled_time=leg.dep_time,
                            live_client=live_client,
                        )

                    return ActiveJourney(
                        journey_id=journey.id,
                        journey_name=journey.name,
                        from_type=journey.from_type,
                        from_id=journey.from_id,
                        from_name=journey.from_name,
                        to_type=journey.to_type,
                        to_id=journey.to_id,
                        to_name=journey.to_name,
                        itinerary=itin,
                        legs=list(itin.legs),
                        current_leg_index=leg_idx,
                        current_status=JourneyStepStatus.ON_TRANSIT,
                        started_at=current_dt,
                        expected_arrival_time=itin.arrival_time,
                        platform=plat,
                        live_status=live_stat,
                    )

            # 4. Walking to departure stop (first leg is walk, left origin corridor towards transit stop)
            if (
                leg_idx == 0
                and leg.mode == "walk"
                and orig_lat is not None
                and dest_lat is not None
            ):
                walk_dep = leg_dep_m if leg_dep_m is not None else 0
                walk_arr = leg_arr_m if leg_arr_m is not None else 1440
                next_leg = itin.legs[1] if len(itin.legs) > 1 else None
                next_dep_m = (
                    parse_time_to_minutes(next_leg.dep_time) if next_leg else None
                )
                max_walk_time = next_dep_m if next_dep_m is not None else (walk_arr + 5)
                if (walk_dep - 15) <= leg_cur_m < max_walk_time:
                    leg_span = haversine_distance(
                        orig_lat, orig_lon, dest_lat, dest_lon
                    )
                    if (
                        dist_orig is not None
                        and dist_dest is not None
                        and (dist_orig + dist_dest)
                        <= max(leg_span * 1.5, leg_span + 1000.0)
                    ):
                        plat = None
                        live_stat = None
                        if next_leg and next_leg.mode == "rail" and live_client:
                            plat, live_stat = resolve_live_rail_platform(
                                origin_id=next_leg.origin.id,
                                dest_id=next_leg.destination.id,
                                scheduled_time=next_leg.dep_time,
                                live_client=live_client,
                            )

                        return ActiveJourney(
                            journey_id=journey.id,
                            journey_name=journey.name,
                            from_type=journey.from_type,
                            from_id=journey.from_id,
                            from_name=journey.from_name,
                            to_type=journey.to_type,
                            to_id=journey.to_id,
                            to_name=journey.to_name,
                            itinerary=itin,
                            legs=list(itin.legs),
                            current_leg_index=0,
                            current_status=JourneyStepStatus.EN_ROUTE_TO_STOP,
                            started_at=current_dt,
                            expected_arrival_time=itin.arrival_time,
                            platform=plat,
                            live_status=live_stat,
                        )

    return None


STATUS_METADATA: Dict[JourneyStepStatus, Dict[str, str]] = {
    JourneyStepStatus.PRE_DEPARTURE: {
        "label": "Preparing to leave",
        "icon": "schedule",
        "badge_colour": "sky",
    },
    JourneyStepStatus.EN_ROUTE_TO_STOP: {
        "label": "Walking to departure stop",
        "icon": "directions_walk",
        "badge_colour": "amber",
    },
    JourneyStepStatus.AT_DEPARTURE_STOP: {
        "label": "At departure stop",
        "icon": "pin_drop",
        "badge_colour": "indigo",
    },
    JourneyStepStatus.ON_TRANSIT: {
        "label": "On board transit",
        "icon": "directions_transit",
        "badge_colour": "emerald",
    },
    JourneyStepStatus.AT_INTERCHANGE: {
        "label": "At transfer station",
        "icon": "transfer_within_a_station",
        "badge_colour": "purple",
    },
    JourneyStepStatus.EN_ROUTE_TO_DESTINATION: {
        "label": "Walking to destination",
        "icon": "directions_walk",
        "badge_colour": "teal",
    },
    JourneyStepStatus.ARRIVED: {
        "label": "Arrived at destination",
        "icon": "check_circle",
        "badge_colour": "emerald",
    },
    JourneyStepStatus.EXPIRED: {
        "label": "Journey completed",
        "icon": "done_all",
        "badge_colour": "slate",
    },
}


def get_journey_live_tracking_data(
    journey_id: Optional[int] = None,
    dt: Optional[datetime.datetime] = None,
    ha_client: Optional[HomeAssistantClient] = None,
    live_client: Optional[TrainLiveClient] = None,
    active_journeys: Optional[Dict[int, ActiveJourney]] = None,
) -> Dict[str, Any]:
    """Compile aggregated journey progress, waypoints, and Stuart's real-time position."""
    current_dt = dt or datetime.datetime.now()

    # 1. Resolve active journeys
    current_active_journeys: Dict[int, ActiveJourney] = {}
    if active_journeys is not None:
        current_active_journeys = active_journeys
    else:
        try:
            from app.services.dispatcher.monitor import get_departure_monitor

            mon = get_departure_monitor()
            if mon:
                current_active_journeys = mon.active_journeys
        except Exception:
            current_active_journeys = {}

    # 2. Query configured journeys
    all_journeys = list(Journey.select())
    journeys_list = [
        {
            "id": j.id,
            "name": j.name,
            "from_name": j.from_name,
            "to_name": j.to_name,
            "is_active": (j.id in current_active_journeys),
        }
        for j in all_journeys
    ]

    # 3. Determine selected journey ID
    target_id: Optional[int] = None
    if journey_id is not None and any(j["id"] == journey_id for j in journeys_list):
        target_id = journey_id
    elif current_active_journeys:
        target_id = next(iter(current_active_journeys.keys()))
    elif journeys_list:
        target_id = journeys_list[0]["id"]

    if target_id is None:
        return {
            "journeys": [],
            "selected_journey": None,
            "person": None,
            "active": False,
            "timestamp": current_dt.isoformat(),
        }

    # 4. Query Stuart's current position from Home Assistant
    client = ha_client or HomeAssistantClient.from_settings()
    person_state: Optional[Dict[str, Any]] = None
    if client and client.token:
        try:
            person_state = client.get_entity_state("person.stuart")
        except Exception as exc:
            logger.debug("Could not query Home Assistant for person.stuart: %s", exc)

    person_lat: Optional[float] = None
    person_lon: Optional[float] = None
    person_status_str = "unknown"
    if person_state and isinstance(person_state, dict):
        person_status_str = str(person_state.get("state", "unknown"))
        attrs = person_state.get("attributes", {}) or {}
        raw_lat = attrs.get("latitude")
        raw_lon = attrs.get("longitude")
        if raw_lat is not None and raw_lon is not None:
            try:
                person_lat = float(raw_lat)
                person_lon = float(raw_lon)
            except (ValueError, TypeError):
                pass

    # 5. Extract journey data
    if target_id in current_active_journeys:
        active = current_active_journeys[target_id]
        is_active = True
        journey_name = active.journey_name
        from_name = active.from_name
        from_type = active.from_type
        from_id = active.from_id
        to_name = active.to_name
        to_type = active.to_type
        to_id = active.to_id
        current_status = active.current_status
        current_leg_index = active.current_leg_index
        platform = active.platform
        live_status = active.live_status
        departure_time = active.itinerary.departure_time if active.itinerary else ""
        expected_arrival_time = active.expected_arrival_time
        legs = list(active.legs)
        notification_message = active.last_notification_message
    else:
        j_obj = next(j for j in all_journeys if j.id == target_id)
        is_active = False
        journey_name = j_obj.name
        from_name = j_obj.from_name
        from_type = j_obj.from_type
        from_id = j_obj.from_id
        to_name = j_obj.to_name
        to_type = j_obj.to_type
        to_id = j_obj.to_id
        current_status = JourneyStepStatus.PRE_DEPARTURE
        current_leg_index = 0
        platform = None
        live_status = None
        notification_message = None

        # Plan upcoming itinerary (cached to avoid repeated RAPTOR runs on auto-refresh)
        upcoming_itinerary = None
        time_str = current_dt.strftime("%H:%M")
        now_ts = time.time()
        cached_entry = _UPCOMING_ITINERARY_CACHE.get(target_id)
        if (
            cached_entry is not None
            and (now_ts - cached_entry[0]) < _TRACKING_CACHE_TTL_SECONDS
            and cached_entry[1] == time_str
        ):
            upcoming_itinerary = cached_entry[2]
        else:
            weekday_idx = current_dt.weekday()
            day_names = [
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
            ]
            day_code = DAY_NAME_TO_CODE.get(day_names[weekday_idx], "mon")
            try:
                from app.services.planner.raptor import plan_journey

                plans = plan_journey(
                    from_type=j_obj.from_type,
                    from_id=j_obj.from_id,
                    to_type=j_obj.to_type,
                    to_id=j_obj.to_id,
                    timing_mode="depart",
                    time_str=time_str,
                    days_of_week=[day_code],
                    target_date=current_dt.date(),
                    max_itineraries=1,
                )
                if plans:
                    upcoming_itinerary = plans[0]
                _UPCOMING_ITINERARY_CACHE[target_id] = (
                    now_ts,
                    time_str,
                    upcoming_itinerary,
                )
            except Exception as exc:
                logger.debug(
                    "Could not plan upcoming itinerary for journey %d: %s",
                    target_id,
                    exc,
                )

        if upcoming_itinerary:
            legs = list(upcoming_itinerary.legs)
            departure_time = upcoming_itinerary.departure_time
            expected_arrival_time = upcoming_itinerary.arrival_time
        else:
            legs = []
            departure_time = ""
            expected_arrival_time = ""

    # Check live rail platform if applicable
    if current_leg_index < len(legs):
        cur_leg = legs[current_leg_index]
        if cur_leg.mode == "rail" and live_client:
            plat, l_stat = resolve_live_rail_platform(
                cur_leg.origin.id,
                cur_leg.destination.id,
                cur_leg.dep_time,
                live_client,
            )
            if plat:
                platform = plat
            if l_stat:
                live_status = l_stat

    # 6. Resolve coordinates
    origin_lat, origin_lon, _ = resolve_endpoint_coordinates(from_type, from_id)
    dest_lat, dest_lon, _ = resolve_endpoint_coordinates(to_type, to_id)

    serialized_legs: List[Dict[str, Any]] = []
    waypoints: List[Dict[str, Any]] = []

    if origin_lat is not None and origin_lon is not None:
        waypoints.append(
            {
                "lat": origin_lat,
                "lon": origin_lon,
                "name": from_name,
                "type": "origin",
                "description": f"Origin: {from_name}",
            }
        )

    for idx, leg in enumerate(legs):
        o_lat, o_lon, _ = resolve_endpoint_coordinates(leg.mode, leg.origin.id)
        d_lat, d_lon, _ = resolve_endpoint_coordinates(leg.mode, leg.destination.id)

        leg_plat = getattr(leg.origin, "platform", None)
        if idx == current_leg_index and platform:
            leg_plat = platform

        is_completed = (idx < current_leg_index) if is_active else False
        is_current = (idx == current_leg_index) if is_active else (idx == 0)
        is_upcoming = (idx > current_leg_index) if is_active else (idx > 0)

        leg_dict = {
            "leg_index": idx,
            "mode": leg.mode,
            "line": leg.line,
            "operator": leg.operator,
            "headsign": getattr(leg, "headsign", None),
            "dep_time": leg.dep_time,
            "arr_time": leg.arr_time,
            "duration_minutes": leg.duration_minutes,
            "origin": {
                "id": leg.origin.id,
                "name": leg.origin.name,
                "platform": leg_plat,
                "latitude": o_lat,
                "longitude": o_lon,
            },
            "destination": {
                "id": leg.destination.id,
                "name": leg.destination.name,
                "latitude": d_lat,
                "longitude": d_lon,
            },
            "status": (
                "completed"
                if is_completed
                else ("current" if is_current else "upcoming")
            ),
            "is_completed": is_completed,
            "is_current": is_current,
            "is_upcoming": is_upcoming,
        }
        serialized_legs.append(leg_dict)

        if o_lat is not None and o_lon is not None:
            if not waypoints or (
                abs(waypoints[-1]["lat"] - o_lat) > 1e-5
                or abs(waypoints[-1]["lon"] - o_lon) > 1e-5
            ):
                waypoints.append(
                    {
                        "lat": o_lat,
                        "lon": o_lon,
                        "name": leg.origin.name,
                        "type": "origin" if idx == 0 and not waypoints else "stop",
                        "description": f"{leg.origin.name} ({leg.mode.title()})",
                    }
                )

        if d_lat is not None and d_lon is not None:
            is_final = idx == len(legs) - 1
            waypoints.append(
                {
                    "lat": d_lat,
                    "lon": d_lon,
                    "name": leg.destination.name,
                    "type": "destination" if is_final else "interchange",
                    "description": (
                        f"Destination: {leg.destination.name}"
                        if is_final
                        else f"Interchange: {leg.destination.name}"
                    ),
                }
            )

    if dest_lat is not None and dest_lon is not None:
        if not waypoints or (
            abs(waypoints[-1]["lat"] - dest_lat) > 1e-5
            or abs(waypoints[-1]["lon"] - dest_lon) > 1e-5
        ):
            waypoints.append(
                {
                    "lat": dest_lat,
                    "lon": dest_lon,
                    "name": to_name,
                    "type": "destination",
                    "description": f"Destination: {to_name}",
                }
            )

    # 7. Compute distances to next waypoint and destination
    dist_to_dest_m: Optional[float] = None
    dist_to_next_stop_m: Optional[float] = None
    if person_lat is not None and person_lon is not None:
        if dest_lat is not None and dest_lon is not None:
            dist_to_dest_m = round(
                haversine_distance(person_lat, person_lon, dest_lat, dest_lon), 1
            )

        if current_leg_index < len(serialized_legs):
            cur_l = serialized_legs[current_leg_index]
            if (
                cur_l["mode"] == "walk"
                and current_status == JourneyStepStatus.PRE_DEPARTURE
            ):
                t_lat = cur_l["origin"]["latitude"]
                t_lon = cur_l["origin"]["longitude"]
            else:
                t_lat = cur_l["destination"]["latitude"]
                t_lon = cur_l["destination"]["longitude"]

            if t_lat is not None and t_lon is not None:
                dist_to_next_stop_m = round(
                    haversine_distance(person_lat, person_lon, t_lat, t_lon), 1
                )
        elif dist_to_dest_m is not None:
            dist_to_next_stop_m = dist_to_dest_m

    # 8. Friendly status styling and messaging
    status_meta = STATUS_METADATA.get(
        current_status,
        {
            "label": "Scheduled Journey" if not is_active else "In Progress",
            "icon": "calendar_month" if not is_active else "navigation",
            "badge_colour": "slate" if not is_active else "sky",
        },
    )

    if not notification_message:
        if not is_active:
            if departure_time:
                notification_message = (
                    f"Next scheduled departure at {departure_time} from {from_name} "
                    f"to {to_name} (ETA: {expected_arrival_time})."
                )
            else:
                notification_message = (
                    f"Configured journey from {from_name} to {to_name}."
                )
        else:
            _, notification_message, _ = format_progress_notification(active)

    # 9. Next step action instruction in British English
    next_step_instruction = ""
    if current_leg_index < len(serialized_legs):
        c_leg = serialized_legs[current_leg_index]
        mode_str = c_leg["mode"].title()
        line_str = c_leg.get("line") or ""
        if line_str and mode_str.lower() in line_str.lower():
            line_display = line_str
        elif line_str:
            line_display = f"{mode_str} {line_str}"
        else:
            line_display = mode_str

        if current_status == JourneyStepStatus.PRE_DEPARTURE:
            next_step_instruction = (
                f"Prepare to depart {from_name} for the {departure_time} departure."
            )
        elif current_status == JourneyStepStatus.EN_ROUTE_TO_STOP:
            next_step_instruction = (
                f"Walk to {c_leg['destination']['name']} for connection."
            )
        elif current_status == JourneyStepStatus.AT_DEPARTURE_STOP:
            plat_str = f" from Platform {platform}" if platform else ""
            next_step_instruction = (
                f"Board {line_display} departing at {c_leg['dep_time']}{plat_str} "
                f"towards {c_leg['destination']['name']}."
            )
        elif current_status == JourneyStepStatus.ON_TRANSIT:
            next_step_instruction = (
                f"Alight at {c_leg['destination']['name']} (ETA: {c_leg['arr_time']})."
            )
        elif current_status == JourneyStepStatus.AT_INTERCHANGE:
            plat_str = f" from Platform {platform}" if platform else ""
            next_step_instruction = f"Transfer to {line_display} departing at {c_leg['dep_time']}{plat_str}."
        elif current_status == JourneyStepStatus.EN_ROUTE_TO_DESTINATION:
            next_step_instruction = (
                f"Walk to final destination {to_name} (ETA: {expected_arrival_time})."
            )
        elif current_status == JourneyStepStatus.ARRIVED:
            next_step_instruction = f"You have reached your destination: {to_name}."
    else:
        next_step_instruction = f"Journey from {from_name} to {to_name}."

    # 10. Abstract vertical schematic representation (TfL / mainline rail route diagram)
    schematic_stages: List[Dict[str, Any]] = []
    for idx, s_leg in enumerate(serialized_legs):
        is_first = idx == 0
        is_last = idx == len(serialized_legs) - 1

        is_stuart_at_origin_node = False
        if is_active:
            if is_first and current_status == JourneyStepStatus.PRE_DEPARTURE:
                is_stuart_at_origin_node = True
            elif (
                idx > 0
                and current_leg_index == idx
                and current_status
                in (
                    JourneyStepStatus.AT_DEPARTURE_STOP,
                    JourneyStepStatus.AT_INTERCHANGE,
                )
            ):
                is_stuart_at_origin_node = True

        is_stuart_on_this_leg = False
        stuart_stage_text = ""
        if is_active:
            if is_first and current_status == JourneyStepStatus.EN_ROUTE_TO_STOP:
                is_stuart_on_this_leg = True
                stuart_stage_text = "Stuart walking to departure stop"
            elif (
                current_status == JourneyStepStatus.ON_TRANSIT
                and current_leg_index == idx
            ):
                is_stuart_on_this_leg = True
                stuart_stage_text = (
                    f"Stuart on board {s_leg['line'] or s_leg['mode'].title()}"
                )
            elif (
                is_last and current_status == JourneyStepStatus.EN_ROUTE_TO_DESTINATION
            ):
                is_stuart_on_this_leg = True
                stuart_stage_text = "Stuart walking to final destination"

        mode = s_leg["mode"].lower()
        if mode == "rail":
            line_colour = "indigo"
            line_style = "solid"
        elif mode == "bus":
            line_colour = "rose"
            line_style = "solid"
        elif mode == "walk":
            line_colour = "amber"
            line_style = "dashed"
        elif mode in ("metro", "subway", "tube"):
            line_colour = "sky"
            line_style = "solid"
        elif mode == "tram":
            line_colour = "emerald"
            line_style = "solid"
        else:
            line_colour = "slate"
            line_style = "solid"

        # Delineate change / interchange to next leg
        interchange_info = None
        if not is_last and idx + 1 < len(serialized_legs):
            next_l = serialized_legs[idx + 1]
            interchange_info = {
                "station_name": s_leg["destination"]["name"],
                "transfer_from": s_leg.get("line") or s_leg["mode"].title(),
                "transfer_to": next_l.get("line") or next_l["mode"].title(),
                "next_dep_time": next_l["dep_time"],
                "next_platform": next_l["origin"]["platform"],
                "duration_minutes": max(
                    1,
                    (parse_time_to_minutes(next_l["dep_time"]) or 0)
                    - (parse_time_to_minutes(s_leg["arr_time"]) or 0),
                ),
                "is_stuart_here": (
                    is_active
                    and current_leg_index == idx + 1
                    and current_status == JourneyStepStatus.AT_INTERCHANGE
                ),
            }

        stage_data = {
            "stage_index": idx,
            "from_node": {
                "name": s_leg["origin"]["name"],
                "time": s_leg["dep_time"],
                "type": "origin" if is_first else "interchange",
                "platform": s_leg["origin"]["platform"],
                "is_stuart_here": is_stuart_at_origin_node,
            },
            "to_node": {
                "name": s_leg["destination"]["name"],
                "time": s_leg["arr_time"],
                "type": "destination" if is_last else "interchange",
                "is_stuart_here": (
                    is_active
                    and is_last
                    and current_status == JourneyStepStatus.ARRIVED
                ),
            },
            "leg": s_leg,
            "line_colour": line_colour,
            "line_style": line_style,
            "is_stuart_on_leg": is_stuart_on_this_leg,
            "stuart_status_text": stuart_stage_text,
            "interchange": interchange_info,
        }
        schematic_stages.append(stage_data)

    final_node = {
        "name": to_name,
        "time": expected_arrival_time,
        "type": "destination",
        "is_stuart_here": (is_active and current_status == JourneyStepStatus.ARRIVED),
    }

    return {
        "journeys": journeys_list,
        "selected_journey": {
            "id": target_id,
            "name": journey_name,
            "from_name": from_name,
            "from_type": from_type,
            "from_id": from_id,
            "from_coords": {"lat": origin_lat, "lon": origin_lon},
            "to_name": to_name,
            "to_type": to_type,
            "to_id": to_id,
            "to_coords": {"lat": dest_lat, "lon": dest_lon},
            "departure_time": departure_time,
            "arrival_time": expected_arrival_time,
            "is_active": is_active,
            "status": {
                "code": (
                    current_status.value
                    if isinstance(current_status, JourneyStepStatus)
                    else str(current_status)
                ),
                "label": status_meta["label"],
                "icon": status_meta["icon"],
                "badge_colour": status_meta["badge_colour"],
                "message": notification_message,
                "next_step": next_step_instruction,
            },
            "current_leg_index": current_leg_index,
            "platform": platform,
            "live_status": live_status,
            "legs": serialized_legs,
            "schematic": {
                "stages": schematic_stages,
                "final_node": final_node,
                "current_stage_index": current_leg_index,
            },
            "waypoints": waypoints,
            "route_polyline": [
                [wp["lat"], wp["lon"]]
                for wp in waypoints
                if wp.get("lat") is not None and wp.get("lon") is not None
            ],
        },
        "person": {
            "name": "Stuart",
            "state": person_status_str,
            "latitude": person_lat,
            "longitude": person_lon,
            "distance_to_next_stop_m": dist_to_next_stop_m,
            "distance_to_destination_m": dist_to_dest_m,
            "updated_at": current_dt.strftime("%H:%M:%S"),
        },
        "active": is_active,
        "timestamp": current_dt.isoformat(),
    }


__all__ = [
    "ActiveJourney",
    "JourneyStepStatus",
    "format_progress_notification",
    "resolve_live_rail_platform",
    "update_journey_progress",
    "get_journey_live_tracking_data",
]
