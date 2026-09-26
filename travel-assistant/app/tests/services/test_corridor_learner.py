"""Unit tests for CorridorLearner service."""

from unittest.mock import MagicMock
import pytest
from flask import Flask
from app.models.journey import Journey
from app.models.location import Location
from app.models.route_query_log import RouteQueryLog
from app.models.transit import Stop
from app.models.walking import Walking
from app.services.corridor_learner import (
    CorridorLearner,
    map_vehicle_type,
    parse_duration_seconds,
    resolve_or_create_stop,
)


@pytest.fixture(autouse=True)
def setup_test_db(app: Flask) -> None:
    """Initialise isolated test database with app context."""
    pass


def test_map_vehicle_type() -> None:
    """Test vehicle type mapping to canonical transport modes."""
    assert map_vehicle_type("BUS") == "bus"
    assert map_vehicle_type("SUBWAY") == "metro"
    assert map_vehicle_type("HEAVY_RAIL") == "rail"
    assert map_vehicle_type("COMMUTER_TRAIN") == "rail"
    assert map_vehicle_type("TRAM") == "tram"
    assert map_vehicle_type("FERRY") == "ferry"
    assert map_vehicle_type("UNKNOWN") == "bus"


def test_parse_duration_seconds() -> None:
    """Test parsing of duration strings into seconds."""
    assert parse_duration_seconds("1200s") == 1200
    assert parse_duration_seconds("45s") == 45
    assert parse_duration_seconds("") == 0
    assert parse_duration_seconds(None) == 0


def test_resolve_or_create_stop() -> None:
    """Test resolving existing stop and generating new Stop record."""
    Stop.create(
        atco_code="490000077E",
        name="London King's Cross",
        stop_type="rail",
        latitude=51.5308,
        longitude=-0.1238,
    )

    # Resolves existing stop by name
    st_type, atco, st_name = resolve_or_create_stop(
        "London King's Cross", 51.5308, -0.1238, stop_type="rail"
    )
    assert st_type == "rail"
    assert atco == "490000077E"
    assert st_name == "London King's Cross"

    # Creates new stop if not found
    st_type2, atco2, st_name2 = resolve_or_create_stop(
        "Angel Islington (Stop B)", 51.532, -0.106, stop_type="bus"
    )
    assert st_type2 == "bus"
    assert "angel_islington_stop_b" in atco2
    assert st_name2 == "Angel Islington (Stop B)"
    assert Stop.get_by_atco(atco2) is not None


def test_discover_and_persist_corridors_success() -> None:
    """Test full corridor discovery, audit logging, and persistence."""
    Location.create(
        id="ha:home",
        name="Home",
        location_type="ha",
        latitude=51.5308,
        longitude=-0.1238,
    )
    Location.create(
        id="custom:office",
        name="Office",
        location_type="custom",
        latitude=51.5284,
        longitude=-0.1331,
    )

    journey = Journey.create(
        name="Commute to Work",
        from_type="ha",
        from_id="ha:home",
        from_name="Home",
        to_type="custom",
        to_id="custom:office",
        to_name="Office",
    )

    mock_client = MagicMock()
    mock_client.compute_transit_routes.return_value = {
        "routes": [
            {
                "duration": "1440s",
                "description": "Bus 73",
                "legs": [
                    {
                        "steps": [
                            {
                                "travelMode": "WALK",
                                "staticDuration": "360s",
                                "distanceMeters": 400,
                            },
                            {
                                "travelMode": "TRANSIT",
                                "staticDuration": "840s",
                                "distanceMeters": 2100,
                                "transitDetails": {
                                    "stopDetails": {
                                        "departureStop": {
                                            "name": "King's Cross Station (Stop E)",
                                            "location": {
                                                "latLng": {
                                                    "latitude": 51.5308,
                                                    "longitude": -0.1238,
                                                }
                                            },
                                        },
                                        "arrivalStop": {
                                            "name": "Euston Station (Stop C)",
                                            "location": {
                                                "latLng": {
                                                    "latitude": 51.5284,
                                                    "longitude": -0.1331,
                                                }
                                            },
                                        },
                                    },
                                    "transitLine": {
                                        "nameShort": "73",
                                        "transitAgency": {"name": "Arriva London"},
                                        "vehicle": {"type": "BUS"},
                                    },
                                    "stopCount": 5,
                                },
                            },
                            {
                                "travelMode": "WALK",
                                "staticDuration": "240s",
                                "distanceMeters": 250,
                            },
                        ]
                    }
                ],
            }
        ]
    }

    learner = CorridorLearner(client=mock_client)
    routes = learner.discover_and_persist_corridors(
        journey,
        query_type="initial_discovery",
        trigger_reason="automated_test_creation",
    )

    assert len(routes) == 1
    r = routes[0]
    assert r.journey_id == journey.id
    assert r.name == "Bus 73"
    assert r.is_preferred is True
    assert r.total_duration_est_minutes == 24
    assert r.primary_mode == "bus"
    assert len(r.legs) == 3
    assert r.legs[1]["line_name"] == "73"

    # Verify query audit log
    logs = list(RouteQueryLog.select().where(RouteQueryLog.journey_id == journey.id))
    assert len(logs) == 1
    assert logs[0].query_type == "initial_discovery"
    assert logs[0].trigger_reason == "automated_test_creation"
    assert logs[0].selected_route_id == r.id
    assert len(logs[0].parsed_summary) == 1

    # Verify walking link created
    walk = Walking.find_walking_route("ha", "ha:home", "bus", r.legs[1]["from_id"])
    assert walk is not None

    # Verify legacy calculated_routes updated on journey
    j_updated = Journey.get_by_id(journey.id)
    assert j_updated.calculated_routes is not None
    assert len(j_updated.get_calculated_routes()) == 1


def test_discover_and_persist_corridors_unresolved_coords() -> None:
    """Test handling when endpoint coordinates cannot be resolved."""
    journey = Journey.create(
        name="Missing Coords",
        from_type="custom",
        from_id="custom:non_existent",
        from_name="Nowhere",
        to_type="custom",
        to_id="custom:nowhere",
        to_name="Nowhere Else",
    )
    learner = CorridorLearner()
    res = learner.discover_and_persist_corridors(journey)
    assert res == []


def test_discover_and_persist_corridors_empty_response() -> None:
    """Test handling when Google Routes returns no routes."""
    Location.create(
        id="custom:p1",
        name="Place 1",
        location_type="custom",
        latitude=51.5,
        longitude=-0.1,
    )
    Location.create(
        id="custom:p2",
        name="Place 2",
        location_type="custom",
        latitude=51.6,
        longitude=-0.2,
    )

    journey = Journey.create(
        name="Empty Commute",
        from_type="custom",
        from_id="custom:p1",
        from_name="Place 1",
        to_type="custom",
        to_id="custom:p2",
        to_name="Place 2",
    )

    mock_client = MagicMock()
    mock_client.compute_transit_routes.return_value = {"routes": []}

    learner = CorridorLearner(client=mock_client)
    res = learner.discover_and_persist_corridors(journey)
    assert res == []

    logs = list(RouteQueryLog.select().where(RouteQueryLog.journey_id == journey.id))
    assert len(logs) == 1
    assert logs[0].raw_response == {"routes": []}
