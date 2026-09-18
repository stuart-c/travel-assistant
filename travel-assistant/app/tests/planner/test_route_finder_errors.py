"""Unit tests for journey planner exception hierarchy and error handling."""

from __future__ import annotations

from flask import Flask
import pytest

from app.services.planner.exceptions import (
    InvalidEndpointError,
    JourneyPlanningError,
    JourneyPlanningErrorCode,
    NoAccessStopsError,
    NoCorridorPathError,
    NoServicesOnDayError,
    NoTripsInWindowError,
)
from app.services.planner.raptor import plan_journey
from app.services.planner.route_finder import find_routes


def test_error_invalid_endpoints(seeded_planner: Flask) -> None:
    """Verify InvalidEndpointError and same origin/destination errors."""
    with seeded_planner.app_context():
        with pytest.raises(InvalidEndpointError):
            find_routes("", "", "rail", "9100EUSTON")

        with pytest.raises(JourneyPlanningError) as exc_info:
            find_routes("rail", "9100EUSTON", "rail", "9100EUSTON")
        assert exc_info.value.code == JourneyPlanningErrorCode.SAME_ORIGIN_DESTINATION


def test_error_no_access_stops(seeded_planner: Flask) -> None:
    """Verify NoAccessStopsError when endpoint has no walking connections."""
    with seeded_planner.app_context():
        with pytest.raises(NoAccessStopsError) as exc_info:
            find_routes("custom", "custom:isolated_spot", "rail", "9100EUSTON")
        assert exc_info.value.code == JourneyPlanningErrorCode.NO_ACCESS_STOPS
        assert "isolated_spot" in exc_info.value.message


def test_error_no_corridor_path(seeded_planner: Flask) -> None:
    """Verify NoCorridorPathError when no transit services connect the access stops."""
    with seeded_planner.app_context():
        with pytest.raises(NoCorridorPathError) as exc_info:
            find_routes("rail", "9100FPK", "rail", "9100MNCR", days_of_week=["mon"])
        assert exc_info.value.code == JourneyPlanningErrorCode.NO_CORRIDOR_PATH


def test_error_no_services_on_day(seeded_planner: Flask) -> None:
    """Verify NoServicesOnDayError or NoCorridorPathError on non-operating days (e.g. Sunday for Bus 73)."""
    with seeded_planner.app_context():
        with pytest.raises((NoServicesOnDayError, NoCorridorPathError)):
            plan_journey(
                from_type="ha",
                from_id="ha:home",
                to_type="ha",
                to_id="ha:work",
                days_of_week=["sun"],
            )


def test_error_no_trips_in_window(seeded_planner: Flask) -> None:
    """Verify NoTripsInWindowError when corridor exists but window has no departures."""
    with seeded_planner.app_context():
        with pytest.raises(NoTripsInWindowError) as exc_info:
            plan_journey(
                from_type="rail",
                from_id="9100EUSTON",
                to_type="rail",
                to_id="9100MNCR",
                timing_mode="depart",
                time_str="14:00",  # Trip is at 09:00 only
                days_of_week=["mon"],
            )
        assert exc_info.value.code == JourneyPlanningErrorCode.NO_TRIPS_IN_WINDOW


def test_journey_planning_error_to_dict() -> None:
    """Verify error serialization via to_dict()."""
    err = JourneyPlanningError(
        JourneyPlanningErrorCode.NO_CORRIDOR_PATH,
        "Custom error message",
        {"detail": 123},
    )
    d = err.to_dict()
    assert d["error_code"] == "NO_CORRIDOR_PATH"
    assert d["message"] == "Custom error message"
    assert d["diagnostics"] == {"detail": 123}
