"""Unit tests for JourneyRoute and RouteQueryLog models."""

import pytest
from flask import Flask
from app.models.journey import Journey
from app.models.journey_route import JourneyRoute
from app.models.route_query_log import RouteQueryLog


@pytest.fixture(autouse=True)
def setup_test_db(app: Flask) -> None:
    """Initialise test SQLite isolated database with required models."""
    pass


def test_journey_route_crud() -> None:
    """Test creating, reading, updating, and querying JourneyRoute records."""
    journey = Journey.create(
        name="Morning Commute",
        from_type="ha",
        from_id="ha:home",
        from_name="Home",
        to_type="custom",
        to_id="custom:office",
        to_name="Office",
    )

    legs_data = [
        {
            "stage_index": 1,
            "step_index": 1,
            "leg_type": "walk",
            "from_name": "Home",
            "to_name": "King's Cross Station (Stop E)",
            "duration_minutes": 8,
            "distance_m": 520,
        },
        {
            "stage_index": 2,
            "step_index": 2,
            "leg_type": "transit",
            "transport_mode": "bus",
            "line_name": "73",
            "from_name": "King's Cross Station (Stop E)",
            "to_name": "Euston Station (Stop C)",
            "duration_minutes": 14,
        },
        {
            "stage_index": 3,
            "step_index": 3,
            "leg_type": "walk",
            "from_name": "Euston Station (Stop C)",
            "to_name": "Office",
            "duration_minutes": 6,
            "distance_m": 410,
        },
    ]

    route = JourneyRoute.create(
        journey_id=journey.id,
        name="Bus 73 via Euston",
        is_preferred=True,
        is_enabled=True,
        auto_generated=True,
        total_duration_est_minutes=28,
        transfer_count=0,
        stages_count=3,
        primary_mode="bus",
        legs=legs_data,
        active_days=["mon", "tue", "wed", "thu", "fri"],
        summary_text="Walk to King's Cross, Bus 73 to Euston, Walk to Office",
    )

    assert route.id is not None
    fetched = JourneyRoute.get_by_id(route.id)
    assert fetched.name == "Bus 73 via Euston"
    assert fetched.is_preferred is True
    assert fetched.total_duration_est_minutes == 28
    assert len(fetched.legs) == 3
    assert fetched.legs[1]["line_name"] == "73"
    assert fetched.active_days == ["mon", "tue", "wed", "thu", "fri"]


def test_route_query_log_crud() -> None:
    """Test creating and retrieving RouteQueryLog audit entries."""
    journey = Journey.create(
        name="Audit Commute",
        from_type="ha",
        from_id="ha:home",
        from_name="Home",
        to_type="custom",
        to_id="custom:office",
        to_name="Office",
    )

    raw_response = {
        "routes": [
            {
                "duration": "1680s",
                "description": "Bus 73",
                "legs": [{"steps": [{"travelMode": "TRANSIT"}]}],
            }
        ]
    }
    parsed_summary = [{"route_index": 0, "duration_minutes": 28, "primary_mode": "bus"}]

    log_entry = RouteQueryLog.create(
        journey_id=journey.id,
        query_type="initial_discovery",
        trigger_reason="automated_journey_creation",
        origin_lat=51.5308,
        origin_lng=-0.1238,
        dest_lat=51.5284,
        dest_lng=-0.1331,
        departure_time="2026-09-26T08:30:00Z",
        raw_response=raw_response,
        parsed_summary=parsed_summary,
    )

    assert log_entry.id is not None
    fetched = RouteQueryLog.get_by_id(log_entry.id)
    assert fetched.journey_id == journey.id
    assert fetched.query_type == "initial_discovery"
    assert fetched.trigger_reason == "automated_journey_creation"
    assert fetched.origin_lat == 51.5308
    assert "routes" in fetched.raw_response
    assert len(fetched.parsed_summary) == 1
