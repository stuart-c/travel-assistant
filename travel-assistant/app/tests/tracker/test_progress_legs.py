"""Unit tests for journey leg advancement, interchange waiting, and forward scanning."""

import datetime
from unittest.mock import MagicMock
from flask import Flask

from app.datasources.homeassistant import HomeAssistantClient
from app.models.location import Location
from app.models.transit import Stop
from app.services.dispatcher.tracker.models import (
    ActiveJourney,
    JourneyStepStatus,
)
from app.services.dispatcher.tracker.progress import update_journey_progress
from app.services.planner.models import (
    ItineraryEndpoint,
    ItineraryLeg,
    ScheduledItinerary,
)
from app.tests.tracker.conftest import create_sample_active_journey


def test_update_journey_progress_transit_origin_proximity_and_interchange(
    app: Flask,
) -> None:
    """Test transit leg origin proximity and waiting at interchange stop."""
    with app.app_context():
        # Journey starting directly with rail (leg index 0 is rail)
        active = create_sample_active_journey(with_rail=True)
        active.legs = active.legs[1:]  # remove walking access leg, rail is leg 0
        active.current_leg_index = 0
        active.current_status = JourneyStepStatus.PRE_DEPARTURE

        Stop.create(
            atco_code="naptan:KGX",
            naptan_code="KGX",
            name="London King's Cross",
            stop_type="rail",
            latitude=51.5308,
            longitude=-0.1238,
        )

        mock_ha = MagicMock(spec=HomeAssistantClient)
        now_before = datetime.datetime(2026, 9, 7, 8, 5)
        stuart_at_kgx = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5308, "longitude": -0.1238},
        }
        res = update_journey_progress(active, stuart_at_kgx, now_before, mock_ha)
        assert res is True
        assert active.current_status == JourneyStepStatus.AT_DEPARTURE_STOP

        # Now test multi-leg journey at interchange stop (leg index 2 is rail)
        active_multi = create_sample_active_journey(with_rail=True)
        active_multi.current_leg_index = 1
        active_multi.current_status = JourneyStepStatus.ON_TRANSIT
        # If leg is rail and Stuart is at origin station
        res_inter = update_journey_progress(
            active_multi, stuart_at_kgx, now_before, mock_ha
        )
        assert res_inter is True
        assert active_multi.current_status == JourneyStepStatus.AT_DEPARTURE_STOP


def test_update_journey_progress_past_last_leg_and_transfer_walk(app: Flask) -> None:
    """Test update_journey_progress when current_leg_index exceeds legs or is intermediate walk."""
    with app.app_context():
        active = create_sample_active_journey()
        # Exceeds leg length
        active.current_leg_index = 10
        active.current_status = JourneyStepStatus.ON_TRANSIT

        mock_ha = MagicMock(spec=HomeAssistantClient)
        stuart_state = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5250, "longitude": -0.1300},
        }
        res = update_journey_progress(
            active, stuart_state, datetime.datetime(2026, 9, 7, 8, 20), mock_ha
        )
        assert res is True
        assert active.current_status == JourneyStepStatus.EN_ROUTE_TO_DESTINATION

        # Intermediate walking transfer reaching transfer destination stop
        multi = create_sample_active_journey()
        # Make leg 2 a transfer walk to a second bus stop
        multi.legs.append(
            ItineraryLeg(
                leg_index=4,
                mode="bus",
                line="24",
                origin=ItineraryEndpoint(id="atco:dest_stop", name="Dest Stop"),
                destination=ItineraryEndpoint(id="ha:office", name="Tech Campus"),
                dep_time="08:35",
                arr_time="08:45",
                duration_minutes=10,
            )
        )
        multi.current_leg_index = 2
        multi.current_status = JourneyStepStatus.EN_ROUTE_TO_DESTINATION
        Stop.create(
            atco_code="atco:dest_stop",
            naptan_code="dest_stop",
            name="Dest Stop",
            stop_type="bus",
            latitude=51.5260,
            longitude=-0.1310,
        )
        multi.legs[2].destination.id = "atco:dest_stop"
        state_at_transfer = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5260, "longitude": -0.1310},
        }
        res_walk = update_journey_progress(
            multi, state_at_transfer, datetime.datetime(2026, 9, 7, 8, 25), mock_ha
        )
        assert res_walk is True
        assert multi.current_leg_index == 3
        assert multi.current_status == JourneyStepStatus.AT_INTERCHANGE


def test_update_journey_progress_advances_forward_bypassing_intermediate_leg(
    app: Flask,
) -> None:
    """Test forward scanning advances active journey when intermediate transfer stop was bypassed."""
    with app.app_context():
        Stop.create(
            atco_code="naptan:SVG",
            naptan_code="SVG",
            name="Stevenage Rail Station",
            stop_type="rail",
            latitude=51.9017,
            longitude=-0.2066,
        )
        Stop.create(
            atco_code="naptan:CBG",
            naptan_code="CBG",
            name="Cambridge Rail Station",
            stop_type="rail",
            latitude=52.1943,
            longitude=0.1372,
        )
        Location.create(
            id="ha:home",
            name="Home",
            latitude=51.9000,
            longitude=-0.2000,
            ha=True,
        )
        Location.create(
            id="ha:cambridge_office",
            name="Cambridge Office",
            latitude=52.2000,
            longitude=0.1400,
            ha=True,
        )

        legs = [
            ItineraryLeg(
                leg_index=1,
                mode="walk",
                origin=ItineraryEndpoint(id="ha:home", name="Home"),
                destination=ItineraryEndpoint(
                    id="naptan:SVG", name="Stevenage Rail Station"
                ),
                dep_time="06:35",
                arr_time="06:42",
                duration_minutes=7,
            ),
            ItineraryLeg(
                leg_index=2,
                mode="interchange",
                origin=ItineraryEndpoint(
                    id="naptan:SVG", name="Stevenage Rail Station"
                ),
                destination=ItineraryEndpoint(
                    id="naptan:SVG", name="Stevenage Rail Station"
                ),
                dep_time="06:42",
                arr_time="06:47",
                duration_minutes=5,
            ),
            ItineraryLeg(
                leg_index=3,
                mode="rail",
                line="London Kings Cross Rail Station to Cambridge Rail Station (Mon-Fri)",
                operator="Great Northern",
                origin=ItineraryEndpoint(
                    id="naptan:SVG", name="Stevenage Rail Station"
                ),
                destination=ItineraryEndpoint(
                    id="naptan:CBG", name="Cambridge Rail Station"
                ),
                dep_time="06:48",
                arr_time="07:18",
                duration_minutes=30,
            ),
            ItineraryLeg(
                leg_index=4,
                mode="walk",
                origin=ItineraryEndpoint(
                    id="naptan:CBG", name="Cambridge Rail Station"
                ),
                destination=ItineraryEndpoint(
                    id="ha:cambridge_office", name="Cambridge Office"
                ),
                dep_time="07:18",
                arr_time="07:28",
                duration_minutes=10,
            ),
        ]
        itin = ScheduledItinerary(
            departure_time="06:35",
            arrival_time="07:28",
            total_duration_minutes=53,
            transfers_count=1,
            robustness_score="High",
            legs=legs,
        )
        active = ActiveJourney(
            journey_id=1,
            journey_name="Morning Commute",
            from_type="location",
            from_id="ha:home",
            from_name="Home",
            to_type="location",
            to_id="ha:cambridge_office",
            to_name="Cambridge Office",
            itinerary=itin,
            legs=legs,
            expected_arrival_time="07:28",
            current_leg_index=1,  # Stuck on interchange leg
            current_status=JourneyStepStatus.AT_INTERCHANGE,
        )

        mock_ha = MagicMock(spec=HomeAssistantClient)
        # Stuart is past Hitchin on the train towards Cambridge at 06:55 (51.9600, -0.2500)
        # Stevenage is (51.9017, -0.2066), Cambridge is (52.1943, 0.1372)
        state_hitchin = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.9600, "longitude": -0.2500},
        }
        now_hitchin = datetime.datetime(2026, 9, 10, 6, 55)

        updated = update_journey_progress(active, state_hitchin, now_hitchin, mock_ha)
        assert updated is True
        # Advanced past interchange to rail leg (index 2)
        assert active.current_leg_index == 2
        assert active.current_status == JourneyStepStatus.ON_TRANSIT
        mock_ha.send_mobile_notification.assert_called_once()
        msg = mock_ha.send_mobile_notification.call_args[1]["message"]
        assert "On board Great Northern train towards Cambridge Rail Station." in msg
        assert "Expected arrival at 07:18." in msg
        assert "Next step: Walk 10m to Cambridge Office." in msg
