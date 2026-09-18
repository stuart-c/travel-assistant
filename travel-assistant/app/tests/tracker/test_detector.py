"""Unit tests for journey detection and mid-journey recovery."""

import datetime
from unittest.mock import patch
from flask import Flask

from app.models.journey import Journey
from app.models.location import Location
from app.models.transit import Stop
from app.services.dispatcher.tracker.detector import detect_en_route_journey
from app.services.dispatcher.tracker.models import JourneyStepStatus
from app.services.planner.models import (
    ItineraryEndpoint,
    ItineraryLeg,
    ScheduledItinerary,
)


def test_detect_en_route_journey_invalid_or_not_en_route(app: Flask) -> None:
    """Test detect_en_route_journey returns None for non-en-route states."""
    with app.app_context():
        # Seed locations for journey
        Location.create(
            id="ha:home",
            name="Home",
            latitude=51.5300,
            longitude=-0.1230,
            ha=True,
        )
        Location.create(
            id="ha:office",
            name="Tech Campus",
            latitude=51.5280,
            longitude=-0.1340,
            ha=True,
        )
        journey = Journey.create(
            name="Morning Commute",
            from_type="ha",
            from_id="ha:home",
            from_name="Home",
            to_type="ha",
            to_id="ha:office",
            to_name="Tech Campus",
        )
        now = datetime.datetime(2026, 9, 7, 8, 15)

        # 1. None or empty state
        assert detect_en_route_journey(journey, None, now) is None
        assert detect_en_route_journey(journey, {}, now) is None

        # 2. Near origin -> None
        state_at_origin = {
            "entity_id": "person.stuart",
            "state": "home",
            "attributes": {"latitude": 51.5300, "longitude": -0.1230},
        }
        assert detect_en_route_journey(journey, state_at_origin, now) is None

        # 3. Near destination -> None
        state_at_dest = {
            "entity_id": "person.stuart",
            "state": "office",
            "attributes": {"latitude": 51.5280, "longitude": -0.1340},
        }
        assert detect_en_route_journey(journey, state_at_dest, now) is None

        # 4. Missing or invalid coordinates
        state_no_coords = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {},
        }
        assert detect_en_route_journey(journey, state_no_coords, now) is None
        state_invalid_coords = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": "invalid", "longitude": -0.1340},
        }
        assert detect_en_route_journey(journey, state_invalid_coords, now) is None

        # 5. Planning failure / exception handled cleanly
        state_en_route = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5290, "longitude": -0.1280},
        }
        with patch(
            "app.services.planner.raptor.plan_journey",
            side_effect=RuntimeError("Solver error"),
        ):
            assert detect_en_route_journey(journey, state_en_route, now) is None

        # 6. No itineraries discovered
        with patch("app.services.planner.raptor.plan_journey", return_value=[]):
            assert detect_en_route_journey(journey, state_en_route, now) is None


def test_detect_en_route_journey_success_scenarios(app: Flask) -> None:
    """Test detect_en_route_journey successfully detects stops and on-transit progress."""
    with app.app_context():
        # Seed stops
        Stop.create(
            atco_code="490000077E",
            naptan_code="490000077E",
            name="King's Cross (Stop E)",
            stop_type="bus",
            latitude=51.5302,
            longitude=-0.1225,
        )
        Stop.create(
            atco_code="490000077C",
            naptan_code="490000077C",
            name="Euston Station (Stop C)",
            stop_type="bus",
            latitude=51.5281,
            longitude=-0.1325,
        )
        Location.create(
            id="ha:home_loc",
            name="Home",
            latitude=51.5350,
            longitude=-0.1100,
            ha=True,
        )
        Location.create(
            id="ha:office_loc",
            name="Tech Campus",
            latitude=51.5200,
            longitude=-0.1400,
            ha=True,
        )
        journey = Journey.create(
            name="Commute Journey",
            from_type="ha",
            from_id="ha:home_loc",
            from_name="Home",
            to_type="ha",
            to_id="ha:office_loc",
            to_name="Tech Campus",
        )

        sample_itin = ScheduledItinerary(
            departure_time="08:00",
            arrival_time="08:30",
            total_duration_minutes=30,
            transfers_count=0,
            robustness_score="High",
            legs=[
                ItineraryLeg(
                    leg_index=1,
                    mode="walk",
                    origin=ItineraryEndpoint(id="ha:home_loc", name="Home"),
                    destination=ItineraryEndpoint(
                        id="490000077E", name="King's Cross (Stop E)"
                    ),
                    dep_time="08:00",
                    arr_time="08:05",
                    duration_minutes=5,
                ),
                ItineraryLeg(
                    leg_index=2,
                    mode="bus",
                    line="73",
                    origin=ItineraryEndpoint(
                        id="490000077E", name="King's Cross (Stop E)"
                    ),
                    destination=ItineraryEndpoint(
                        id="490000077C", name="Euston Station (Stop C)"
                    ),
                    dep_time="08:08",
                    arr_time="08:22",
                    duration_minutes=14,
                ),
                ItineraryLeg(
                    leg_index=3,
                    mode="walk",
                    origin=ItineraryEndpoint(
                        id="490000077C", name="Euston Station (Stop C)"
                    ),
                    destination=ItineraryEndpoint(
                        id="ha:office_loc", name="Tech Campus"
                    ),
                    dep_time="08:22",
                    arr_time="08:30",
                    duration_minutes=8,
                ),
            ],
        )

        now = datetime.datetime(2026, 9, 7, 8, 10)

        # 1. Stuart is at departure bus stop (King's Cross Stop E)
        state_at_stop = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5302, "longitude": -0.1225},
        }
        with patch(
            "app.services.planner.raptor.plan_journey",
            return_value=[sample_itin],
        ):
            recovered = detect_en_route_journey(journey, state_at_stop, now)
            assert recovered is not None
            assert recovered.journey_id == journey.id
            assert recovered.current_leg_index == 1
            assert recovered.current_status == JourneyStepStatus.AT_DEPARTURE_STOP

        # 2. Stuart is at leg destination stop (Euston Stop C)
        state_at_dest_stop = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5281, "longitude": -0.1325},
        }
        with patch(
            "app.services.planner.raptor.plan_journey",
            return_value=[sample_itin],
        ):
            recovered_dest = detect_en_route_journey(journey, state_at_dest_stop, now)
            assert recovered_dest is not None
            assert recovered_dest.current_leg_index == 2
            assert (
                recovered_dest.current_status
                == JourneyStepStatus.EN_ROUTE_TO_DESTINATION
            )

        # 3. Stuart is on board transit between King's Cross and Euston
        # Midpoint coordinates ~51.5291, -0.1275
        state_midway = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5291, "longitude": -0.1275},
        }
        with patch(
            "app.services.planner.raptor.plan_journey",
            return_value=[sample_itin],
        ):
            now_mid = datetime.datetime(2026, 9, 7, 8, 15)  # Between 08:08 and 08:22
            recovered_mid = detect_en_route_journey(journey, state_midway, now_mid)
            assert recovered_mid is not None
            assert recovered_mid.current_leg_index == 1
            assert recovered_mid.current_status == JourneyStepStatus.ON_TRANSIT

        # 4. Stuart is walking towards King's Cross Stop E (en route to stop)
        # Coordinates ~51.5330, -0.1240 (between Home and King's Cross)
        state_walking = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5330, "longitude": -0.1240},
        }
        with patch(
            "app.services.planner.raptor.plan_journey",
            return_value=[sample_itin],
        ):
            now_walk = datetime.datetime(2026, 9, 7, 8, 2)  # Between 08:00 and 08:05
            recovered_walk = detect_en_route_journey(journey, state_walking, now_walk)
            assert recovered_walk is not None
            assert recovered_walk.current_leg_index == 0
            assert recovered_walk.current_status == JourneyStepStatus.EN_ROUTE_TO_STOP
