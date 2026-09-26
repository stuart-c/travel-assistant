"""Corridor learner service for discovering, parsing, auditing, and persisting transit routes."""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.datasources.exceptions import DataSourceConfigError
from app.datasources.google_maps import GoogleMapsClient
from app.models.journey import Journey
from app.models.journey_route import JourneyRoute
from app.models.route_query_log import RouteQueryLog
from app.models.transit import Stop
from app.models.walking import Walking
from app.utils.geo import resolve_endpoint_coordinates

logger = logging.getLogger(__name__)

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


def parse_duration_seconds(duration_str: Optional[str]) -> int:
    """Parse Google API duration string (e.g. '1680s') into integer seconds."""
    if not duration_str:
        return 0
    digits = re.sub(r"[^\d]", "", str(duration_str))
    try:
        return int(digits)
    except ValueError:
        return 0


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
    except Exception as exc:
        logger.debug("Could not ensure walking connection: %s", exc)


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
        replace_existing: bool = True,
    ) -> List[JourneyRoute]:
        """Discover transit routes via Google Routes API, audit query, and persist templates.

        Args:
            journey: Journey model to discover routes for.
            query_type: Classification of the routing query.
            trigger_reason: Explanatory trigger reason for the audit log.
            departure_time: Optional departure datetime or RFC3339 string.
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

        if origin_lat is None or origin_lng is None:
            logger.warning(
                "Cannot compute routes for journey %d: origin coordinates unresolved.",
                journey.id,
            )
            return []
        if dest_lat is None or dest_lng is None:
            logger.warning(
                "Cannot compute routes for journey %d: destination coordinates unresolved.",
                journey.id,
            )
            return []

        client = self.get_client()
        try:
            raw_response = client.compute_transit_routes(
                origin=(origin_lat, origin_lng),
                destination=(dest_lat, dest_lng),
                departure_time=departure_time,
                compute_alternative_routes=True,
            )
        except DataSourceConfigError:
            logger.info(
                "Google Maps API key not configured. Skipping corridor discovery."
            )
            return []
        except Exception as exc:
            logger.warning(
                "Failed to compute transit routes via Google Routes API for journey %d: %s",
                journey.id,
                exc,
            )
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
                departure_time=str(departure_time) if departure_time else None,
                raw_response=raw_response,
                parsed_summary=[],
            )
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
            departure_time=str(departure_time) if departure_time else None,
            raw_response=raw_response,
            parsed_summary=[],
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

        for route_idx, route in enumerate(routes):
            total_duration_sec = parse_duration_seconds(route.get("duration"))
            total_duration_mins = max(1, total_duration_sec // 60)
            route_desc = route.get("description", "").strip()

            legs_data: List[Dict[str, Any]] = []
            transit_modes_used: List[str] = []
            transit_count = 0

            route_legs = route.get("legs", [])
            stage_idx = 1
            step_idx = 1

            prev_endpoint_type = journey.from_type
            prev_endpoint_id = journey.from_id
            prev_endpoint_name = origin_name or journey.from_name

            for r_leg in route_legs:
                for step in r_leg.get("steps", []):
                    travel_mode = str(step.get("travelMode", "")).upper()
                    step_dur_sec = parse_duration_seconds(step.get("staticDuration"))
                    step_dur_mins = (
                        max(1, round(step_dur_sec / 60)) if step_dur_sec else 1
                    )
                    step_dist_m = int(step.get("distanceMeters", 0))

                    if travel_mode == "TRANSIT":
                        transit_count += 1
                        transit_details = step.get("transitDetails", {})
                        stop_details = transit_details.get("stopDetails", {})
                        dep_stop_raw = stop_details.get("departureStop", {})
                        arr_stop_raw = stop_details.get("arrivalStop", {})

                        line_info = transit_details.get("transitLine", {})
                        line_name = (
                            line_info.get("nameShort")
                            or line_info.get("name")
                            or "Transit"
                        )
                        agency = line_info.get("transitAgency", {}).get("name")
                        vehicle_type = line_info.get("vehicle", {}).get("type")
                        canonical_mode = map_vehicle_type(vehicle_type)
                        transit_modes_used.append(canonical_mode)

                        dep_lat = (
                            dep_stop_raw.get("location", {})
                            .get("latLng", {})
                            .get("latitude")
                        )
                        dep_lng = (
                            dep_stop_raw.get("location", {})
                            .get("latLng", {})
                            .get("longitude")
                        )
                        arr_lat = (
                            arr_stop_raw.get("location", {})
                            .get("latLng", {})
                            .get("latitude")
                        )
                        arr_lng = (
                            arr_stop_raw.get("location", {})
                            .get("latLng", {})
                            .get("longitude")
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
                        legs_data.append(leg_dict)
                        prev_endpoint_type = arr_type
                        prev_endpoint_id = arr_id
                        prev_endpoint_name = arr_name

                    else:
                        # Walking or other movement step
                        next_type = journey.to_type
                        next_id = journey.to_id
                        next_name = dest_name or journey.to_name

                        # If next step is transit, peek ahead for next boarding stop
                        step_idx_in_leg = r_leg.get("steps", []).index(step)
                        if step_idx_in_leg + 1 < len(r_leg.get("steps", [])):
                            next_step = r_leg.get("steps", [])[step_idx_in_leg + 1]
                            if (
                                str(next_step.get("travelMode", "")).upper()
                                == "TRANSIT"
                            ):
                                n_dep = (
                                    next_step.get("transitDetails", {})
                                    .get("stopDetails", {})
                                    .get("departureStop", {})
                                )
                                n_lat = (
                                    n_dep.get("location", {})
                                    .get("latLng", {})
                                    .get("latitude")
                                )
                                n_lng = (
                                    n_dep.get("location", {})
                                    .get("latLng", {})
                                    .get("longitude")
                                )
                                next_type, next_id, next_name = resolve_or_create_stop(
                                    n_dep.get("name", "Transit Stop"), n_lat, n_lng
                                )

                        leg_dict = {
                            "stage_index": stage_idx,
                            "step_index": step_idx,
                            "leg_type": "walk",
                            "from_type": prev_endpoint_type,
                            "from_id": prev_endpoint_id,
                            "from_name": prev_endpoint_name,
                            "to_type": next_type,
                            "to_id": next_id,
                            "to_name": next_name,
                            "duration_minutes": step_dur_mins,
                            "distance_m": step_dist_m,
                        }
                        legs_data.append(leg_dict)
                        ensure_walking_connection(
                            prev_endpoint_type,
                            prev_endpoint_id,
                            prev_endpoint_name,
                            next_type,
                            next_id,
                            next_name,
                            step_dur_mins,
                            step_dist_m,
                        )
                        prev_endpoint_type = next_type
                        prev_endpoint_id = next_id
                        prev_endpoint_name = next_name

                    stage_idx += 1
                    step_idx += 1

            primary_mode = transit_modes_used[0] if transit_modes_used else "bus"
            transfer_count = max(0, transit_count - 1)
            route_name = route_desc or f"{primary_mode.title()} Route {route_idx + 1}"

            # Format human-readable summary
            summary_parts = []
            for l_item in legs_data:
                if l_item.get("leg_type") == "transit":
                    summary_parts.append(
                        f"{l_item.get('transport_mode', '').title()} {l_item.get('line_name', '')}"
                    )
                else:
                    summary_parts.append(f"Walk ({l_item.get('duration_minutes', 1)}m)")
            summary_text = " → ".join(summary_parts)

            saved_route = JourneyRoute.create(
                journey_id=journey.id,
                name=route_name,
                is_preferred=(route_idx == 0),
                is_enabled=True,
                auto_generated=True,
                total_duration_est_minutes=total_duration_mins,
                transfer_count=transfer_count,
                stages_count=len(legs_data),
                primary_mode=primary_mode,
                legs=legs_data,
                active_days=active_days,
                summary_text=summary_text,
            )
            persisted_routes.append(saved_route)
            parsed_summary.append(
                {
                    "route_id": saved_route.id,
                    "name": route_name,
                    "duration_minutes": total_duration_mins,
                    "primary_mode": primary_mode,
                    "transfer_count": transfer_count,
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
