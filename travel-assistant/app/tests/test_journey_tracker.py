"""Comprehensive unit tests for Stuart's journey tracking and live progress updates."""

import datetime
from unittest.mock import MagicMock
from flask import Flask

from app.datasources.homeassistant import HomeAssistantClient
from app.datasources.train_live import TrainLiveClient
from app.models.location import Location
from app.models.transit import Stop
from app.services.dispatcher.tracker import (
    ActiveJourney,
    JourneyStepStatus,
    _format_transit_service_desc,
    detect_en_route_journey,
    format_progress_notification,
    resolve_live_rail_platform,
    update_journey_progress,
)
from app.services.planner.models import (
    ItineraryEndpoint,
    ItineraryLeg,
    ScheduledItinerary,
)


def _create_sample_active_journey(
    journey_id: int = 1,
    with_rail: bool = False,
) -> ActiveJourney:
    """Create a sample ActiveJourney fixture with walk -> transit -> walk legs."""
    legs = [
        ItineraryLeg(
            leg_index=1,
            mode="walk",
            origin=ItineraryEndpoint(id="ha:home", name="Home"),
            destination=ItineraryEndpoint(
                id="naptan:KGX" if with_rail else "atco:490000077E",
                name="London King's Cross" if with_rail else "King's Cross (Stop E)",
            ),
            dep_time="08:00",
            arr_time="08:08",
            duration_minutes=8,
        ),
        ItineraryLeg(
            leg_index=2,
            mode="rail" if with_rail else "bus",
            line="Thameslink" if with_rail else "73",
            operator="Govia" if with_rail else "Arriva",
            origin=ItineraryEndpoint(
                id="naptan:KGX" if with_rail else "atco:490000077E",
                name="London King's Cross" if with_rail else "King's Cross (Stop E)",
            ),
            destination=ItineraryEndpoint(
                id="naptan:CBG" if with_rail else "atco:490000077C",
                name="Cambridge" if with_rail else "Euston Station (Stop C)",
            ),
            dep_time="08:08",
            arr_time="08:22",
            duration_minutes=14,
        ),
        ItineraryLeg(
            leg_index=3,
            mode="walk",
            origin=ItineraryEndpoint(
                id="naptan:CBG" if with_rail else "atco:490000077C",
                name="Cambridge" if with_rail else "Euston Station (Stop C)",
            ),
            destination=ItineraryEndpoint(id="ha:office", name="Tech Campus"),
            dep_time="08:22",
            arr_time="08:28",
            duration_minutes=6,
        ),
    ]

    itin = ScheduledItinerary(
        departure_time="08:00",
        arrival_time="08:28",
        total_duration_minutes=28,
        transfers_count=0,
        robustness_score="High",
        legs=legs,
    )

    return ActiveJourney(
        journey_id=journey_id,
        journey_name="Daily Office Commute",
        from_type="ha",
        from_id="ha:home",
        from_name="Home",
        to_type="ha",
        to_id="ha:office",
        to_name="Tech Campus",
        itinerary=itin,
        legs=legs,
        expected_arrival_time="08:28",
        last_notification_message=None,
    )


# --- Platform Resolution Tests ---


def test_resolve_live_rail_platform_no_client() -> None:
    """Test resolve_live_rail_platform returns None, None when live_client is None."""
    plat, stat = resolve_live_rail_platform("naptan:KGX", "naptan:CBG", "08:08", None)
    assert plat is None
    assert stat is None


def test_resolve_live_rail_platform_invalid_crs() -> None:
    """Test resolve_live_rail_platform with invalid or non-rail CRS codes."""
    mock_live = MagicMock(spec=TrainLiveClient)
    # Long ATCO code
    plat, stat = resolve_live_rail_platform(
        "atco:490000077E", "atco:490000077C", "08:08", mock_live
    )
    assert plat is None
    assert stat is None
    mock_live.get_fastest_departures.assert_not_called()

    # Numeric code
    plat, stat = resolve_live_rail_platform("1234", "CBG", "08:08", mock_live)
    assert plat is None
    mock_live.get_fastest_departures.assert_not_called()


def test_resolve_live_rail_platform_matching_departure() -> None:
    """Test resolve_live_rail_platform when matching departure is found."""
    mock_live = MagicMock(spec=TrainLiveClient)
    mock_live.get_fastest_departures.return_value = [
        {"std": "08:05", "etd": "On time", "platform": "1"},
        {"std": "08:08", "etd": "Delayed", "platform": "4B"},
    ]

    plat, stat = resolve_live_rail_platform(
        "naptan:KGX", "naptan:CBG", "08:08", mock_live
    )
    assert plat == "4B"
    assert stat == "Delayed"
    mock_live.get_fastest_departures.assert_called_once_with("KGX", ["CBG"])


def test_resolve_live_rail_platform_first_departure_when_time_empty() -> None:
    """Test resolve_live_rail_platform returns first departure when scheduled_time is empty."""
    mock_live = MagicMock(spec=TrainLiveClient)
    mock_live.get_fastest_departures.return_value = [
        {"std": "08:05", "etd": "On time", "platform": "2"},
    ]
    plat, stat = resolve_live_rail_platform("KGX", "CBG", "", mock_live)
    assert plat == "2"
    assert stat == "On time"


def test_resolve_live_rail_platform_not_found_or_exception() -> None:
    """Test resolve_live_rail_platform handles empty list and exceptions gracefully."""
    mock_live = MagicMock(spec=TrainLiveClient)
    mock_live.get_fastest_departures.return_value = []
    plat, stat = resolve_live_rail_platform("KGX", "CBG", "08:08", mock_live)
    assert plat is None
    assert stat is None

    mock_live.get_fastest_departures.side_effect = RuntimeError(
        "Darwin connection reset"
    )
    plat, stat = resolve_live_rail_platform("KGX", "CBG", "08:08", mock_live)
    assert plat is None
    assert stat is None


# --- Format Transit Service Description Tests ---


def test_format_transit_service_desc() -> None:
    """Test service description formatting without duplicate mode names."""
    assert _format_transit_service_desc("bus", "73") == "Bus 73"
    assert _format_transit_service_desc("bus", "Bus 73") == "Bus 73"
    assert _format_transit_service_desc("rail", "Thameslink") == "Rail Thameslink"
    assert _format_transit_service_desc("rail", "") == "Rail"
    assert _format_transit_service_desc("", "") == "Transit"


# --- Notification Formatting Tests ---


def test_format_progress_notification_stages() -> None:
    """Test notification message formatting across all journey step stages."""
    active = _create_sample_active_journey(with_rail=True)

    # 1. PRE_DEPARTURE
    active.current_status = JourneyStepStatus.PRE_DEPARTURE
    title, msg, data = format_progress_notification(active)
    assert title == "Travel Alert: Daily Office Commute"
    assert "Leave by 08:00 (walk 8m) for Rail Thameslink" in msg
    assert "London King's Cross" in msg
    assert "Estimated arrival at Tech Campus by 08:28." in msg
    assert data["tag"] == "journey_1"
    assert data["url"] == "/journey"
    assert data["clickAction"] == "/journey"
    assert data["group"] == "travel_assistant_journeys"

    # PRE_DEPARTURE with announced platform
    active.platform = "4"
    active.live_status = "On time"
    _, msg_plat, _ = format_progress_notification(active)
    assert "(Platform 4) (On time)" in msg_plat

    # 2. EN_ROUTE_TO_STOP
    active.current_status = JourneyStepStatus.EN_ROUTE_TO_STOP
    active.current_leg_index = 0
    _, msg_en_route, _ = format_progress_notification(active)
    assert "On your way to London King's Cross." in msg_en_route
    assert "Rail Thameslink departs at 08:08." in msg_en_route

    # 3. AT_DEPARTURE_STOP (Rail)
    active.current_status = JourneyStepStatus.AT_DEPARTURE_STOP
    active.current_leg_index = 1
    active.platform = "4"
    active.live_status = "On time"
    _, msg_at_stop, _ = format_progress_notification(active)
    assert "At London King's Cross." in msg_at_stop
    assert "Platform 4 (On time)" in msg_at_stop

    # 3b. AT_DEPARTURE_STOP (Rail, platform unannounced)
    active.platform = None
    active.live_status = None
    _, msg_unannounced, _ = format_progress_notification(active)
    assert "Platform to be announced" in msg_unannounced

    # 3c. AT_DEPARTURE_STOP (Bus)
    active_bus = _create_sample_active_journey(with_rail=False)
    active_bus.current_status = JourneyStepStatus.AT_DEPARTURE_STOP
    active_bus.current_leg_index = 1
    _, msg_bus_stop, _ = format_progress_notification(active_bus)
    assert "At King's Cross (Stop E)." in msg_bus_stop
    assert "Bus 73 to Euston Station (Stop C) departs at 08:08." in msg_bus_stop

    # 4. ON_TRANSIT (with next leg walk)
    active.current_status = JourneyStepStatus.ON_TRANSIT
    active.current_leg_index = 1
    active.platform = "4"
    _, msg_transit, _ = format_progress_notification(active)
    assert "On board Rail Thameslink (Platform 4) towards Cambridge." in msg_transit
    assert "Expected arrival at 08:22." in msg_transit
    assert "Next step: Walk 6m to Tech Campus." in msg_transit

    # 4b. ON_TRANSIT (with next leg transit transfer)
    multi_active = _create_sample_active_journey()
    multi_active.legs.append(
        ItineraryLeg(
            leg_index=4,
            mode="bus",
            line="14",
            origin=ItineraryEndpoint(id="ha:office", name="Tech Campus"),
            destination=ItineraryEndpoint(id="ha:suburb", name="North Office"),
            dep_time="08:35",
            arr_time="08:50",
            duration_minutes=15,
        )
    )
    multi_active.current_status = JourneyStepStatus.ON_TRANSIT
    multi_active.current_leg_index = 1
    multi_active.legs[2].mode = "bus"
    multi_active.legs[2].line = "14"
    _, msg_transfer, _ = format_progress_notification(multi_active)
    assert "Transfer to Bus 14." in msg_transfer

    # 5. AT_INTERCHANGE
    active.current_status = JourneyStepStatus.AT_INTERCHANGE
    active.current_leg_index = 1
    active.platform = "2"
    _, msg_interchange, _ = format_progress_notification(active)
    assert "Transfer at London King's Cross:" in msg_interchange
    assert "Platform 2" in msg_interchange

    # 6. EN_ROUTE_TO_DESTINATION
    active.current_status = JourneyStepStatus.EN_ROUTE_TO_DESTINATION
    active.current_leg_index = 2
    _, msg_egress, _ = format_progress_notification(active)
    assert "Final leg: Walk to Tech Campus." in msg_egress
    assert "Estimated arrival at 08:28." in msg_egress

    # 7. ARRIVED
    active.current_status = JourneyStepStatus.ARRIVED
    _, msg_arrived, _ = format_progress_notification(active)
    assert "Journey complete: Arrived at Tech Campus (08:28)." in msg_arrived
    assert "Have a great day!" in msg_arrived


# --- Progress Update & State Transition Tests ---


def test_update_journey_progress_invalid_state_or_timeout(app: Flask) -> None:
    """Test update_journey_progress handles invalid person state and journey expiration."""
    with app.app_context():
        active = _create_sample_active_journey()
        mock_ha = MagicMock(spec=HomeAssistantClient)

        # Invalid / None state -> False
        assert (
            update_journey_progress(active, None, datetime.datetime.now(), mock_ha)
            is False
        )
        assert (
            update_journey_progress(active, {}, datetime.datetime.now(), mock_ha)
            is False
        )

        # Expired: arrival is 08:28 (508 mins), at 10:05 (605 mins > 508 + 90) -> EXPIRED
        late_dt = datetime.datetime(2026, 9, 7, 10, 5)
        stuart_state = {
            "entity_id": "person.stuart",
            "state": "home",
            "attributes": {"latitude": 51.5300, "longitude": -0.1230},
        }
        res = update_journey_progress(active, stuart_state, late_dt, mock_ha)
        assert res is False
        assert active.current_status == JourneyStepStatus.EXPIRED


def test_update_journey_progress_missed_departure_at_origin(app: Flask) -> None:
    """Test that active journey expires if Stuart does not leave origin by leave time + 2m."""
    with app.app_context():
        active = _create_sample_active_journey()
        active.current_status = JourneyStepStatus.PRE_DEPARTURE
        # Leave time is 08:00 (dep 08:08 - walk 8m)
        # At 08:03, leave time + 2 has passed and Stuart is still at home
        now_03 = datetime.datetime(2026, 9, 7, 8, 3)
        stuart_state = {
            "entity_id": "person.stuart",
            "state": "home",
            "attributes": {"latitude": 51.5300, "longitude": -0.1230},
        }
        mock_ha = MagicMock(spec=HomeAssistantClient)
        res = update_journey_progress(active, stuart_state, now_03, mock_ha)
        assert res is False
        assert active.current_status == JourneyStepStatus.EXPIRED


def test_update_journey_progress_full_journey_progression(app: Flask) -> None:
    """Test end-to-end journey progression through all stages from origin to arrival."""
    with app.app_context():
        # Setup stops and locations
        Location.create(
            id="ha:home", name="Home", latitude=51.5350, longitude=-0.1230, ha=True
        )
        Location.create(
            id="ha:office",
            name="Tech Campus",
            latitude=51.5200,
            longitude=-0.1340,
            ha=True,
        )
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
            latitude=51.5240,
            longitude=-0.1325,
        )

        active = _create_sample_active_journey(with_rail=False)
        active.current_status = JourneyStepStatus.PRE_DEPARTURE
        active.last_notification_message = "Leave by 08:00 (walk 8m) for Bus 73 from King's Cross (Stop E) departing at 08:08. Estimated arrival at Tech Campus by 08:28."

        mock_ha = MagicMock(spec=HomeAssistantClient)

        # 1. Stuart is at home at 07:50 (PRE_DEPARTURE) -> no duplicate notification
        now_50 = datetime.datetime(2026, 9, 7, 7, 50)
        state_home = {
            "entity_id": "person.stuart",
            "state": "home",
            "attributes": {"latitude": 51.5350, "longitude": -0.1230},
        }
        res1 = update_journey_progress(active, state_home, now_50, mock_ha)
        assert res1 is False
        assert active.current_status == JourneyStepStatus.PRE_DEPARTURE
        mock_ha.send_mobile_notification.assert_not_called()

        # 2. Stuart starts walking: midway between Home and Stop E (51.5325, -0.1228)
        now_55 = datetime.datetime(2026, 9, 7, 7, 55)
        state_walking = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5325, "longitude": -0.1228},
        }
        res2 = update_journey_progress(active, state_walking, now_55, mock_ha)
        assert res2 is True
        assert active.current_status == JourneyStepStatus.EN_ROUTE_TO_STOP
        mock_ha.send_mobile_notification.assert_called_once()
        call_msg = mock_ha.send_mobile_notification.call_args[1]["message"]
        assert "On your way to King's Cross (Stop E)." in call_msg

        # 3. Stuart arrives at King's Cross Stop E (51.5302, -0.1225)
        mock_ha.reset_mock()
        now_02 = datetime.datetime(2026, 9, 7, 8, 2)
        state_at_stop = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5302, "longitude": -0.1225},
        }
        res3 = update_journey_progress(active, state_at_stop, now_02, mock_ha)
        assert res3 is True
        assert active.current_leg_index == 1
        assert active.current_status == JourneyStepStatus.AT_DEPARTURE_STOP
        call_msg3 = mock_ha.send_mobile_notification.call_args[1]["message"]
        assert "At King's Cross (Stop E)." in call_msg3

        # 4. Bus departs at 08:08; at 08:12 Stuart is on transit midway to Euston (51.5270, -0.1280)
        mock_ha.reset_mock()
        now_12 = datetime.datetime(2026, 9, 7, 8, 12)
        state_transit = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5270, "longitude": -0.1280},
        }
        res4 = update_journey_progress(active, state_transit, now_12, mock_ha)
        assert res4 is True
        assert active.current_status == JourneyStepStatus.ON_TRANSIT
        call_msg4 = mock_ha.send_mobile_notification.call_args[1]["message"]
        assert "On board Bus 73 towards Euston Station (Stop C)." in call_msg4
        assert "Next step: Walk 6m to Tech Campus." in call_msg4

        # 5. Bus reaches Euston Stop C (51.5240, -0.1325) -> Stuart exits and begins final walk
        mock_ha.reset_mock()
        now_22 = datetime.datetime(2026, 9, 7, 8, 22)
        state_euston = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5240, "longitude": -0.1325},
        }
        res5 = update_journey_progress(active, state_euston, now_22, mock_ha)
        assert res5 is True
        assert active.current_leg_index == 2
        assert active.current_status == JourneyStepStatus.EN_ROUTE_TO_DESTINATION
        call_msg5 = mock_ha.send_mobile_notification.call_args[1]["message"]
        assert "Final leg: Walk to Tech Campus." in call_msg5

        # 6. Stuart arrives at Tech Campus (51.5200, -0.1340)
        mock_ha.reset_mock()
        now_28 = datetime.datetime(2026, 9, 7, 8, 28)
        state_arrived = {
            "entity_id": "person.stuart",
            "state": "office",
            "attributes": {"latitude": 51.5200, "longitude": -0.1340},
        }
        res6 = update_journey_progress(active, state_arrived, now_28, mock_ha)
        assert res6 is True
        assert active.current_status == JourneyStepStatus.ARRIVED
        call_msg6 = mock_ha.send_mobile_notification.call_args[1]["message"]
        assert "Journey complete: Arrived at Tech Campus (08:28)." in call_msg6

        # 7. Next tick when already arrived -> returns False (no duplicate notification)
        mock_ha.reset_mock()
        res7 = update_journey_progress(active, state_arrived, now_28, mock_ha)
        assert res7 is False
        mock_ha.send_mobile_notification.assert_not_called()


def test_update_journey_progress_live_platform_update(app: Flask) -> None:
    """Test live platform update triggered while Stuart is waiting at station."""
    with app.app_context():
        active = _create_sample_active_journey(with_rail=True)
        active.current_status = JourneyStepStatus.AT_DEPARTURE_STOP
        active.current_leg_index = 1
        active.platform = None
        active.last_notification_message = "At London King's Cross. Rail Thameslink to Cambridge departs at 08:08 from Platform to be announced."

        mock_ha = MagicMock(spec=HomeAssistantClient)
        mock_live = MagicMock(spec=TrainLiveClient)
        mock_live.get_fastest_departures.return_value = [
            {"std": "08:08", "etd": "On time", "platform": "9"},
        ]

        now = datetime.datetime(2026, 9, 7, 8, 4)
        stuart_state = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5308, "longitude": -0.1238},
        }

        res = update_journey_progress(
            active,
            stuart_state,
            now,
            mock_ha,
            live_client=mock_live,
        )
        assert res is True
        assert active.platform == "9"
        call_msg = mock_ha.send_mobile_notification.call_args[1]["message"]
        assert "Platform 9 (On time)" in call_msg


def test_update_journey_progress_stuart_wanders_far_away(app: Flask) -> None:
    """Test that if Stuart is far off the route during initial walk, active journey expires."""
    with app.app_context():
        Location.create(
            id="ha:home", name="Home", latitude=51.5300, longitude=-0.1230, ha=True
        )
        Stop.create(
            atco_code="490000077E",
            naptan_code="490000077E",
            name="King's Cross (Stop E)",
            stop_type="bus",
            latitude=51.5302,
            longitude=-0.1225,
        )

        active = _create_sample_active_journey()
        active.current_status = JourneyStepStatus.PRE_DEPARTURE

        mock_ha = MagicMock(spec=HomeAssistantClient)
        # Stuart at latitude 52.0, longitude 0.0 (~50km away)
        stuart_state = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 52.0, "longitude": 0.0},
        }
        res = update_journey_progress(
            active,
            stuart_state,
            datetime.datetime(2026, 9, 7, 7, 55),
            mock_ha,
        )
        assert res is False
        assert active.current_status == JourneyStepStatus.EXPIRED


def test_active_journey_post_init_defaults() -> None:
    """Test ActiveJourney __post_init__ populates legs and expected_arrival_time."""
    itin = ScheduledItinerary(
        departure_time="08:00",
        arrival_time="08:45",
        total_duration_minutes=45,
        transfers_count=0,
        robustness_score="High",
        legs=[
            ItineraryLeg(
                leg_index=1,
                mode="bus",
                origin=ItineraryEndpoint(id="1", name="A"),
                destination=ItineraryEndpoint(id="2", name="B"),
                dep_time="08:00",
                arr_time="08:45",
                duration_minutes=45,
            )
        ],
    )
    active = ActiveJourney(
        journey_id=5,
        journey_name="Test Journey",
        from_type="bus",
        from_id="1",
        from_name="A",
        to_type="bus",
        to_id="2",
        to_name="B",
        itinerary=itin,
    )
    assert len(active.legs) == 1
    assert active.expected_arrival_time == "08:45"


def test_format_progress_notification_empty_leg_fallbacks() -> None:
    """Test notification formatting fallbacks when current_leg is None."""
    active = _create_sample_active_journey()
    active.current_leg_index = 99  # beyond legs length

    active.current_status = JourneyStepStatus.AT_DEPARTURE_STOP
    _, msg1, _ = format_progress_notification(active)
    assert "At departure stop for Tech Campus." in msg1

    active.current_status = JourneyStepStatus.ON_TRANSIT
    _, msg2, _ = format_progress_notification(active)
    assert "In transit towards Tech Campus." in msg2

    active.current_status = JourneyStepStatus.AT_INTERCHANGE
    _, msg3, _ = format_progress_notification(active)
    assert "Interchange stop: transfer to connecting service." in msg3

    # Fallback status
    active.current_status = JourneyStepStatus.EXPIRED
    _, msg4, _ = format_progress_notification(active)
    assert "Journey update: en route to Tech Campus." in msg4


def test_determine_transit_arrival_status_coverage() -> None:
    """Test _determine_transit_arrival_status edge cases."""
    from app.services.dispatcher.tracker import _determine_transit_arrival_status

    active = _create_sample_active_journey()
    # Past last leg -> EN_ROUTE_TO_DESTINATION
    active.current_leg_index = 10
    assert (
        _determine_transit_arrival_status(active)
        == JourneyStepStatus.EN_ROUTE_TO_DESTINATION
    )

    # Multi-transit connection where next leg is not walk
    active.current_leg_index = 1
    active.legs[-1].mode = "bus"
    assert _determine_transit_arrival_status(active) == JourneyStepStatus.AT_INTERCHANGE


def test_update_journey_progress_transit_origin_proximity_and_interchange(
    app: Flask,
) -> None:
    """Test transit leg origin proximity and waiting at interchange stop."""
    with app.app_context():
        # Journey starting directly with rail (leg index 0 is rail)
        active = _create_sample_active_journey(with_rail=True)
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
        active_multi = _create_sample_active_journey(with_rail=True)
        active_multi.current_leg_index = 1
        active_multi.current_status = JourneyStepStatus.ON_TRANSIT
        # If leg is rail and Stuart is at origin station
        res_inter = update_journey_progress(
            active_multi, stuart_at_kgx, now_before, mock_ha
        )
        assert res_inter is True
        assert active_multi.current_status == JourneyStepStatus.AT_DEPARTURE_STOP


def test_update_journey_progress_notification_exception_handling(app: Flask) -> None:
    """Test update_journey_progress catches notification dispatch errors gracefully."""
    with app.app_context():
        active = _create_sample_active_journey()
        active.current_status = JourneyStepStatus.EN_ROUTE_TO_DESTINATION
        active.current_leg_index = 2

        Location.create(
            id="ha:office",
            name="Tech Campus",
            latitude=51.5200,
            longitude=-0.1340,
            ha=True,
        )
        stuart_arrived = {
            "entity_id": "person.stuart",
            "state": "office",
            "attributes": {"latitude": 51.5200, "longitude": -0.1340},
        }

        mock_ha = MagicMock(spec=HomeAssistantClient)
        mock_ha.send_mobile_notification.side_effect = RuntimeError(
            "Push notification failed"
        )

        now = datetime.datetime(2026, 9, 7, 8, 28)
        res = update_journey_progress(active, stuart_arrived, now, mock_ha)
        assert res is False

        # Exception during regular progress notification (not arrival)
        active.current_status = JourneyStepStatus.PRE_DEPARTURE
        active.current_leg_index = 0
        state_walking = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5325, "longitude": -0.1228},
        }
        res_prog_err = update_journey_progress(active, state_walking, now, mock_ha)
        assert res_prog_err is False


def test_update_journey_progress_past_last_leg_and_transfer_walk(app: Flask) -> None:
    """Test update_journey_progress when current_leg_index exceeds legs or is intermediate walk."""
    with app.app_context():
        active = _create_sample_active_journey()
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
        multi = _create_sample_active_journey()
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


# --- En-Route Recovery Tests ---


def test_detect_en_route_journey_invalid_or_not_en_route(app: Flask) -> None:
    """Test detect_en_route_journey returns None for non-en-route states."""
    from unittest.mock import patch
    from app.models.journey import Journey

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
    from unittest.mock import patch
    from app.models.journey import Journey

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
