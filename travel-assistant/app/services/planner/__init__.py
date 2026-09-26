"""Journey Planner Service Package.

Provides multi-modal topological route discovery (Mode 1) and
concrete scheduled itinerary planning (Mode 2) using pure SQLite database tables.
"""

from app.services.planner.exceptions import (
    InvalidEndpointError,
    JourneyPlanningError,
    JourneyPlanningErrorCode,
    NoAccessStopsError,
    NoCorridorPathError,
    NoServicesOnDayError,
    NoTripsInWindowError,
)
from app.services.planner.models import (
    ItineraryEndpoint,
    ItineraryLeg,
    ScheduledItinerary,
)
from app.services.planner.raptor import plan_journey
from app.services.planner.transfers import (
    DAY_NAME_TO_CODE,
    VALID_DAYS,
    extract_route_base_name,
    format_minutes_to_time,
    get_access_edges,
    get_active_timetables,
    normalise_id,
    parse_time_to_minutes,
    resolve_active_days_and_date,
    resolve_endpoint_name,
    resolve_transfer_duration,
)

__all__ = [
    # Solvers
    "plan_journey",
    "extract_route_base_name",
    # Models
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
    "get_active_timetables",
    "get_access_edges",
    "VALID_DAYS",
    "DAY_NAME_TO_CODE",
]
