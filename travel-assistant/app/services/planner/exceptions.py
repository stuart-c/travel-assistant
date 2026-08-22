"""Domain exceptions for Journey Planning operations."""

from enum import Enum
from typing import Any, Dict, Optional


class JourneyPlanningErrorCode(str, Enum):
    """Machine-readable error codes for journey planning failures."""

    INVALID_ENDPOINT = "INVALID_ENDPOINT"
    SAME_ORIGIN_DESTINATION = "SAME_ORIGIN_DESTINATION"
    NO_ACCESS_STOPS = "NO_ACCESS_STOPS"
    NO_CORRIDOR_PATH = "NO_CORRIDOR_PATH"
    NO_SERVICES_ON_DAY = "NO_SERVICES_ON_DAY"
    NO_TRIPS_IN_WINDOW = "NO_TRIPS_IN_WINDOW"
    UNSATISFIED_ARRIVE_BY = "UNSATISFIED_ARRIVE_BY"


class JourneyPlanningError(Exception):
    """Base domain exception raised when a journey route or plan cannot be computed."""

    def __init__(
        self,
        code: JourneyPlanningErrorCode,
        message: str,
        diagnostics: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.diagnostics = diagnostics or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert error to a structured dictionary representation."""
        return {
            "error_code": self.code.value,
            "message": self.message,
            "diagnostics": self.diagnostics,
        }


class InvalidEndpointError(JourneyPlanningError):
    """Raised when an origin or destination endpoint cannot be resolved."""

    def __init__(
        self, message: str, diagnostics: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(
            JourneyPlanningErrorCode.INVALID_ENDPOINT, message, diagnostics
        )


class NoAccessStopsError(JourneyPlanningError):
    """Raised when origin or destination has no reachable transit stops or walking paths."""

    def __init__(
        self, message: str, diagnostics: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(JourneyPlanningErrorCode.NO_ACCESS_STOPS, message, diagnostics)


class NoCorridorPathError(JourneyPlanningError):
    """Raised when no continuous multi-modal corridor connects origin and destination."""

    def __init__(
        self, message: str, diagnostics: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(
            JourneyPlanningErrorCode.NO_CORRIDOR_PATH, message, diagnostics
        )


class NoServicesOnDayError(JourneyPlanningError):
    """Raised when transit services do not operate on the requested day of the week."""

    def __init__(
        self, message: str, diagnostics: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(
            JourneyPlanningErrorCode.NO_SERVICES_ON_DAY, message, diagnostics
        )


class NoTripsInWindowError(JourneyPlanningError):
    """Raised when corridors exist but no scheduled trips run within the requested time window."""

    def __init__(
        self, message: str, diagnostics: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(
            JourneyPlanningErrorCode.NO_TRIPS_IN_WINDOW, message, diagnostics
        )


__all__ = [
    "JourneyPlanningErrorCode",
    "JourneyPlanningError",
    "InvalidEndpointError",
    "NoAccessStopsError",
    "NoCorridorPathError",
    "NoServicesOnDayError",
    "NoTripsInWindowError",
]
