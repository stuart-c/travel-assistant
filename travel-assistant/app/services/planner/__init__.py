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
from app.services.planner.dynamic_planner import (
    DynamicRoutePlanner,
    resolve_target_commute_datetime,
)
from app.services.planner.raptor import plan_journey
from app.services.planner.transfers import (
    extract_route_base_name,
    get_access_edges,
    get_active_timetables,
    normalise_id,
    resolve_active_days_and_date,
    resolve_endpoint_name,
)

__all__ = [
    # Solvers
    "DynamicRoutePlanner",
    "resolve_target_commute_datetime",
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
    "normalise_id",
    "resolve_endpoint_name",
    "resolve_active_days_and_date",
    "get_active_timetables",
    "get_access_edges",
]
