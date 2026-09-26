"""Unit tests for RerouteEngine service."""

import datetime
from unittest.mock import MagicMock
import pytest
from flask import Flask
from app.models.journey import Journey
from app.models.journey_route import JourneyRoute
from app.models.location import Location
from app.models.route_query_log import RouteQueryLog
from app.services.dispatcher.tracker.models import ActiveJourney
from app.services.dispatcher.tracker.session_store import load_active_journey_sessions
from app.services.reroute_engine import (
    RerouteEngine,
)


@pytest.fixture(autouse=True)
def setup_test_db(app: Flask) -> None:
    """Initialise isolated test database with app context."""
    pass


def test_check_disruption_requires_reroute() -> None:
    """Test delay threshold and disruption condition checks."""
    engine = RerouteEngine()

    # Delay under 10m does not require reroute
    req, _ = engine.check_disruption_requires_reroute(delay_minutes=9)
    assert req is False

    # Delay >= 10m requires reroute
    req, reason = engine.check_disruption_requires_reroute(delay_minutes=10)
    assert req is True
    assert "10m threshold" in reason

    req, reason = engine.check_disruption_requires_reroute(delay_minutes=18)
    assert req is True
    assert "18m" in reason

    # Cancellations require reroute
    req, reason = engine.check_disruption_requires_reroute(is_cancelled=True)
    assert req is True
    assert "cancelled" in reason.lower()

    # Broken transfer connections require reroute
    req, reason = engine.check_disruption_requires_reroute(connection_severed=True)
    assert req is True
    assert "connection severed" in reason.lower()


def test_reroute_tier1_local_failover() -> None:
    """Test Tier 1 failover to secondary local JourneyRoute template."""
    journey = Journey.create(
        name="Local Failover Commute",
        from_type="ha",
        from_id="ha:home",
        from_name="Home",
        to_type="custom",
        to_id="custom:office",
        to_name="Office",
    )

    route_primary = JourneyRoute.create(
        journey_id=journey.id,
        name="Bus 73 (Primary)",
        is_preferred=True,
        is_enabled=True,
        auto_generated=True,
        total_duration_est_minutes=30,
        transfer_count=0,
        primary_mode="bus",
    )
    route_secondary = JourneyRoute.create(
        journey_id=journey.id,
        name="Thameslink Rail (Backup)",
        is_preferred=False,
        is_enabled=True,
        auto_generated=True,
        total_duration_est_minutes=25,
        transfer_count=0,
        primary_mode="rail",
    )

    engine = RerouteEngine()
    selected_route, strategy = engine.evaluate_and_reroute(
        journey=journey,
        trigger_reason="Delay of 14m on Bus 73",
        current_route_id=route_primary.id,
    )

    assert selected_route is not None
    assert selected_route.id == route_secondary.id
    assert strategy == "local_failover"

    # Verify preference switch
    assert JourneyRoute.get_by_id(route_secondary.id).is_preferred is True
    assert JourneyRoute.get_by_id(route_primary.id).is_preferred is False

    # Verify audit log
    logs = list(
        RouteQueryLog.select().where(
            (RouteQueryLog.journey_id == journey.id)
            & (RouteQueryLog.query_type == "local_failover")
        )
    )
    assert len(logs) == 1
    assert logs[0].selected_route_id == route_secondary.id


def test_reroute_tier2_google_routes_api() -> None:
    """Test Tier 2 live Google Routes API query when no local alternatives exist."""
    Location.create(
        id="ha:home_tier2",
        name="Home",
        location_type="ha",
        latitude=51.5308,
        longitude=-0.1238,
    )
    Location.create(
        id="custom:office_tier2",
        name="Office",
        location_type="custom",
        latitude=51.5284,
        longitude=-0.1331,
    )

    journey = Journey.create(
        name="Live Cloud Reroute Commute",
        from_type="ha",
        from_id="ha:home_tier2",
        from_name="Home",
        to_type="custom",
        to_id="custom:office_tier2",
        to_name="Office",
    )

    mock_google = MagicMock()
    mock_google.compute_transit_routes.return_value = {
        "routes": [
            {
                "duration": "1080s",
                "description": "Great Northern Detour",
                "legs": [
                    {
                        "steps": [
                            {
                                "travelMode": "TRANSIT",
                                "staticDuration": "900s",
                                "transitDetails": {
                                    "stopDetails": {
                                        "departureStop": {"name": "King's Cross"},
                                        "arrivalStop": {"name": "Moorgate"},
                                    },
                                    "transitLine": {
                                        "nameShort": "GN",
                                        "vehicle": {"type": "HEAVY_RAIL"},
                                    },
                                },
                            }
                        ]
                    }
                ],
            }
        ]
    }

    engine = RerouteEngine(google_client=mock_google)
    selected_route, strategy = engine.evaluate_and_reroute(
        journey=journey,
        trigger_reason="Train cancelled at King's Cross",
        departure_time=datetime.datetime(2026, 9, 26, 8, 15, 0),
    )

    assert selected_route is not None
    assert strategy == "google_reroute"
    assert selected_route.name == "Great Northern Detour"
    assert selected_route.is_preferred is True

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
    """Test that executing a reroute flushes the updated session to SQLite settings table."""
    journey = Journey.create(
        name="Session Commute",
        from_type="ha",
        from_id="ha:home_session",
        from_name="Home",
        to_type="custom",
        to_id="custom:office_session",
        to_name="Office",
    )

    route_backup = JourneyRoute.create(
        journey_id=journey.id,
        name="Metro Backup",
        is_preferred=False,
        is_enabled=True,
        auto_generated=True,
        total_duration_est_minutes=20,
        primary_mode="metro",
    )

    active_session = ActiveJourney(
        journey_id=journey.id,
        journey_name=journey.name,
        from_type=journey.from_type,
        from_id=journey.from_id,
        to_type=journey.to_type,
        to_id=journey.to_id,
        delay_minutes=15,
        delay_reason="Train signal failure",
    )

    engine = RerouteEngine()
    new_route, strategy = engine.evaluate_and_reroute(
        journey=journey,
        trigger_reason="Train delay of 15m",
        active_session=active_session,
    )

    assert new_route.id == route_backup.id
    assert strategy == "local_failover"

    # Verify persisted in SQLite settings
    sessions = load_active_journey_sessions()
    assert journey.id in sessions
    persisted_session = sessions[journey.id]
    assert "Rerouted: Metro Backup" in persisted_session.delay_reason
    assert persisted_session.delay_minutes == 0
