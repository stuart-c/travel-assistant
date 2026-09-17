"""Live tracking telemetry compilation, geographic waypoints, and schematic diagrams."""

import datetime
from typing import Any, Dict, Optional

from app.datasources.homeassistant import HomeAssistantClient
from app.datasources.train_live import TrainLiveClient
from app.models.journey import Journey
from app.services.dispatcher.tracker.models import (
    FOOT_MODES,
    ActiveJourney,
    ItineraryEndpoint,
    ItineraryLeg,
    JourneyStepStatus,
)
from app.services.dispatcher.tracker.notification_formatter import (
    format_progress_notification,
)
from app.services.dispatcher.tracker.platform_service import (
    resolve_live_rail_platform,
)
from app.services.dispatcher.tracker.schematic_builder import (
    STATUS_METADATA,
    _build_next_step_instruction,
    _build_schematic_stages,
)
from app.services.dispatcher.tracker.waypoint_builder import (
    _TRACKING_CACHE_TTL_SECONDS,
    _UPCOMING_ITINERARY_CACHE,
    _build_waypoints_and_legs,
    _plan_upcoming_itinerary_cached,
    _resolve_person_location,
    _resolve_target_journey_id,
    clear_tracking_cache,
)
from app.utils.geo import haversine_distance_m


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
    target_id = _resolve_target_journey_id(
        journey_id,
        journeys_list,
        current_active_journeys,
        all_journeys,
        current_dt,
    )
    if target_id is None:
        return {
            "journeys": [],
            "selected_journey": None,
            "person": None,
            "active": False,
            "timestamp": current_dt.isoformat(),
        }

    # 4. Query Stuart's current position from Home Assistant
    person_lat, person_lon, person_status_str = _resolve_person_location(ha_client)

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

        upcoming_itinerary = _plan_upcoming_itinerary_cached(
            target_id, j_obj, current_dt
        )
        if upcoming_itinerary:
            legs = list(upcoming_itinerary.legs)
            departure_time = upcoming_itinerary.departure_time
            expected_arrival_time = upcoming_itinerary.arrival_time
        else:
            legs = []
            departure_time = ""
            expected_arrival_time = ""
            calc_routes = j_obj.get_calculated_routes()
            if calc_routes and isinstance(calc_routes, list):
                primary_route = calc_routes[0]
                route_legs = (
                    primary_route.get("legs", [])
                    if isinstance(primary_route, dict)
                    else getattr(primary_route, "legs", [])
                )
                for r_idx, r_leg in enumerate(route_legs):
                    r_leg_dict = (
                        r_leg
                        if isinstance(r_leg, dict)
                        else (
                            r_leg.model_dump()
                            if hasattr(r_leg, "model_dump")
                            else dict(r_leg)
                        )
                    )
                    mode = (
                        r_leg_dict.get("transport_mode")
                        or r_leg_dict.get("leg_type")
                        or "walk"
                    )
                    legs.append(
                        ItineraryLeg(
                            leg_index=r_idx,
                            mode=mode,
                            origin=ItineraryEndpoint(
                                id=str(r_leg_dict.get("from_id", "")),
                                name=str(r_leg_dict.get("from_name", "")),
                            ),
                            destination=ItineraryEndpoint(
                                id=str(r_leg_dict.get("to_id", "")),
                                name=str(r_leg_dict.get("to_name", "")),
                            ),
                            dep_time="",
                            arr_time="",
                            duration_minutes=int(
                                r_leg_dict.get("duration_minutes") or 0
                            ),
                            line=r_leg_dict.get("line_name"),
                            operator=r_leg_dict.get("operator_name"),
                        )
                    )

    # Check live rail platform if applicable
    target_rail_leg = None
    if current_leg_index < len(legs):
        cur_leg = legs[current_leg_index]
        if cur_leg.mode == "rail":
            target_rail_leg = cur_leg
        elif cur_leg.mode in FOOT_MODES:
            target_rail_leg = next(
                (lg for lg in legs[current_leg_index:] if lg.mode == "rail"),
                None,
            )

    if target_rail_leg and live_client:
        live_res = resolve_live_rail_platform(
            origin_id=target_rail_leg.origin.id,
            dest_id=target_rail_leg.destination.id,
            scheduled_time=target_rail_leg.dep_time,
            live_client=live_client,
        )
        if live_res.platform:
            platform = live_res.platform
        if live_res.etd:
            live_status = live_res.etd

    # 6. Resolve coordinates and build waypoints
    (
        origin_lat,
        origin_lon,
        dest_lat,
        dest_lon,
        serialized_legs,
        waypoints,
    ) = _build_waypoints_and_legs(
        legs=legs,
        current_leg_index=current_leg_index,
        platform=platform,
        is_active=is_active,
        from_name=from_name,
        from_type=from_type,
        from_id=from_id,
        to_name=to_name,
        to_type=to_type,
        to_id=to_id,
    )

    # 7. Compute distances to next waypoint and destination
    dist_to_dest_m: Optional[float] = None
    dist_to_next_stop_m: Optional[float] = None
    if person_lat is not None and person_lon is not None:
        if dest_lat is not None and dest_lon is not None:
            dist_to_dest_m = round(
                haversine_distance_m(person_lat, person_lon, dest_lat, dest_lon),
                1,
            )

        if current_leg_index < len(serialized_legs):
            cur_l = serialized_legs[current_leg_index]
            if (
                cur_l["mode"] in FOOT_MODES
                and current_status == JourneyStepStatus.PRE_DEPARTURE
            ):
                t_lat = cur_l["origin"]["latitude"]
                t_lon = cur_l["origin"]["longitude"]
            else:
                t_lat = cur_l["destination"]["latitude"]
                t_lon = cur_l["destination"]["longitude"]

            if t_lat is not None and t_lon is not None:
                dist_to_next_stop_m = round(
                    haversine_distance_m(person_lat, person_lon, t_lat, t_lon),
                    1,
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
                notification_message = f"Scheduled route from {from_name} to {to_name}."
        else:
            _, notification_message, _ = format_progress_notification(active)

    # 9. Next step action instruction in British English
    next_step_instruction = _build_next_step_instruction(
        current_leg_index=current_leg_index,
        serialized_legs=serialized_legs,
        current_status=current_status,
        from_name=from_name,
        to_name=to_name,
        departure_time=departure_time,
        expected_arrival_time=expected_arrival_time,
        platform=platform,
    )

    # 10. Abstract vertical schematic representation
    schematic_stages = _build_schematic_stages(
        serialized_legs=serialized_legs,
        is_active=is_active,
        current_status=current_status,
        current_leg_index=current_leg_index,
    )

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
    "_TRACKING_CACHE_TTL_SECONDS",
    "_UPCOMING_ITINERARY_CACHE",
    "STATUS_METADATA",
    "clear_tracking_cache",
    "get_journey_live_tracking_data",
]
