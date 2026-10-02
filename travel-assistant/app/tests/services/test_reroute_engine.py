"""Unit tests for RerouteEngine dynamic transit rerouting service."""

import datetime
from unittest.mock import MagicMock
import pytest
from flask import Flask

from app.models.journey import Journey
from app.models.location import Location
from app.models.route_query_log import RouteQueryLog
from app.models.setting import Setting
from app.services.dispatcher.tracker.models import ActiveJourney
from app.services.dispatcher.tracker.session_store import load_active_journey_sessions
from app.services.planner.dynamic_planner import DynamicRoutePlanner
from app.services.reroute_engine import RerouteEngine


@pytest.fixture(autouse=True)
def setup_test_db(app: Flask) -> None:
    """Initialise isolated test database with app context."""
    pass


def test_check_disruption_requires_reroute() -> None:
    """Test delay threshold, cancellation, and sensitivity condition checks."""
    engine = RerouteEngine()

    # Default medium sensitivity: delay under 10m does not require reroute
    req, _ = engine.check_disruption_requires_reroute(delay_minutes=9)
    assert req is False

    # Delay >= 10m requires reroute
    req, reason = engine.check_disruption_requires_reroute(delay_minutes=10)
    assert req is True
    assert "10m threshold" in reason

    req, reason = engine.check_disruption_requires_reroute(delay_minutes=18)
    assert req is True
    assert "18m" in reason

    # Cancellations require immediate reroute
    req, reason = engine.check_disruption_requires_reroute(is_cancelled=True)
    assert req is True
    assert "cancelled" in reason.lower()

    # Broken transfer connections require reroute
    req, reason = engine.check_disruption_requires_reroute(connection_severed=True)
    assert req is True
    assert "connection severed" in reason.lower()

    # High sensitivity setting (5m delay threshold)
    Setting.set_val("reroute_sensitivity", "high")
    req_high, reason_high = engine.check_disruption_requires_reroute(delay_minutes=6)
    assert req_high is True
    assert "5m threshold" in reason_high

    # Low sensitivity setting (15m delay threshold)
    Setting.set_val("reroute_sensitivity", "low")
    req_low, _ = engine.check_disruption_requires_reroute(delay_minutes=12)
    assert req_low is False
    req_low_hit, reason_low = engine.check_disruption_requires_reroute(delay_minutes=16)
    assert req_low_hit is True
    assert "15m threshold" in reason_low

    # Reset setting
    Setting.set_val("reroute_sensitivity", "medium")


def test_reroute_dynamic_planning() -> None:
    """Test dynamic live rerouting via Google Routes API and audit logging."""
    Location.create(
        id="ha:home_reroute",
        name="London King's Cross Residence",
        location_type="ha",
        latitude=51.5308,
        longitude=-0.1238,
    )
    Location.create(
        id="custom:office_reroute",
        name="Old Street Tech Hub",
        location_type="custom",
        latitude=51.5255,
        longitude=-0.0875,
    )

    journey = Journey.create(
        name="London Morning Commute",
        from_type="ha",
        from_id="ha:home_reroute",
        from_name="London King's Cross Residence",
        to_type="custom",
        to_id="custom:office_reroute",
        to_name="Old Street Tech Hub",
    )

    mock_google = MagicMock()
    mock_google.compute_transit_routes.return_value = {
        "routes": [
            {
                "duration": "1080s",
                "description": "Northern Line Detour",
                "legs": [
                    {
                        "steps": [
                            {
                                "travelMode": "TRANSIT",
                                "staticDuration": "900s",
                                "transitDetails": {
                                    "stopDetails": {
                                        "departureStop": {
                                            "name": "King's Cross St. Pancras"
                                        },
                                        "arrivalStop": {"name": "Old Street"},
                                        "departureTime": "2026-10-02T08:15:00Z",
                                        "arrivalTime": "2026-10-02T08:30:00Z",
                                    },
                                    "transitLine": {
                                        "nameShort": "Northern",
                                        "vehicle": {"type": "SUBWAY"},
                                    },
                                },
                            }
                        ]
                    }
                ],
            }
        ]
    }

    planner = DynamicRoutePlanner(google_client=mock_google)
    engine = RerouteEngine(google_client=mock_google, dynamic_planner=planner)

    selected_itin, strategy = engine.evaluate_and_reroute(
        journey=journey,
        trigger_reason="Train cancelled at King's Cross",
        departure_time=datetime.datetime(2026, 10, 2, 8, 10, 0),
    )

    assert selected_itin is not None
    assert strategy == "dynamic_reroute"
    assert len(selected_itin.legs) >= 1
    assert selected_itin.legs[0].line == "Northern"

    # Verify query logged with delay_reroute query_type
    logs = list(
        RouteQueryLog.select().where(
            (RouteQueryLog.journey_id == journey.id)
            & (RouteQueryLog.query_type == "delay_reroute")
        )
    )
    assert len(logs) == 1
    assert "Train cancelled" in logs[0].trigger_reason


def test_reroute_updates_active_journey_session() -> None:
    """Test that executing a dynamic reroute updates the active session with new legs and resets delay."""
    Location.create(
        id="ha:home_session",
        name="London King's Cross Residence",
        location_type="ha",
        latitude=51.5308,
        longitude=-0.1238,
    )
    Location.create(
        id="custom:office_session",
        name="London Euston Offices",
        location_type="custom",
        latitude=51.5284,
        longitude=-0.1331,
    )

    journey = Journey.create(
        name="Active Session Commute",
        from_type="ha",
        from_id="ha:home_session",
        from_name="London King's Cross Residence",
        to_type="custom",
        to_id="custom:office_session",
        to_name="London Euston Offices",
    )

    mock_google = MagicMock()
    mock_google.compute_transit_routes.return_value = {
        "routes": [
            {
                "duration": "720s",
                "description": "Bus 73 Detour",
                "legs": [
                    {
                        "steps": [
                            {
                                "travelMode": "TRANSIT",
                                "staticDuration": "600s",
                                "transitDetails": {
                                    "stopDetails": {
                                        "departureStop": {
                                            "name": "King's Cross Station"
                                        },
                                        "arrivalStop": {"name": "Euston Station"},
                                        "departureTime": "2026-10-02T08:20:00Z",
                                        "arrivalTime": "2026-10-02T08:30:00Z",
                                    },
                                    "transitLine": {
                                        "nameShort": "73",
                                        "vehicle": {"type": "BUS"},
                                    },
                                },
                            }
                        ]
                    }
                ],
            }
        ]
    }

    active_session = ActiveJourney(
        journey_id=journey.id,
        journey_name=journey.name,
        from_type=journey.from_type,
        from_id=journey.from_id,
        to_type=journey.to_type,
        to_id=journey.to_id,
        delay_minutes=15,
        delay_reason="Original service cancelled",
    )

    planner = DynamicRoutePlanner(google_client=mock_google)
    engine = RerouteEngine(google_client=mock_google, dynamic_planner=planner)

    new_itin, strategy = engine.evaluate_and_reroute(
        journey=journey,
        trigger_reason="Train delay of 15m",
        active_session=active_session,
    )

    assert new_itin is not None
    assert strategy == "dynamic_reroute"

    # Verify session was updated and persisted in SQLite settings
    sessions = load_active_journey_sessions()
    assert journey.id in sessions
    persisted = sessions[journey.id]
    assert "Rerouted: Train delay of 15m" in persisted.delay_reason
    assert persisted.delay_minutes == 0
    assert len(persisted.legs) >= 1
