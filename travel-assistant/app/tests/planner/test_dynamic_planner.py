"""Unit tests for DynamicRoutePlanner dynamic transit routing service."""

from __future__ import annotations

import datetime
from unittest.mock import MagicMock
import pytest
from flask import Flask

from app.models.journey import Journey, JourneyTimeSetting
from app.models.location import Location
from app.models.timetable import (
    Timetable,
    TimetableContent,
    TimetableStop,
    TimetableTrip,
)
from app.models.transit import Stop
from app.services.planner.dynamic_planner import (
    DynamicRoutePlanner,
    map_vehicle_type,
    resolve_or_create_stop,
    resolve_target_commute_datetime,
)


@pytest.fixture(autouse=True)
def setup_test_db(app: Flask) -> None:
    """Initialise isolated test database with app context."""
    pass


def test_map_vehicle_type() -> None:
    """Test vehicle type mapping from Google Routes API strings to internal modes."""
    assert map_vehicle_type("BUS") == "bus"
    assert map_vehicle_type("INTERCITY_BUS") == "bus"
    assert map_vehicle_type("SUBWAY") == "subway"
    assert map_vehicle_type("METRO") == "subway"
    assert map_vehicle_type("UNDERGROUND") == "subway"
    assert map_vehicle_type("TRAM") == "tram"
    assert map_vehicle_type("HEAVY_RAIL") == "rail"
    assert map_vehicle_type("COMMUTER_TRAIN") == "rail"
    assert map_vehicle_type(None) == "rail"


def test_resolve_or_create_stop() -> None:
    """Test resolving existing Stop record or generating synthetic stop."""
    # Existing stop
    Stop.create(
        atco_code="9100KNGX",
        name="London King's Cross Rail Station",
        stop_type="rail",
        latitude=51.5308,
        longitude=-0.1238,
    )

    st_type, atco, name = resolve_or_create_stop(
        "London King's Cross", 51.5308, -0.1238, stop_type="rail"
    )
    assert st_type == "rail"
    assert atco == "9100KNGX"

    # Synthetic stop
    st_type2, atco2, name2 = resolve_or_create_stop(
        "Piccadilly Circus", 51.5100, -0.1340, stop_type="rail"
    )
    assert "google:" in atco2
    assert "Piccadilly" in name2


def test_resolve_target_commute_datetime() -> None:
    """Test resolving next departure and arrival target datetimes from journey time settings."""
    # Departure mode journey
    j_dep = Journey.create(
        name="Depart Commute",
        from_type="ha",
        from_id="ha:home",
        from_name="Home",
        to_type="custom",
        to_id="custom:office",
        to_name="Office",
        time_settings=[
            JourneyTimeSetting(
                days=["mon", "tue", "wed", "thu", "fri"],
                mode="depart",
                start_time="08:15",
                end_time="09:00",
            )
        ],
    )
    ref_dt = datetime.datetime(2026, 10, 5, 7, 30, 0)  # Monday 07:30
    target_dep, target_arr = resolve_target_commute_datetime(j_dep, ref_dt)
    assert target_arr is None
    assert target_dep is not None
    assert target_dep.hour == 8
    assert target_dep.minute == 15

    # Arrival mode journey
    j_arr = Journey.create(
        name="Arrive Commute",
        from_type="ha",
        from_id="ha:home",
        from_name="Home",
        to_type="custom",
        to_id="custom:office",
        to_name="Office",
        time_settings=[
            JourneyTimeSetting(
                days=["mon", "tue", "wed", "thu", "fri"],
                mode="arrive",
                start_time="08:30",
                end_time="09:00",
            )
        ],
    )
    target_dep2, target_arr2 = resolve_target_commute_datetime(j_arr, ref_dt)
    assert target_dep2 is None
    assert target_arr2 is not None
    assert target_arr2.hour == 9
    assert target_arr2.minute == 0


def test_dynamic_route_planner_google_transit() -> None:
    """Test dynamic live transit route computation using Google Routes API response."""
    Location.create(
        id="ha:home_dyn",
        name="London King's Cross Residence",
        location_type="ha",
        latitude=51.5308,
        longitude=-0.1238,
    )
    Location.create(
        id="custom:office_dyn",
        name="Old Street Tech Hub",
        location_type="custom",
        latitude=51.5255,
        longitude=-0.0875,
    )

    journey = Journey.create(
        name="Dynamic Commute",
        from_type="ha",
        from_id="ha:home_dyn",
        from_name="London King's Cross Residence",
        to_type="custom",
        to_id="custom:office_dyn",
        to_name="Old Street Tech Hub",
    )

    mock_google = MagicMock()
    mock_google.compute_transit_routes.return_value = {
        "routes": [
            {
                "duration": "1200s",
                "description": "Northern Line via Moorgate",
                "legs": [
                    {
                        "steps": [
                            {
                                "travelMode": "WALK",
                                "staticDuration": "180s",
                            },
                            {
                                "travelMode": "TRANSIT",
                                "staticDuration": "720s",
                                "transitDetails": {
                                    "stopDetails": {
                                        "departureStop": {
                                            "name": "King's Cross St. Pancras"
                                        },
                                        "arrivalStop": {"name": "Old Street"},
                                        "departureTime": "2026-10-02T08:18:00Z",
                                        "arrivalTime": "2026-10-02T08:30:00Z",
                                    },
                                    "transitLine": {
                                        "nameShort": "Northern",
                                        "vehicle": {"type": "SUBWAY"},
                                    },
                                },
                            },
                            {
                                "travelMode": "WALK",
                                "staticDuration": "300s",
                            },
                        ]
                    }
                ],
            }
        ]
    }

    planner = DynamicRoutePlanner(google_client=mock_google)
    itineraries = planner.plan_transit(
        journey=journey,
        departure_time=datetime.datetime(2026, 10, 2, 8, 15, 0),
        enrich_live=False,
    )

    assert len(itineraries) == 1
    itin = itineraries[0]
    assert itin.total_duration_minutes == 20
    assert len(itin.legs) == 3
    assert itin.legs[0].mode == "walk"
    assert itin.legs[1].mode == "subway"
    assert itin.legs[1].line == "Northern"
    assert itin.legs[2].mode == "walk"


def test_dynamic_route_planner_hybrid_custom_shuttle() -> None:
    """Test hybrid routing incorporating private shuttle bus timetable for first/last mile."""
    Location.create(
        id="ha:home_shuttle",
        name="London King's Cross Residence",
        location_type="ha",
        latitude=51.5308,
        longitude=-0.1238,
    )
    Location.create(
        id="custom:campus_shuttle",
        name="Research Science Park",
        location_type="custom",
        latitude=52.2300,
        longitude=0.1500,
    )
    Stop.create(
        atco_code="9100CAMBDGE",
        name="Cambridge Station",
        stop_type="rail",
        latitude=52.1945,
        longitude=0.1372,
    )

    # Campus Shuttle timetable: Cambridge Station -> Research Science Park
    tt_shuttle = Timetable.create(
        name="Campus Shuttle (Morning)",
        transport_type="bus",
        monday=True,
        tuesday=True,
        wednesday=True,
        thursday=True,
        friday=True,
        saturday=False,
        sunday=False,
        bank_holiday=False,
        start_date=datetime.date(2026, 1, 1),
        end_date=datetime.date(2026, 12, 31),
        auto_added=False,  # Custom private timetable
    )
    tt_shuttle.set_content(
        TimetableContent(
            stops=[
                TimetableStop(id="9100CAMBDGE", name="Cambridge Station", type="rail"),
                TimetableStop(
                    id="custom:campus_shuttle",
                    name="Research Science Park",
                    type="custom",
                ),
            ],
            trips=[
                TimetableTrip(
                    id="shuttle_trip_1",
                    times=[
                        {"dep": "08:45"},
                        {"arr": "08:58"},
                    ],
                )
            ],
        )
    )
    tt_shuttle.save()

    journey = Journey.create(
        name="Cambridge Commute with Private Shuttle",
        from_type="ha",
        from_id="ha:home_shuttle",
        from_name="London King's Cross Residence",
        to_type="custom",
        to_id="custom:campus_shuttle",
        to_name="Research Science Park",
    )

    # Google Routes mock from King's Cross to Cambridge Station
    mock_google = MagicMock()
    mock_google.compute_transit_routes.return_value = {
        "routes": [
            {
                "duration": "3000s",
                "description": "Great Northern to Cambridge",
                "legs": [
                    {
                        "steps": [
                            {
                                "travelMode": "TRANSIT",
                                "staticDuration": "3000s",
                                "transitDetails": {
                                    "stopDetails": {
                                        "departureStop": {
                                            "name": "London King's Cross"
                                        },
                                        "arrivalStop": {"name": "Cambridge"},
                                        "departureTime": "2026-10-02T07:45:00Z",
                                        "arrivalTime": "2026-10-02T08:35:00Z",
                                    },
                                    "transitLine": {
                                        "nameShort": "Great Northern",
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

    planner = DynamicRoutePlanner(google_client=mock_google)
    itineraries = planner.plan_transit(
        journey=journey,
        departure_time=datetime.datetime(2026, 10, 2, 7, 40, 0),
        enrich_live=False,
    )

    assert len(itineraries) >= 1
    hybrid_itin = itineraries[0]
    # Spliced legs should include main transit + shuttle bus
    leg_lines = [leg.line for leg in hybrid_itin.legs if leg.line]
    assert "Great Northern" in leg_lines
    assert "Campus Shuttle (Morning)" in leg_lines
