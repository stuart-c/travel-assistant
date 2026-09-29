"""Unit tests for CorridorLearner service."""

from unittest.mock import MagicMock
import pytest
from flask import Flask
from app.models.journey import Journey
from app.models.location import Location
from app.models.route_query_log import RouteQueryLog
from app.models.timetable import Timetable
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


def test_discover_and_persist_corridors_direct_walk() -> None:
    """Test discovering and persisting direct walking connection."""
    Location.create(
        id="ha:home_residence",
        name="Home Residence",
        location_type="ha",
        latitude=51.5308,
        longitude=-0.1238,
    )
    Location.create(
        id="custom:corner_shop",
        name="Corner Shop",
        location_type="custom",
        latitude=51.5315,
        longitude=-0.1245,
    )
    Walking.create(
        start_type="ha",
        start_id="ha:home_residence",
        start_name="Home Residence",
        finish_type="custom",
        finish_id="custom:corner_shop",
        finish_name="Corner Shop",
        time_needed_minutes=5,
        bidirectional=True,
    )

    journey = Journey.create(
        name="Quick Walk",
        from_type="ha",
        from_id="ha:home_residence",
        from_name="Home Residence",
        to_type="custom",
        to_id="custom:corner_shop",
        to_name="Corner Shop",
    )

    # Even without a Google Maps client, direct walk is persisted
    learner = CorridorLearner()
    routes = learner.discover_and_persist_corridors(journey)

    assert len(routes) == 1
    assert routes[0].primary_mode == "walk"
    assert routes[0].total_duration_est_minutes == 5
    assert routes[0].is_preferred is True
    assert len(routes[0].legs) == 1
    assert routes[0].legs[0]["duration_minutes"] == 5


def test_discover_and_persist_corridors_multi_step_walking_lookahead() -> None:
    """Test multi-step turn-by-turn walking steps are consolidated without erroneous destination links."""
    Location.create(
        id="ha:kings_cross_home",
        name="King's Cross Home",
        location_type="ha",
        latitude=51.5308,
        longitude=-0.1238,
    )
    Location.create(
        id="custom:london_bridge_office",
        name="London Bridge Office",
        location_type="custom",
        latitude=51.5045,
        longitude=-0.0865,
    )

    journey = Journey.create(
        name="London Commute",
        from_type="ha",
        from_id="ha:kings_cross_home",
        from_name="King's Cross Home",
        to_type="custom",
        to_id="custom:london_bridge_office",
        to_name="London Bridge Office",
    )

    mock_client = MagicMock()
    mock_client.compute_transit_routes.return_value = {
        "routes": [
            {
                "duration": "1800s",
                "description": "Northern line",
                "legs": [
                    {
                        "steps": [
                            {
                                "travelMode": "WALK",
                                "staticDuration": "120s",
                                "distanceMeters": 100,
                            },
                            {
                                "travelMode": "WALK",
                                "staticDuration": "180s",
                                "distanceMeters": 150,
                            },
                            {
                                "travelMode": "TRANSIT",
                                "staticDuration": "1200s",
                                "distanceMeters": 4500,
                                "transitDetails": {
                                    "stopDetails": {
                                        "departureStop": {
                                            "name": "King's Cross St. Pancras Underground Station",
                                            "location": {
                                                "latLng": {
                                                    "latitude": 51.5308,
                                                    "longitude": -0.1238,
                                                }
                                            },
                                        },
                                        "arrivalStop": {
                                            "name": "London Bridge Underground Station",
                                            "location": {
                                                "latLng": {
                                                    "latitude": 51.5045,
                                                    "longitude": -0.0865,
                                                }
                                            },
                                        },
                                    },
                                    "transitLine": {
                                        "name": "Northern line",
                                        "transitAgency": {"name": "London Underground"},
                                        "vehicle": {"type": "SUBWAY"},
                                    },
                                    "stopCount": 6,
                                },
                            },
                            {
                                "travelMode": "WALK",
                                "staticDuration": "60s",
                                "distanceMeters": 50,
                            },
                            {
                                "travelMode": "WALK",
                                "staticDuration": "240s",
                                "distanceMeters": 200,
                            },
                        ]
                    }
                ],
            }
        ]
    }

    learner = CorridorLearner(client=mock_client)
    routes = learner.discover_and_persist_corridors(journey)

    assert len(routes) == 1
    r = routes[0]
    # Consecutive walking turns should be consolidated into exactly 3 legs
    assert len(r.legs) == 3

    # Leg 1: Consolidated access walk from origin to departure transit stop
    leg1 = r.legs[0]
    assert leg1["leg_type"] == "walk"
    assert leg1["from_id"] == "ha:kings_cross_home"
    assert leg1["to_id"] != "custom:london_bridge_office"
    assert "king_s_cross" in leg1["to_id"]
    assert leg1["duration_minutes"] == 5
    assert leg1["distance_m"] == 250

    # Leg 2: Transit leg
    leg2 = r.legs[1]
    assert leg2["leg_type"] == "transit"
    assert leg2["line_name"] == "Northern line"

    # Leg 3: Consolidated egress walk from alight transit stop to final destination
    leg3 = r.legs[2]
    assert leg3["leg_type"] == "walk"
    assert "london_bridge" in leg3["from_id"]
    assert leg3["to_id"] == "custom:london_bridge_office"
    assert leg3["duration_minutes"] == 5
    assert leg3["distance_m"] == 250

    # Verify that NO direct walking connection between origin and destination was created
    spurious_direct = Walking.find_walking_route(
        "ha", "ha:kings_cross_home", "custom", "custom:london_bridge_office"
    )
    assert spurious_direct is None

    # Verify that valid walking legs were registered in the Walking model
    access_walk = Walking.find_walking_route(
        "ha", "ha:kings_cross_home", leg1["to_type"], leg1["to_id"]
    )
    assert access_walk is not None
    assert access_walk.time_needed_minutes == 5

    egress_walk = Walking.find_walking_route(
        leg3["from_type"], leg3["from_id"], "custom", "custom:london_bridge_office"
    )
    assert egress_walk is not None
    assert egress_walk.time_needed_minutes == 5


def test_synthesize_custom_timetable_last_mile_corridor() -> None:
    """Test synthesising a last-mile custom shuttle bus corridor into journey routes."""
    Location.create(
        id="ha:kings_cross_home",
        name="King's Cross Home",
        location_type="ha",
        latitude=51.5308,
        longitude=-0.1238,
    )
    Location.create(
        id="custom:tech_campus",
        name="Tech Campus",
        location_type="custom",
        latitude=51.5490,
        longitude=-0.1000,
    )
    Stop.create(
        atco_code="490000078F",
        name="Highbury & Islington Rail Station",
        stop_type="rail",
        latitude=51.5463,
        longitude=-0.1033,
    )

    journey = Journey.create(
        name="Morning Commute",
        from_type="ha",
        from_id="ha:kings_cross_home",
        from_name="King's Cross Home",
        to_type="custom",
        to_id="custom:tech_campus",
        to_name="Tech Campus",
    )

    Timetable.create(
        name="Tech Campus Shuttle (Morning)",
        transport_type="bus",
        monday=1,
        tuesday=1,
        wednesday=1,
        thursday=1,
        friday=1,
        auto_added=0,
        content={
            "stops": [
                {
                    "id": "atco:490000078F",
                    "name": "Highbury & Islington Rail Station",
                    "type": "rail",
                    "latitude": 51.5463,
                    "longitude": -0.1033,
                },
                {
                    "id": "custom:tech_campus",
                    "name": "Tech Campus",
                    "type": "custom",
                    "latitude": 51.5490,
                    "longitude": -0.1000,
                },
            ],
            "trips": [{"id": "t1", "times": ["08:30", "08:40"]}],
        },
    )

    mock_client = MagicMock()
    mock_client.compute_transit_routes.return_value = {
        "routes": [
            {
                "duration": "2400s",
                "description": "Great Northern",
                "legs": [
                    {
                        "steps": [
                            {
                                "travelMode": "WALK",
                                "staticDuration": "180s",
                                "distanceMeters": 200,
                            },
                            {
                                "travelMode": "TRANSIT",
                                "staticDuration": "420s",
                                "distanceMeters": 2500,
                                "transitDetails": {
                                    "stopDetails": {
                                        "departureStop": {
                                            "name": "King's Cross Station",
                                            "location": {
                                                "latLng": {
                                                    "latitude": 51.5308,
                                                    "longitude": -0.1238,
                                                }
                                            },
                                        },
                                        "arrivalStop": {
                                            "name": "Highbury & Islington Rail Station",
                                            "location": {
                                                "latLng": {
                                                    "latitude": 51.5463,
                                                    "longitude": -0.1033,
                                                }
                                            },
                                        },
                                    },
                                    "transitLine": {
                                        "nameShort": "Great Northern",
                                        "vehicle": {"type": "HEAVY_RAIL"},
                                    },
                                },
                            },
                            {
                                "travelMode": "WALK",
                                "staticDuration": "1800s",
                                "distanceMeters": 2200,
                            },
                        ]
                    }
                ],
            }
        ]
    }

    learner = CorridorLearner(client=mock_client)
    routes = learner.discover_and_persist_corridors(journey)

    assert len(routes) == 2
    pref_route = next(r for r in routes if r.is_preferred)
    assert "Tech Campus Shuttle (Morning)" in pref_route.name
    assert pref_route.is_preferred is True
    # Verify the last leg is the custom timetable transit leg
    assert pref_route.legs[-1]["leg_type"] == "transit"
    assert pref_route.legs[-1]["line_name"] == "Tech Campus Shuttle (Morning)"
    assert pref_route.legs[-1]["to_id"] == "custom:tech_campus"

    # Verify the non-preferred fallback route is the public one
    fallback = next(r for r in routes if not r.is_preferred)
    assert "Tech Campus Shuttle (Morning)" not in fallback.name
    assert fallback.is_preferred is False


def test_synthesize_custom_timetable_first_mile_corridor() -> None:
    """Test synthesising a first-mile custom shuttle bus corridor into journey routes."""
    Location.create(
        id="custom:tech_campus",
        name="Tech Campus",
        location_type="custom",
        latitude=51.5490,
        longitude=-0.1000,
    )
    Location.create(
        id="ha:tech_shuttle_stand",
        name="Tech Shuttle Stand",
        location_type="ha",
        latitude=51.5485,
        longitude=-0.1010,
    )
    Location.create(
        id="ha:kings_cross_home",
        name="King's Cross Home",
        location_type="ha",
        latitude=51.5308,
        longitude=-0.1238,
    )
    Stop.create(
        atco_code="490000078F",
        name="Highbury & Islington Rail Station",
        stop_type="rail",
        latitude=51.5463,
        longitude=-0.1033,
    )

    Walking.create(
        start_type="custom",
        start_id="custom:tech_campus",
        start_name="Tech Campus",
        finish_type="ha",
        finish_id="ha:tech_shuttle_stand",
        finish_name="Tech Shuttle Stand",
        time_needed_minutes=3,
        bidirectional=True,
    )

    journey = Journey.create(
        name="Evening Commute",
        from_type="custom",
        from_id="custom:tech_campus",
        from_name="Tech Campus",
        to_type="ha",
        to_id="ha:kings_cross_home",
        to_name="King's Cross Home",
    )

    Timetable.create(
        name="Tech Campus Shuttle (Evening)",
        transport_type="bus",
        monday=1,
        tuesday=1,
        wednesday=1,
        thursday=1,
        friday=1,
        auto_added=0,
        content={
            "stops": [
                {
                    "id": "ha:tech_shuttle_stand",
                    "name": "Tech Shuttle Stand",
                    "type": "ha",
                    "latitude": 51.5485,
                    "longitude": -0.1010,
                },
                {
                    "id": "atco:490000078F",
                    "name": "Highbury & Islington Rail Station",
                    "type": "rail",
                    "latitude": 51.5463,
                    "longitude": -0.1033,
                },
            ],
            "trips": [{"id": "t2", "times": ["17:00", "17:10"]}],
        },
    )

    mock_client = MagicMock()
    mock_client.compute_transit_routes.return_value = {
        "routes": [
            {
                "duration": "2400s",
                "description": "Great Northern",
                "legs": [
                    {
                        "steps": [
                            {
                                "travelMode": "WALK",
                                "staticDuration": "1500s",
                                "distanceMeters": 2000,
                            },
                            {
                                "travelMode": "TRANSIT",
                                "staticDuration": "420s",
                                "distanceMeters": 2500,
                                "transitDetails": {
                                    "stopDetails": {
                                        "departureStop": {
                                            "name": "Highbury & Islington Rail Station",
                                            "location": {
                                                "latLng": {
                                                    "latitude": 51.5463,
                                                    "longitude": -0.1033,
                                                }
                                            },
                                        },
                                        "arrivalStop": {
                                            "name": "King's Cross Station",
                                            "location": {
                                                "latLng": {
                                                    "latitude": 51.5308,
                                                    "longitude": -0.1238,
                                                }
                                            },
                                        },
                                    },
                                    "transitLine": {
                                        "nameShort": "Great Northern",
                                        "vehicle": {"type": "HEAVY_RAIL"},
                                    },
                                },
                            },
                            {
                                "travelMode": "WALK",
                                "staticDuration": "180s",
                                "distanceMeters": 200,
                            },
                        ]
                    }
                ],
            }
        ]
    }

    learner = CorridorLearner(client=mock_client)
    routes = learner.discover_and_persist_corridors(journey)

    assert len(routes) == 2
    pref_route = next(r for r in routes if r.is_preferred)
    assert "Tech Campus Shuttle (Evening)" in pref_route.name
    assert pref_route.is_preferred is True

    # Leg 1: Access walk to Tech Shuttle Stand
    assert pref_route.legs[0]["leg_type"] == "walk"
    assert pref_route.legs[0]["to_id"] == "ha:tech_shuttle_stand"
    assert pref_route.legs[0]["duration_minutes"] == 3

    # Leg 2: Transit via custom shuttle
    assert pref_route.legs[1]["leg_type"] == "transit"
    assert pref_route.legs[1]["line_name"] == "Tech Campus Shuttle (Evening)"
    assert pref_route.legs[1]["to_id"] == "atco:490000078F"

    # Leg 3: Transit via Great Northern train
    assert pref_route.legs[2]["leg_type"] == "transit"
    assert pref_route.legs[2]["line_name"] == "Great Northern"

    # Leg 4: Egress walk to home
    assert pref_route.legs[3]["leg_type"] == "walk"
    assert pref_route.legs[3]["to_id"] == "ha:kings_cross_home"
