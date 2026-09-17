"""Unit tests for journey detection staleness filtering and connecting leg validation."""

import datetime
from unittest.mock import MagicMock, patch
from flask import Flask

from app.datasources.train_live import TrainLiveClient
from app.models.journey import Journey
from app.models.location import Location
from app.models.transit import Stop
from app.services.dispatcher.tracker.detector import detect_en_route_journey
from app.services.dispatcher.tracker.notification_formatter import (
    format_progress_notification,
)
from app.services.planner.models import (
    ItineraryEndpoint,
    ItineraryLeg,
    ScheduledItinerary,
)


def test_detect_en_route_journey_selects_current_over_stale_itinerary(
    app: Flask,
) -> None:
    """Test en-route recovery selects current itinerary instead of stale past itinerary when at an interchange station."""
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
            atco_code="naptan:CBS",
            naptan_code="CBS",
            name="Cambridge South Rail Station",
            stop_type="rail",
            latitude=52.1760,
            longitude=0.1280,
        )
        Location.create(
            id="ha:home_loc_2",
            name="Home",
            latitude=51.9200,
            longitude=-0.2100,
            ha=True,
        )
        Location.create(
            id="ha:office_cbg",
            name="Cambridge Office",
            latitude=52.1800,
            longitude=0.1300,
            ha=True,
        )
        journey = Journey.create(
            name="Commute to Cambridge",
            from_type="ha",
            from_id="ha:home_loc_2",
            from_name="Home",
            to_type="ha",
            to_id="ha:office_cbg",
            to_name="Cambridge Office",
        )

        stale_itin = ScheduledItinerary(
            departure_time="06:35",
            arrival_time="08:00",
            total_duration_minutes=85,
            transfers_count=1,
            robustness_score="High",
            legs=[
                ItineraryLeg(
                    leg_index=1,
                    mode="walk",
                    origin=ItineraryEndpoint(id="ha:home_loc_2", name="Home"),
                    destination=ItineraryEndpoint(
                        id="naptan:SVG", name="Stevenage Rail Station"
                    ),
                    dep_time="06:35",
                    arr_time="07:05",
                    duration_minutes=30,
                ),
                ItineraryLeg(
                    leg_index=2,
                    mode="rail",
                    line="Thameslink",
                    operator="Thameslink",
                    origin=ItineraryEndpoint(
                        id="naptan:SVG", name="Stevenage Rail Station"
                    ),
                    destination=ItineraryEndpoint(
                        id="naptan:CBS", name="Cambridge South Rail Station"
                    ),
                    dep_time="07:29",
                    arr_time="07:58",
                    duration_minutes=29,
                ),
            ],
        )

        current_itin = ScheduledItinerary(
            departure_time="07:35",
            arrival_time="09:00",
            total_duration_minutes=85,
            transfers_count=1,
            robustness_score="High",
            legs=[
                ItineraryLeg(
                    leg_index=1,
                    mode="walk",
                    origin=ItineraryEndpoint(id="ha:home_loc_2", name="Home"),
                    destination=ItineraryEndpoint(
                        id="naptan:SVG", name="Stevenage Rail Station"
                    ),
                    dep_time="07:35",
                    arr_time="08:05",
                    duration_minutes=30,
                ),
                ItineraryLeg(
                    leg_index=2,
                    mode="rail",
                    line="Thameslink",
                    operator="Thameslink",
                    origin=ItineraryEndpoint(
                        id="naptan:SVG", name="Stevenage Rail Station"
                    ),
                    destination=ItineraryEndpoint(
                        id="naptan:CBS", name="Cambridge South Rail Station"
                    ),
                    dep_time="08:29",
                    arr_time="08:58",
                    duration_minutes=29,
                ),
            ],
        )

        mock_live = MagicMock(spec=TrainLiveClient)
        mock_live.get_fastest_departures.return_value = [
            {
                "std": "08:29",
                "etd": "08:38",
                "platform": "4",
                "delayReason": "This train has been delayed by a fault with the signalling system",
            }
        ]

        now = datetime.datetime(2026, 9, 14, 8, 31)
        state_at_stevenage = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.9017, "longitude": -0.2066},
        }

        with patch(
            "app.services.planner.raptor.plan_journey",
            return_value=[stale_itin, current_itin],
        ):
            recovered = detect_en_route_journey(
                journey, state_at_stevenage, now, live_client=mock_live
            )
            assert recovered is not None
            assert recovered.current_leg_index == 1
            assert recovered.platform == "4"
            assert recovered.live_status == "08:38"
            assert recovered.delay_minutes == 9
            assert recovered.delay_reason == "a fault with the signalling system"
            assert recovered.legs[1].dep_time == "08:29"

            # Check formatted notification message
            _, msg, _ = format_progress_notification(recovered)
            assert "08:29" in msg
            assert "expected 08:38 due to a fault with the signalling system" in msg
            assert "Platform 4" in msg


def test_detect_en_route_journey_rejects_expired_past_legs(app: Flask) -> None:
    """Test that detect_en_route_journey rejects stale candidate legs whose arrival/departure passed."""
    with app.app_context():
        journey = Journey.create(
            name="Commute",
            from_type="ha",
            from_id="ha:home_3",
            from_name="Home",
            to_type="ha",
            to_id="ha:dest_3",
            to_name="Dest",
        )
        stale_itin = ScheduledItinerary(
            departure_time="06:30",
            arrival_time="07:15",
            total_duration_minutes=45,
            transfers_count=0,
            robustness_score="High",
            legs=[
                ItineraryLeg(
                    leg_index=1,
                    mode="rail",
                    origin=ItineraryEndpoint(
                        id="naptan:KGX", name="London King's Cross"
                    ),
                    destination=ItineraryEndpoint(id="naptan:CBG", name="Cambridge"),
                    dep_time="06:30",
                    arr_time="07:15",
                    duration_minutes=45,
                )
            ],
        )
        now = datetime.datetime(2026, 9, 14, 8, 30)
        state_at_kgx = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5302, "longitude": -0.1225},
        }
        with patch(
            "app.services.planner.raptor.plan_journey", return_value=[stale_itin]
        ):
            recovered = detect_en_route_journey(journey, state_at_kgx, now)
            assert recovered is None


def test_detect_en_route_journey_rejects_expired_connecting_transit_leg(
    app: Flask,
) -> None:
    """Test detect_en_route_journey rejects candidate itineraries whose connecting train has already passed."""
    with app.app_context():
        # Setup stops using generic London rail locations
        Stop.create(
            atco_code="9100KINGSX",
            naptan_code="9100KINGSX",
            name="London King's Cross",
            locality="London",
            stop_type="rail",
            latitude=51.531,
            longitude=-0.123,
        )
        Stop.create(
            atco_code="9100FPK",
            naptan_code="9100FPK",
            name="Finsbury Park",
            locality="London",
            stop_type="rail",
            latitude=51.564,
            longitude=-0.106,
        )
        # Commuter is at London King's Cross at 17:16 (past 16:51 connecting train)
        person_state = {
            "entity_id": "person.commuter",
            "state": "not_home",
            "attributes": {"latitude": 51.531, "longitude": -0.123},
        }
        dt_1716 = datetime.datetime(2026, 9, 14, 17, 16)

        mock_live = MagicMock(spec=TrainLiveClient)
        mock_live.get_fastest_departures.return_value = []

        journey = Journey.create(
            name="Commute Home",
            from_type="ha",
            from_id="ha:office",
            from_name="London Office",
            to_type="ha",
            to_id="ha:home",
            to_name="Home",
            primary_mode="rail",
        )

        # Plan journey returning expired connecting leg at 16:51
        expired_itin = ScheduledItinerary(
            departure_time="16:40",
            arrival_time="18:07",
            total_duration_minutes=87,
            transfers_count=1,
            robustness_score="medium",
            legs=[
                ItineraryLeg(
                    leg_index=0,
                    mode="bus",
                    origin=ItineraryEndpoint(id="ha:office", name="London Office"),
                    destination=ItineraryEndpoint(
                        id="9100KINGSX", name="London King's Cross"
                    ),
                    dep_time="16:40",
                    arr_time="16:50",
                    duration_minutes=10,
                ),
                ItineraryLeg(
                    leg_index=1,
                    mode="rail",
                    origin=ItineraryEndpoint(
                        id="9100KINGSX", name="London King's Cross"
                    ),
                    destination=ItineraryEndpoint(id="9100FPK", name="Finsbury Park"),
                    dep_time="16:51",
                    arr_time="17:35",
                    duration_minutes=44,
                ),
            ],
        )

        with patch(
            "app.services.planner.raptor.plan_journey", return_value=[expired_itin]
        ):
            recovered = detect_en_route_journey(
                journey, person_state, dt_1716, live_client=mock_live
            )
            assert recovered is None
