"""Journey Planner Service Facade.

Unifies topological route discovery (Mode 1) and concrete scheduled
itinerary planning (Mode 2) using modular sub-components.
"""

from app.services.exceptions import (
    InvalidEndpointError,
    JourneyPlanningError,
    JourneyPlanningErrorCode,
    NoAccessStopsError,
    NoCorridorPathError,
    NoServicesOnDayError,
    NoTripsInWindowError,
)
from app.services.models import (
    ItineraryEndpoint,
    ItineraryLeg,
    RouteLeg,
    RouteTemplate,
    ScheduledItinerary,
)
from app.services.raptor import plan_journey
from app.services.route_finder import find_routes, prune_route_templates
from app.services.transfers import (
    DAY_NAME_TO_CODE,
    VALID_DAYS,
    format_minutes_to_time,
    get_access_edges,
    is_timetable_active,
    normalise_id,
    parse_time_to_minutes,
    resolve_active_days_and_date,
    resolve_endpoint_name,
    resolve_transfer_duration,
)

__all__ = [
    # Solvers
    "find_routes",
    "plan_journey",
    "prune_route_templates",
    # Models
    "RouteTemplate",
    "RouteLeg",
    "ScheduledItinerary",
    "ItineraryLeg",
    "ItineraryEndpoint",
    # Exceptions
    "JourneyPlanningError",
    "JourneyPlanningErrorCode",
    "InvalidEndpointError",
    "NoAccessStopsError",
    "NoCorridorPathError",
    "NoServicesOnDayError",
    "NoTripsInWindowError",
    # Transfer & Date utilities
    "parse_time_to_minutes",
    "format_minutes_to_time",
    "normalise_id",
    "resolve_endpoint_name",
    "resolve_transfer_duration",
    "resolve_active_days_and_date",
    "is_timetable_active",
    "get_access_edges",
    "VALID_DAYS",
    "DAY_NAME_TO_CODE",
]
