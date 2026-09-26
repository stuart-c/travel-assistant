"""Services package for Travel Assistant."""

from app.services.planner import (
    DAY_NAME_TO_CODE,
    VALID_DAYS,
    InvalidEndpointError,
    ItineraryEndpoint,
    ItineraryLeg,
    JourneyPlanningError,
    JourneyPlanningErrorCode,
    NoAccessStopsError,
    NoCorridorPathError,
    NoServicesOnDayError,
    NoTripsInWindowError,
    ScheduledItinerary,
    format_minutes_to_time,
    get_access_edges,
    get_active_timetables,
    normalise_id,
    parse_time_to_minutes,
    plan_journey,
    resolve_active_days_and_date,
    resolve_endpoint_name,
    resolve_transfer_duration,
)

__all__ = [
    # Solvers
    "plan_journey",
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
