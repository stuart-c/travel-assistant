"""Unit tests for RouteQueryLog audit model."""

import pytest
from flask import Flask
from app.models.journey import Journey
from app.models.route_query_log import RouteQueryLog


@pytest.fixture(autouse=True)
def setup_test_db(app: Flask) -> None:
    """Initialise test SQLite isolated database with required models."""
    pass


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
