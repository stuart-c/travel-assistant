"""Comprehensive unit tests for Stuart's journey tracking and live progress updates."""

import datetime
from unittest.mock import MagicMock, patch
from flask import Flask

from app.datasources.homeassistant import HomeAssistantClient
from app.datasources.train_live import TrainLiveClient
from app.models.journey import Journey
from app.models.location import Location
from app.models.setting import Setting
from app.models.timetable import (
    Timetable,
    TimetableContent,
    TimetableStop,
    TimetableTrip,
)
from app.models.transit import Stop
from app.services.dispatcher.tracker import (
    ActiveJourney,
    JourneyStepStatus,
    LiveRailStatus,
    _format_platform_label,
    _format_transit_service_desc,
    _format_upcoming_change_platforms,
    _realign_active_journey_timings,
    clear_active_journey_session,
    detect_en_route_journey,
    format_next_step_for_departure,
    format_progress_notification,
    get_journey_live_tracking_data,
    load_active_journey_sessions,
    resolve_live_rail_arrival_platform,
    resolve_live_rail_platform,
    save_active_journey_session,
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
    """Test resolve_live_rail_platform returns default LiveRailStatus when live_client is None."""
    res = resolve_live_rail_platform("naptan:KGX", "naptan:CBG", "08:08", None)
    assert isinstance(res, LiveRailStatus)
    assert res.platform is None
    assert res.etd is None
    assert res.delay_minutes == 0
    assert res.delay_reason is None


def test_resolve_live_rail_platform_invalid_crs() -> None:
    """Test resolve_live_rail_platform with invalid or non-rail CRS codes."""
    mock_live = MagicMock(spec=TrainLiveClient)
    # Long ATCO code
    res = resolve_live_rail_platform(
        "atco:490000077E", "atco:490000077C", "08:08", mock_live
    )
    assert res.platform is None
    assert res.etd is None
    mock_live.get_fastest_departures.assert_not_called()

    # Numeric code
    res = resolve_live_rail_platform("1234", "CBG", "08:08", mock_live)
    assert res.platform is None
    assert res.etd is None
    mock_live.get_fastest_departures.assert_not_called()


def test_resolve_live_rail_platform_matching_departure() -> None:
    """Test resolve_live_rail_platform when matching departure is found."""
    mock_live = MagicMock(spec=TrainLiveClient)
    mock_live.get_fastest_departures.return_value = [
        {"std": "08:05", "etd": "On time", "platform": "1"},
        {
            "std": "08:08",
            "etd": "Delayed",
            "platform": "4B",
            "delayReason": "This service has been delayed by a fault with the signalling system",
        },
    ]

    res = resolve_live_rail_platform("naptan:KGX", "naptan:CBG", "08:08", mock_live)
    assert res.platform == "4B"
    assert res.etd == "Delayed"
    assert res.delay_reason == "a fault with the signalling system"
    mock_live.get_fastest_departures.assert_called_once_with("KGX", ["CBG"])


def test_resolve_live_rail_platform_first_departure_when_time_empty() -> None:
    """Test resolve_live_rail_platform returns first departure when scheduled_time is empty."""
    mock_live = MagicMock(spec=TrainLiveClient)
    mock_live.get_fastest_departures.return_value = [
        {"std": "08:05", "etd": "On time", "platform": "2"},
    ]
    res = resolve_live_rail_platform("KGX", "CBG", "", mock_live)
    assert res.platform == "2"
    assert res.etd == "On time"


def test_resolve_live_rail_platform_not_found_or_exception() -> None:
    """Test resolve_live_rail_platform handles empty list and exceptions gracefully."""
    mock_live = MagicMock(spec=TrainLiveClient)
    mock_live.get_fastest_departures.return_value = []
    res = resolve_live_rail_platform("KGX", "CBG", "08:08", mock_live)
    assert res.platform is None
    assert res.etd is None

    mock_live.get_fastest_departures.side_effect = RuntimeError(
        "Darwin connection reset"
    )
    res = resolve_live_rail_platform("KGX", "CBG", "08:08", mock_live)
    assert res.platform is None
    assert res.etd is None


def test_resolve_live_rail_platform_with_atco_and_tiploc() -> None:
    """Test resolve_live_rail_platform successfully maps ATCO and TIPLOC codes to CRS."""
    mock_live = MagicMock(spec=TrainLiveClient)
    mock_live.get_fastest_departures.return_value = [
        {"std": "08:15", "etd": "08:18", "platform": "1"},
    ]
    res = resolve_live_rail_platform(
        "atco:9100KNGX", "atco:9100PADTON", "08:15", mock_live
    )
    assert res.platform == "1"
    assert res.etd == "08:18"
    assert res.delay_minutes == 3
    mock_live.get_fastest_departures.assert_called_once_with("KGX", ["PAD"])


def test_resolve_live_rail_platform_with_openapi_dict() -> None:
    """Test resolve_live_rail_platform correctly extracts platforms from Darwin OpenAPI DeparturesBoard dict."""
    mock_live = MagicMock(spec=TrainLiveClient)
    mock_live.get_fastest_departures.return_value = {
        "departures": [
            {
                "crs": "PAD",
                "service": {
                    "std": "08:15",
                    "etd": "08:20",
                    "platform": "3",
                    "delayReason": "This service has been delayed by a track inspection",
                    "cancelReason": None,
                    "isCancelled": False,
                },
            }
        ]
    }

    res = resolve_live_rail_platform("KGX", "PAD", "08:15", mock_live)
    assert res.platform == "3"
    assert res.etd == "08:20"
    assert res.delay_minutes == 5
    assert res.delay_reason == "a track inspection"
    mock_live.get_fastest_departures.assert_called_once_with("KGX", ["PAD"])


def test_resolve_live_rail_platform_fallback_to_departure_board() -> None:
    """Test resolve_live_rail_platform falls back to get_departure_board when fastest departures has no platform."""
    mock_live = MagicMock(spec=TrainLiveClient)
    # GetFastestDepartures returns service without platform
    mock_live.get_fastest_departures.return_value = {
        "departures": [
            {
                "crs": "PAD",
                "service": {
                    "std": "08:15",
                    "etd": "On time",
                    "platform": None,
                },
            }
        ]
    }
    # GetDepartureBoard returns full board with platform
    mock_live.get_departure_board.return_value = {
        "trainServices": [
            {
                "std": "08:15",
                "etd": "On time",
                "platform": "5A",
            }
        ]
    }

    res = resolve_live_rail_platform("KGX", "PAD", "08:15", mock_live)
    assert res.platform == "5A"
    assert res.etd == "On time"
    mock_live.get_departure_board.assert_called_once_with(
        crs="KGX", filter_crs="PAD", num_rows=5
    )


def test_get_journey_live_tracking_data_with_rail_lookahead(app: Flask) -> None:
    """Test get_journey_live_tracking_data resolves platform for connecting rail leg during initial walk."""
    with app.app_context():
        active = _create_sample_active_journey(journey_id=1, with_rail=True)
        # Configure rail leg with ATCO codes
        active.legs[1].origin.id = "atco:9100KNGX"
        active.legs[1].destination.id = "atco:9100PADTON"
        active.current_leg_index = 0  # Walking leg before train

        mock_live = MagicMock(spec=TrainLiveClient)
        mock_live.get_fastest_departures.return_value = [
            {"std": "08:08", "etd": "08:12", "platform": "9"},
        ]

        data = get_journey_live_tracking_data(
            journey_id=1,
            live_client=mock_live,
            active_journeys={1: active},
        )
        assert data["selected_journey"] is not None
        assert data["selected_journey"]["is_active"] is True
        assert data["selected_journey"]["platform"] == "9"
        assert data["selected_journey"]["live_status"] == "08:12"


# --- Format Transit Service Description Tests ---


def test_format_transit_service_desc() -> None:
    """Test service description formatting without duplicate mode names."""
    assert _format_transit_service_desc("bus", "73") == "Bus 73"
    assert _format_transit_service_desc("bus", "Bus 73") == "Bus 73"
    assert _format_transit_service_desc("rail", "Thameslink") == "Rail Thameslink"
    assert _format_transit_service_desc("rail", "") == "Rail"
    assert _format_transit_service_desc("", "") == "Transit"
    # Foot modes
    assert _format_transit_service_desc("interchange") == "Transfer"
    assert _format_transit_service_desc("walk") == "Transfer"
    # Complex rail timetable names with day suffixes and endpoint descriptions
    assert (
        _format_transit_service_desc(
            "rail",
            "London Kings Cross Rail Station to Cambridge Rail Station (Mon-Fri)",
            operator="Great Northern",
            destination="Cambridge Rail Station",
        )
        == "Great Northern train towards Cambridge Rail Station"
    )
    # Without destination
    assert (
        _format_transit_service_desc(
            "rail",
            "London Kings Cross Rail Station to Cambridge Rail Station (Mon-Fri)",
            operator="Great Northern",
        )
        == "Great Northern train"
    )
    # Bus route prefix with colon
    assert (
        _format_transit_service_desc(
            "bus",
            "Bus SB1: Woodcock Road to Bus Station (Mon-Sat)",
        )
        == "Bus SB1"
    )
    assert (
        _format_transit_service_desc(
            "bus",
            "Bus SB1: Woodcock Road to Bus Station (Mon-Sat)",
            operator="Arriva",
        )
        == "Arriva Bus SB1"
    )
    assert (
        _format_transit_service_desc(
            "bus",
            "SB1: Woodcock Road to Bus Station",
            operator="Arriva",
        )
        == "Arriva SB1"
    )


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
    assert data["url"] == "/journey?journey_id=1"
    assert data["clickAction"] == "/journey?journey_id=1"
    assert data["group"] == "travel_assistant_journeys"
    assert data["persistent"] is True
    assert data["sticky"] is True
    assert data["actions"] == [
        {"action": "URI", "title": "View Journey Plan", "uri": "/journey?journey_id=1"}
    ]

    # PRE_DEPARTURE with announced platform
    active.platform = "4"
    active.live_status = "On time"
    _, msg_plat, _ = format_progress_notification(active)
    assert "(Platform 4)" in msg_plat
    assert "departing at 08:08 (scheduled 08:08, expected 08:08 - on time)" in msg_plat

    # 2. EN_ROUTE_TO_STOP
    active.current_status = JourneyStepStatus.EN_ROUTE_TO_STOP
    active.current_leg_index = 0
    _, msg_en_route, _ = format_progress_notification(active)
    assert "On your way to London King's Cross." in msg_en_route
    assert (
        "Rail Thameslink (Platform 4) departs at 08:08 (scheduled 08:08, expected 08:08 - on time)."
        in msg_en_route
    )

    # 3. AT_DEPARTURE_STOP (Rail)
    active.current_status = JourneyStepStatus.AT_DEPARTURE_STOP
    active.current_leg_index = 1
    active.platform = "4"
    active.live_status = "On time"
    _, msg_at_stop, _ = format_progress_notification(active)
    assert "At London King's Cross." in msg_at_stop
    assert "from Platform 4" in msg_at_stop
    assert "departs at 08:08 (scheduled 08:08, expected 08:08 - on time)" in msg_at_stop

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
    assert (
        "Bus 73 to Euston Station (Stop C) departs at 08:08 (scheduled)."
        in msg_bus_stop
    )

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
    assert (
        "Transfer at Euston Station (Stop C) (stands to be announced) to Bus 14 departing at 08:22 (scheduled)."
        in msg_transfer
    )

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
    _, msg_arrived, data_arrived = format_progress_notification(active)
    assert "Journey complete: Arrived at Tech Campus (08:28)." in msg_arrived
    assert "Have a great day!" in msg_arrived
    assert data_arrived["persistent"] is False
    assert data_arrived["sticky"] is False


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
        active.last_notification_message = "Leave by 08:00 (walk 8m) for Bus 73 from King's Cross (Stop E) departing at 08:08 (scheduled). Estimated arrival at Tech Campus by 08:28."

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
        active.last_notification_message = "At London King's Cross. Rail Thameslink to Cambridge departs at 08:08 (scheduled) from Platform to be announced."

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
        assert "from Platform 9" in call_msg
        assert (
            "departs at 08:08 (scheduled 08:08, expected 08:08 - on time)" in call_msg
        )


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


def test_detect_en_route_journey_selects_current_over_stale_itinerary(
    app: Flask,
) -> None:
    """Test en-route recovery selects current itinerary instead of stale past itinerary when at an interchange station."""
    from unittest.mock import MagicMock, patch
    from app.models.journey import Journey

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
            title, msg, data = format_progress_notification(recovered)
            assert "08:29" in msg
            assert (
                "scheduled 08:29, expected 08:38 due to a fault with the signalling system"
                in msg
            )
            assert "Platform 4" in msg


def test_detect_en_route_journey_rejects_expired_past_legs(app: Flask) -> None:
    """Test that detect_en_route_journey rejects stale candidate legs whose arrival/departure passed."""
    from unittest.mock import patch
    from app.models.journey import Journey

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


def test_format_notification_with_custom_ingress_panel_slug(app: Flask) -> None:
    """Test that notifications route clickAction to the configured Home Assistant ingress panel slug."""
    with app.app_context():
        Setting.set_val("ingress_panel_slug", "1a842e7e_travel_assistant_dev")
        active = _create_sample_active_journey(with_rail=True)
        active.current_status = JourneyStepStatus.ON_TRANSIT
        title, msg, data = format_progress_notification(active)
        assert data["url"] == "/1a842e7e_travel_assistant_dev/journey?journey_id=1"
        assert (
            data["clickAction"] == "/1a842e7e_travel_assistant_dev/journey?journey_id=1"
        )
        assert data["actions"] == [
            {
                "action": "URI",
                "title": "View Journey Plan",
                "uri": "/1a842e7e_travel_assistant_dev/journey?journey_id=1",
            }
        ]


def test_format_progress_notification_interchange_foot_modes() -> None:
    """Test that interchange/platform_transfer legs produce clear transfer messages instead of on-board messages."""
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
            origin=ItineraryEndpoint(id="naptan:SVG", name="Stevenage Rail Station"),
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
            origin=ItineraryEndpoint(id="naptan:SVG", name="Stevenage Rail Station"),
            destination=ItineraryEndpoint(
                id="naptan:CBG", name="Cambridge Rail Station"
            ),
            dep_time="06:48",
            arr_time="07:18",
            duration_minutes=30,
        ),
    ]
    itin = ScheduledItinerary(
        departure_time="06:35",
        arrival_time="07:18",
        total_duration_minutes=43,
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
        to_type="station",
        to_id="naptan:CBG",
        to_name="Cambridge Rail Station",
        itinerary=itin,
        legs=legs,
        expected_arrival_time="07:18",
        current_leg_index=1,
        current_status=JourneyStepStatus.AT_INTERCHANGE,
    )

    _, msg, _ = format_progress_notification(active)
    assert "Transfer at Stevenage Rail Station" in msg
    assert "Great Northern train towards Cambridge Rail Station" in msg
    assert "06:48" in msg
    assert "On board Interchange" not in msg


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
        # Hitchin is ~7.5km from Stevenage, well along the corridor
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


def test_format_next_step_for_departure_scenarios() -> None:
    """Test format_next_step_for_departure across varied transit and walking combinations."""
    legs = [
        ItineraryLeg(
            leg_index=1,
            mode="walk",
            origin=ItineraryEndpoint(id="ha:office", name="Office"),
            destination=ItineraryEndpoint(id="ha:shuttle_bus", name="Shuttle Bus"),
            dep_time="17:36",
            arr_time="17:40",
            duration_minutes=4,
        ),
        ItineraryLeg(
            leg_index=2,
            mode="bus",
            line="Shuttle Bus (Evening)",
            operator=None,
            origin=ItineraryEndpoint(id="ha:shuttle_bus", name="Shuttle Bus"),
            destination=ItineraryEndpoint(
                id="naptan:9100CAMBNTH", name="Cambridge North Rail Station"
            ),
            dep_time="17:40",
            arr_time="17:50",
            duration_minutes=10,
        ),
        ItineraryLeg(
            leg_index=3,
            mode="rail",
            line="Kings Lynn Rail Station to London Kings Cross Rail Station (Mon-Fri)",
            operator="Great Northern",
            origin=ItineraryEndpoint(
                id="naptan:9100CAMBNTH",
                name="Cambridge North Rail Station",
                platform="2",
            ),
            destination=ItineraryEndpoint(
                id="naptan:9100STEVNGE", name="Stevenage Rail Station"
            ),
            dep_time="17:54",
            arr_time="18:39",
            duration_minutes=45,
        ),
        ItineraryLeg(
            leg_index=4,
            mode="walk",
            origin=ItineraryEndpoint(
                id="naptan:9100STEVNGE", name="Stevenage Rail Station"
            ),
            destination=ItineraryEndpoint(id="ha:home", name="Home"),
            dep_time="18:39",
            arr_time="18:45",
            duration_minutes=6,
        ),
    ]

    # 1. From the shuttle bus leg (index 1), following transit is Great Northern train with platform
    next_step = format_next_step_for_departure(
        legs, current_transit_leg=legs[1], only_transit=False
    )
    assert (
        next_step
        == " Next step: Transfer at Cambridge North Rail Station (arrive stand to be announced, depart Platform 2) to board Great Northern train to Stevenage Rail Station departing at 17:54 (scheduled)."
    )

    # 2. From the rail leg (index 2), next step is final walk when only_transit is False
    next_walk = format_next_step_for_departure(
        legs, current_transit_leg=legs[2], only_transit=False
    )
    assert next_walk == " Next step: Walk 6m to Home."

    # 3. From the rail leg (index 2), next step is empty when only_transit is True
    assert (
        format_next_step_for_departure(
            legs, current_transit_leg=legs[2], only_transit=True
        )
        == ""
    )

    # 4. Same origin connecting transit
    same_orig_legs = [
        ItineraryLeg(
            leg_index=1,
            mode="rail",
            line="Thameslink",
            origin=ItineraryEndpoint(id="naptan:KGX", name="London King's Cross"),
            destination=ItineraryEndpoint(id="naptan:CBG", name="Cambridge"),
            dep_time="08:14",
            arr_time="09:00",
            duration_minutes=46,
        ),
        ItineraryLeg(
            leg_index=2,
            mode="rail",
            line="Great Northern",
            operator="Great Northern",
            origin=ItineraryEndpoint(id="naptan:KGX", name="London King's Cross"),
            destination=ItineraryEndpoint(id="naptan:PBO", name="Peterborough"),
            dep_time="08:30",
            arr_time="09:15",
            duration_minutes=45,
        ),
    ]
    same_orig_step = format_next_step_for_departure(
        same_orig_legs, current_transit_leg=same_orig_legs[0]
    )
    assert (
        same_orig_step
        == " Next step: Arrive at Cambridge, walk to London King's Cross to board Rail Great Northern to Peterborough departing at 08:30 (scheduled)."
    )

    # 5. Empty legs fallback
    assert format_next_step_for_departure([]) == ""


def test_format_progress_notification_at_departure_stop_connecting_train() -> None:
    """Test AT_DEPARTURE_STOP notification includes connecting train details after shuttle bus."""
    legs = [
        ItineraryLeg(
            leg_index=1,
            mode="walk",
            origin=ItineraryEndpoint(id="ha:office", name="Office"),
            destination=ItineraryEndpoint(id="ha:shuttle_bus", name="Shuttle Bus"),
            dep_time="17:36",
            arr_time="17:40",
            duration_minutes=4,
        ),
        ItineraryLeg(
            leg_index=2,
            mode="bus",
            line="Shuttle Bus (Evening)",
            operator=None,
            origin=ItineraryEndpoint(id="ha:shuttle_bus", name="Shuttle Bus"),
            destination=ItineraryEndpoint(
                id="naptan:9100CAMBNTH", name="Cambridge North Rail Station"
            ),
            dep_time="17:40",
            arr_time="17:50",
            duration_minutes=10,
        ),
        ItineraryLeg(
            leg_index=3,
            mode="rail",
            line="Kings Lynn Rail Station to London Kings Cross Rail Station (Mon-Fri)",
            operator="Great Northern",
            origin=ItineraryEndpoint(
                id="naptan:9100CAMBNTH", name="Cambridge North Rail Station"
            ),
            destination=ItineraryEndpoint(
                id="naptan:9100STEVNGE", name="Stevenage Rail Station"
            ),
            dep_time="17:54",
            arr_time="18:39",
            duration_minutes=45,
        ),
        ItineraryLeg(
            leg_index=4,
            mode="walk",
            origin=ItineraryEndpoint(
                id="naptan:9100STEVNGE", name="Stevenage Rail Station"
            ),
            destination=ItineraryEndpoint(id="ha:home", name="Home"),
            dep_time="18:39",
            arr_time="18:45",
            duration_minutes=6,
        ),
    ]
    itin = ScheduledItinerary(
        departure_time="17:36",
        arrival_time="18:45",
        total_duration_minutes=69,
        transfers_count=2,
        robustness_score="high",
        legs=legs,
    )
    active = ActiveJourney(
        journey_id=2,
        journey_name="Evening Commute",
        from_type="ha",
        from_id="ha:office",
        from_name="Office",
        to_type="ha",
        to_id="ha:home",
        to_name="Home",
        itinerary=itin,
        legs=legs,
        current_leg_index=0,  # Detected at departure stop after initial walk
        current_status=JourneyStepStatus.AT_DEPARTURE_STOP,
        expected_arrival_time="18:45",
    )

    # 1. AT_DEPARTURE_STOP
    _, msg, _ = format_progress_notification(active)
    assert "At Shuttle Bus." in msg
    assert (
        "Shuttle Bus to Cambridge North Rail Station departs at 17:40 (scheduled)."
        in msg
    )
    assert (
        "Next step: Transfer at Cambridge North Rail Station (platforms to be announced) to board Great Northern train to Stevenage Rail Station departing at 17:54 (scheduled)."
        in msg
    )

    # 2. PRE_DEPARTURE
    active.current_status = JourneyStepStatus.PRE_DEPARTURE
    _, msg_pre, _ = format_progress_notification(active)
    assert "Leave by 17:36 (walk 4m)" in msg_pre
    assert (
        "Next step: Transfer at Cambridge North Rail Station (platforms to be announced) to board Great Northern train to Stevenage Rail Station departing at 17:54 (scheduled)."
        in msg_pre
    )

    # 3. EN_ROUTE_TO_STOP
    active.current_status = JourneyStepStatus.EN_ROUTE_TO_STOP
    _, msg_en_route, _ = format_progress_notification(active)
    assert "On your way to Shuttle Bus." in msg_en_route
    assert (
        "Next step: Transfer at Cambridge North Rail Station (platforms to be announced) to board Great Northern train to Stevenage Rail Station departing at 17:54 (scheduled)."
        in msg_en_route
    )


def test_format_progress_notification_bus_interchange_no_platform() -> None:
    """Test AT_INTERCHANGE for bus does not include 'Platform' or 'Platform to be announced'."""
    active = _create_sample_active_journey(with_rail=False)
    active.current_status = JourneyStepStatus.AT_INTERCHANGE
    active.current_leg_index = 1
    active.platform = None
    _, msg, _ = format_progress_notification(active)
    assert "Platform" not in msg
    assert (
        "Transfer at King's Cross (Stop E): Board Bus 73 departing at 08:08 (scheduled)."
        in msg
    )

    # Even if active.platform was mistakenly populated with a rail platform number, bus ignores it
    active.platform = "3"
    _, msg_ignored, _ = format_progress_notification(active)
    assert "Platform" not in msg_ignored

    # But if active.platform has a stand / stop indicator, it is formatted gracefully
    active.platform = "Stop G"
    _, msg_stand, _ = format_progress_notification(active)
    assert "from Stop G" in msg_stand


def test_format_progress_notification_evening_home_arrival_greeting() -> None:
    """Test ARRIVED notification uses actual arrival time and evening home greeting."""
    active = _create_sample_active_journey(with_rail=True)
    active.to_name = "Home"
    active.to_id = "ha:home"
    active.journey_name = "Commute Home"
    active.current_status = JourneyStepStatus.ARRIVED
    active.expected_arrival_time = "18:07"

    # Evening arrival at 18:46
    evening_dt = datetime.datetime(2026, 9, 14, 18, 46)
    _, msg_evening, _ = format_progress_notification(active, current_dt=evening_dt)
    assert "Arrived at Home (18:46)." in msg_evening
    assert "Welcome home! Have a pleasant evening." in msg_evening

    # Morning office arrival at 08:28
    active_office = _create_sample_active_journey(with_rail=True)
    active_office.to_name = "Tech Campus"
    active_office.current_status = JourneyStepStatus.ARRIVED
    active_office.expected_arrival_time = "08:28"
    morning_dt = datetime.datetime(2026, 9, 14, 8, 28)
    _, msg_morning, _ = format_progress_notification(
        active_office, current_dt=morning_dt
    )
    assert "Arrived at Tech Campus (08:28)." in msg_morning
    assert "Have a great day!" in msg_morning


def test_resolve_live_rail_platform_past_scheduled_fallback() -> None:
    """Test resolve_live_rail_platform falls back to next upcoming departure if scheduled time is past."""
    mock_live = MagicMock(spec=TrainLiveClient)
    mock_live.get_fastest_departures.return_value = [
        {
            "std": "17:14",
            "etd": "On time",
            "platform": "1",
            "delayReason": None,
            "cancelReason": None,
            "isCancelled": False,
        },
        {
            "std": "17:21",
            "etd": "17:25",
            "platform": "4",
            "delayReason": "a track fault",
            "cancelReason": None,
            "isCancelled": False,
        },
    ]

    # Stuart was looking for a stale 16:51 departure
    status = resolve_live_rail_platform(
        origin_id="naptan:CBG",
        dest_id="naptan:SVG",
        scheduled_time="16:51",
        live_client=mock_live,
    )
    assert status.platform == "1"
    assert status.std == "17:14"
    assert status.etd == "On time"


def test_active_journey_session_persistence_roundtrip(app: Flask) -> None:
    """Test saving, loading, and clearing active journey sessions via Setting storage."""
    with app.app_context():
        active = _create_sample_active_journey(journey_id=99, with_rail=True)
        active.current_status = JourneyStepStatus.ON_TRANSIT
        active.current_leg_index = 1
        active.platform = "4"
        active.live_status = "On time"

        save_active_journey_session(active)

        sessions = load_active_journey_sessions()
        assert 99 in sessions
        loaded = sessions[99]
        assert loaded.journey_id == 99
        assert loaded.journey_name == "Daily Office Commute"
        assert loaded.current_status == JourneyStepStatus.ON_TRANSIT
        assert loaded.current_leg_index == 1
        assert loaded.platform == "4"
        assert loaded.live_status == "On time"
        assert len(loaded.legs) == len(active.legs)

        clear_active_journey_session(99)
        sessions_after = load_active_journey_sessions()
        assert 99 not in sessions_after


def test_realign_active_journey_timings_bus_and_downstream_egress(app: Flask) -> None:
    """Test realigning past timetable bus departure to next trip and updating egress walk ETA."""
    with app.app_context():
        # Seed bus timetable with trips at 17:43 and 18:20
        Timetable.create(
            name="73",
            transport_type="bus",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
            saturday=True,
            sunday=True,
            content=TimetableContent(
                stops=[
                    TimetableStop(id="490000077E", name="King's Cross (Stop E)"),
                    TimetableStop(id="490000077C", name="Euston Station (Stop C)"),
                ],
                trips=[
                    TimetableTrip(id="t1", times=["17:43", "18:03"]),
                    TimetableTrip(id="t2", times=["18:20", "18:40"]),
                ],
            ),
        )

        legs = [
            ItineraryLeg(
                leg_index=0,
                mode="bus",
                origin=ItineraryEndpoint(id="490000077E", name="King's Cross (Stop E)"),
                destination=ItineraryEndpoint(
                    id="490000077C", name="Euston Station (Stop C)"
                ),
                dep_time="17:43",
                arr_time="18:03",
                duration_minutes=20,
                line="73",
            ),
            ItineraryLeg(
                leg_index=1,
                mode="walk",
                origin=ItineraryEndpoint(
                    id="490000077C", name="Euston Station (Stop C)"
                ),
                destination=ItineraryEndpoint(id="ha:home", name="Home"),
                dep_time="18:03",
                arr_time="18:07",
                duration_minutes=4,
            ),
        ]
        itin = ScheduledItinerary(
            departure_time="17:43",
            arrival_time="18:07",
            total_duration_minutes=24,
            transfers_count=0,
            robustness_score="high",
            legs=legs,
        )
        active = ActiveJourney(
            journey_id=2,
            journey_name="Commute Home",
            from_type="bus",
            from_id="490000077E",
            from_name="King's Cross (Stop E)",
            to_type="ha",
            to_id="ha:home",
            to_name="Home",
            itinerary=itin,
            legs=legs,
            current_leg_index=0,
            current_status=JourneyStepStatus.AT_INTERCHANGE,
            expected_arrival_time="18:07",
        )

        # Commuter arrives at interchange at 18:00 (past 17:43 bus departure)
        dt_1800 = datetime.datetime(2026, 9, 14, 18, 0)
        _realign_active_journey_timings(active, dt_1800)

        assert active.legs[0].dep_time == "18:20"
        assert active.legs[0].arr_time == "18:40"
        # Downstream egress walking leg propagated
        assert active.legs[1].dep_time == "18:40"
        assert active.legs[1].arr_time == "18:44"
        assert active.expected_arrival_time == "18:44"

        # Check formatted notification
        _, msg, _ = format_progress_notification(active, current_dt=dt_1800)
        assert "departing at 18:20" in msg
        assert "Platform" not in msg


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


def test_active_journey_serialization_roundtrip_with_debouncing_attributes() -> None:
    """Test ActiveJourney to_dict and from_dict preserve notification debouncing attributes."""
    now = datetime.datetime(2026, 9, 7, 8, 30, 0)
    active = _create_sample_active_journey(with_rail=False)
    active.last_notification_time = now
    active.last_notified_status = JourneyStepStatus.EN_ROUTE_TO_STOP
    active.last_notified_platform = "Platform 2"
    active.last_notified_delay_minutes = 3

    d = active.to_dict()
    assert d["last_notification_time"] == now.isoformat()
    assert d["last_notified_status"] == JourneyStepStatus.EN_ROUTE_TO_STOP.value
    assert d["last_notified_platform"] == "Platform 2"
    assert d["last_notified_delay_minutes"] == 3

    restored = ActiveJourney.from_dict(d)
    assert restored.last_notification_time == now
    assert restored.last_notified_status == JourneyStepStatus.EN_ROUTE_TO_STOP
    assert restored.last_notified_platform == "Platform 2"
    assert restored.last_notified_delay_minutes == 3


def test_update_journey_progress_debouncing_minor_telemetry_within_cooldown(
    app: Flask,
) -> None:
    """Test update_journey_progress suppresses minor ETA drift when within the 120s cooldown period."""
    with app.app_context():
        active = _create_sample_active_journey(with_rail=False)
        active.current_status = JourneyStepStatus.ON_TRANSIT
        active.current_leg_index = 1
        t0 = datetime.datetime(2026, 9, 7, 8, 10, 0)
        active.last_notification_time = t0
        active.last_notification_message = "On board Bus 73 towards Euston Station (Stop C). Expected arrival at 08:22. Next step: Walk 6m to Tech Campus."

        mock_ha = MagicMock(spec=HomeAssistantClient)
        state_transit = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5270, "longitude": -0.1280},
        }

        # 30 seconds later: minor telemetry drift changes message string slightly
        t1 = datetime.datetime(2026, 9, 7, 8, 10, 30)
        with patch(
            "app.services.dispatcher.tracker.format_progress_notification",
            return_value=(
                "Travel Alert: Commute to Work",
                "On board Bus 73 towards Euston Station (Stop C). Expected arrival at 08:23. Next step: Walk 6m to Tech Campus.",
                {"tag": f"journey_{active.journey_id}"},
            ),
        ):
            dispatched = update_journey_progress(active, state_transit, t1, mock_ha)
            assert dispatched is False
            mock_ha.send_mobile_notification.assert_not_called()
            # last_notification_time should remain at t0
            assert active.last_notification_time == t0


def test_update_journey_progress_debouncing_minor_telemetry_after_cooldown_elapses(
    app: Flask,
) -> None:
    """Test update_journey_progress allows minor telemetry update after 120s cooldown elapses."""
    with app.app_context():
        active = _create_sample_active_journey(with_rail=False)
        active.current_status = JourneyStepStatus.ON_TRANSIT
        active.current_leg_index = 1
        t0 = datetime.datetime(2026, 9, 7, 8, 10, 0)
        active.last_notification_time = t0
        active.last_notification_message = "On board Bus 73 towards Euston Station (Stop C). Expected arrival at 08:22. Next step: Walk 6m to Tech Campus."

        mock_ha = MagicMock(spec=HomeAssistantClient)
        state_transit = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5270, "longitude": -0.1280},
        }

        # 130 seconds later (>= 120s cooldown): ETA drifts
        t2 = datetime.datetime(2026, 9, 7, 8, 12, 10)
        drift_msg = "On board Bus 73 towards Euston Station (Stop C). Expected arrival at 08:24. Next step: Walk 6m to Tech Campus."
        with patch(
            "app.services.dispatcher.tracker.format_progress_notification",
            return_value=(
                "Travel Alert: Commute to Work",
                drift_msg,
                {"tag": f"journey_{active.journey_id}"},
            ),
        ):
            dispatched = update_journey_progress(active, state_transit, t2, mock_ha)
            assert dispatched is True
            mock_ha.send_mobile_notification.assert_called_once()
            assert active.last_notification_time == t2
            assert active.last_notification_message == drift_msg


def test_update_journey_progress_bypasses_cooldown_for_step_progression(
    app: Flask,
) -> None:
    """Test update_journey_progress immediately dispatches when journey status advances, bypassing cooldown."""
    with app.app_context():
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

        active = _create_sample_active_journey(with_rail=False)
        active.current_status = JourneyStepStatus.EN_ROUTE_TO_STOP
        active.current_leg_index = 0
        # Notification dispatched just 15 seconds ago
        t0 = datetime.datetime(2026, 9, 7, 8, 1, 45)
        active.last_notification_time = t0
        active.last_notification_message = "On your way to King's Cross (Stop E)."

        mock_ha = MagicMock(spec=HomeAssistantClient)
        # Stuart arrives at King's Cross Stop E at 8:02:00 (15 seconds later)
        t1 = datetime.datetime(2026, 9, 7, 8, 2, 0)
        state_at_stop = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5302, "longitude": -0.1225},
        }

        dispatched = update_journey_progress(active, state_at_stop, t1, mock_ha)
        assert dispatched is True
        assert active.current_status == JourneyStepStatus.AT_DEPARTURE_STOP
        mock_ha.send_mobile_notification.assert_called_once()
        assert active.last_notification_time == t1


def test_update_journey_progress_bypasses_cooldown_for_platform_announcement(
    app: Flask,
) -> None:
    """Test update_journey_progress immediately dispatches when a rail platform is announced, bypassing cooldown."""
    with app.app_context():
        active = _create_sample_active_journey(with_rail=True)
        active.current_status = JourneyStepStatus.AT_DEPARTURE_STOP
        active.current_leg_index = 1
        active.platform = None
        # Notification was sent 10 seconds ago
        t0 = datetime.datetime(2026, 9, 7, 8, 5, 0)
        active.last_notification_time = t0
        active.last_notification_message = "At London King's Cross. Train departs at 08:08 from Platform to be announced."

        mock_ha = MagicMock(spec=HomeAssistantClient)
        mock_live = MagicMock(spec=TrainLiveClient)

        t1 = datetime.datetime(2026, 9, 7, 8, 5, 10)
        state_at_station = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5310, "longitude": -0.1240},
        }

        with patch(
            "app.services.dispatcher.tracker.resolve_live_rail_platform",
            return_value=LiveRailStatus(platform="4", etd="On time"),
        ):
            dispatched = update_journey_progress(
                active, state_at_station, t1, mock_ha, live_client=mock_live
            )
            assert dispatched is True
            assert active.platform == "4"
            mock_ha.send_mobile_notification.assert_called_once()
            call_msg = mock_ha.send_mobile_notification.call_args[1]["message"]
            assert "Platform 4" in call_msg
            assert active.last_notification_time == t1


def test_update_journey_progress_bypasses_cooldown_for_major_delay_or_cancellation(
    app: Flask,
) -> None:
    """Test update_journey_progress immediately dispatches when a train experiences a major delay (>= 5 min) or cancellation."""
    with app.app_context():
        active = _create_sample_active_journey(with_rail=True)
        active.current_status = JourneyStepStatus.AT_DEPARTURE_STOP
        active.current_leg_index = 1
        active.platform = "4"
        active.delay_minutes = 0
        t0 = datetime.datetime(2026, 9, 7, 8, 5, 0)
        active.last_notification_time = t0
        active.last_notification_message = (
            "At London King's Cross. Train departs at 08:08 from Platform 4."
        )

        mock_ha = MagicMock(spec=HomeAssistantClient)
        mock_live = MagicMock(spec=TrainLiveClient)
        t1 = datetime.datetime(2026, 9, 7, 8, 5, 20)
        state_at_station = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5310, "longitude": -0.1240},
        }

        # Simulate 7-minute delay announced 20s later
        with patch(
            "app.services.dispatcher.tracker.resolve_live_rail_platform",
            return_value=LiveRailStatus(
                platform="4",
                etd="08:15",
                delay_minutes=7,
                delay_reason="Signal failure",
            ),
        ):
            dispatched = update_journey_progress(
                active, state_at_station, t1, mock_ha, live_client=mock_live
            )
            assert dispatched is True
            assert active.delay_minutes == 7
            mock_ha.send_mobile_notification.assert_called_once()
            call_msg = mock_ha.send_mobile_notification.call_args[1]["message"]
            assert "08:15" in call_msg
            assert active.last_notification_time == t1


def test_update_journey_progress_walking_egress_stable_eta_no_notification_churn(
    app: Flask,
) -> None:
    """Test update_journey_progress preserves stable walking ETA and avoids notification churn on each clock tick."""
    with app.app_context():
        Location.create(
            id="ha:office",
            name="Tech Campus",
            latitude=51.5200,
            longitude=-0.1340,
            ha=True,
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
        active.current_leg_index = 2
        active.current_status = JourneyStepStatus.EN_ROUTE_TO_DESTINATION
        active.expected_arrival_time = "08:28"
        t0 = datetime.datetime(2026, 9, 7, 8, 22, 0)
        active.last_notification_time = t0
        active.last_notification_message = (
            "Final leg: Walk to Tech Campus. Estimated arrival at 08:28."
        )

        mock_ha = MagicMock(spec=HomeAssistantClient)
        # Stuart is walking towards Tech Campus at 8:23:00 (1 minute later)
        t1 = datetime.datetime(2026, 9, 7, 8, 23, 0)
        state_walking = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5225, "longitude": -0.1332},
        }

        dispatched1 = update_journey_progress(active, state_walking, t1, mock_ha)
        # ETA must remain 08:28, not drift forward to 08:29
        assert active.expected_arrival_time == "08:28"
        assert dispatched1 is False
        mock_ha.send_mobile_notification.assert_not_called()

        # At 8:24:00 (2 minutes later)
        t2 = datetime.datetime(2026, 9, 7, 8, 24, 0)
        dispatched2 = update_journey_progress(active, state_walking, t2, mock_ha)
        assert active.expected_arrival_time == "08:28"
        assert dispatched2 is False
        mock_ha.send_mobile_notification.assert_not_called()


# --- Platform Resolution and Notification Enhancement Unit Tests ---


def test_resolve_live_rail_arrival_platform_scenarios() -> None:
    """Test resolve_live_rail_arrival_platform across varied live arrival responses and edge cases."""
    # 1. No live client returns None
    assert resolve_live_rail_arrival_platform("naptan:KGX", "naptan:CBG") is None

    # 2. Unknown destination CRS returns None
    mock_live = MagicMock(spec=TrainLiveClient)
    assert (
        resolve_live_rail_arrival_platform(
            "naptan:KGX", "invalid:unknown", live_client=mock_live
        )
        is None
    )

    # 3. Exact arrival time match
    mock_live.get_arrival_board.return_value = {
        "trainServices": [
            {"sta": "08:45", "eta": "On time", "platform": "1"},
            {"sta": "08:50", "eta": "08:52", "platform": "3"},
        ]
    }
    plat = resolve_live_rail_arrival_platform(
        "naptan:KGX", "naptan:CBG", scheduled_arr_time="08:50", live_client=mock_live
    )
    assert plat == "3"

    # 4. Approximate arrival time match (within 3 minutes)
    plat_approx = resolve_live_rail_arrival_platform(
        "naptan:KGX", "naptan:CBG", scheduled_arr_time="08:51", live_client=mock_live
    )
    assert plat_approx == "3"

    # 5. Fallback to first arrival when time does not match
    plat_fallback = resolve_live_rail_arrival_platform(
        "naptan:KGX", "naptan:CBG", scheduled_arr_time="09:30", live_client=mock_live
    )
    assert plat_fallback == "1"

    # 6. Service with missing or empty platform
    mock_live.get_arrival_board.return_value = {
        "trainServices": [
            {"sta": "08:45", "eta": "On time", "platform": None},
        ]
    }
    assert (
        resolve_live_rail_arrival_platform(
            "naptan:KGX", "naptan:CBG", live_client=mock_live
        )
        is None
    )

    # 7. Exception in get_arrival_board is swallowed gracefully
    mock_live.get_arrival_board.side_effect = RuntimeError("Network error")
    assert (
        resolve_live_rail_arrival_platform(
            "naptan:KGX", "naptan:CBG", live_client=mock_live
        )
        is None
    )


def test_format_platform_label_variations() -> None:
    """Test _format_platform_label handles rail and bus formatting correctly in British English."""
    # None or empty
    assert _format_platform_label(None, "rail") is None
    assert _format_platform_label("", "rail") is None
    assert _format_platform_label("   ", "rail") is None

    # Rail mode
    assert _format_platform_label("4", "rail") == "Platform 4"
    assert _format_platform_label("Platform 4", "rail") == "Platform 4"
    assert _format_platform_label("platform 2B", "rail") == "platform 2B"

    # Bus mode
    assert _format_platform_label("Stop G", "bus") == "Stop G"
    assert _format_platform_label("Stand A", "bus") == "Stand A"
    assert _format_platform_label("Bay 3", "bus") == "Bay 3"
    # Bare numbers should NOT become 'Platform' on buses
    assert _format_platform_label("3", "bus") is None


def test_format_upcoming_change_platforms_matrix() -> None:
    """Test _format_upcoming_change_platforms covering all platform announcement combinations."""
    # Rail to Rail
    assert (
        _format_upcoming_change_platforms("2", "4", "rail", "rail")
        == "arrive Platform 2, depart Platform 4"
    )
    assert (
        _format_upcoming_change_platforms("2", None, "rail", "rail")
        == "arrive Platform 2, depart Platform to be announced"
    )
    assert (
        _format_upcoming_change_platforms(None, "4", "rail", "rail")
        == "arrive Platform to be announced, depart Platform 4"
    )
    assert (
        _format_upcoming_change_platforms(None, None, "rail", "rail")
        == "platforms to be announced"
    )

    # Bus to Rail
    assert (
        _format_upcoming_change_platforms("Stop A", "3", "bus", "rail")
        == "arrive Stop A, depart Platform 3"
    )
    assert (
        _format_upcoming_change_platforms("Stop A", None, "bus", "rail")
        == "arrive Stop A, depart Platform to be announced"
    )
    assert (
        _format_upcoming_change_platforms(None, "3", "bus", "rail")
        == "arrive stand to be announced, depart Platform 3"
    )

    # Bus to Bus
    assert (
        _format_upcoming_change_platforms("Stop A", "Stand C", "bus", "bus")
        == "arrive Stop A, depart Stand C"
    )
    assert (
        _format_upcoming_change_platforms("Stop A", None, "bus", "bus")
        == "arrive Stop A, depart stand to be announced"
    )
    assert (
        _format_upcoming_change_platforms(None, "Stand C", "bus", "bus")
        == "arrive stand to be announced, depart Stand C"
    )
    assert (
        _format_upcoming_change_platforms(None, None, "bus", "bus")
        == "stands to be announced"
    )


def test_persistent_notification_state_lifecycle(app: Flask) -> None:
    """Test that notifications are persistent during journey progression and dismissible upon arrival."""
    with app.app_context():
        Setting.set_val("ingress_panel_slug", "travel_assistant")
        active = _create_sample_active_journey(with_rail=True)

        en_route_statuses = [
            JourneyStepStatus.PRE_DEPARTURE,
            JourneyStepStatus.EN_ROUTE_TO_STOP,
            JourneyStepStatus.AT_DEPARTURE_STOP,
            JourneyStepStatus.ON_TRANSIT,
            JourneyStepStatus.AT_INTERCHANGE,
            JourneyStepStatus.EN_ROUTE_TO_DESTINATION,
        ]

        expected_nav_url = f"/travel_assistant/journey?journey_id={active.journey_id}"
        expected_action = {
            "action": "URI",
            "title": "View Journey Plan",
            "uri": expected_nav_url,
        }

        for st in en_route_statuses:
            active.current_status = st
            _, _, data = format_progress_notification(active)
            assert data["persistent"] is True, f"Expected persistent=True for {st}"
            assert data["sticky"] is True, f"Expected sticky=True for {st}"
            assert data["url"] == expected_nav_url
            assert data["clickAction"] == expected_nav_url
            assert expected_action in data["actions"]

        # Final arrived status -> non-persistent / dismissible
        active.current_status = JourneyStepStatus.ARRIVED
        _, _, data_arrived = format_progress_notification(active)
        assert data_arrived["persistent"] is False
        assert data_arrived["sticky"] is False
        assert data_arrived["url"] == expected_nav_url
        assert data_arrived["clickAction"] == expected_nav_url
        assert expected_action in data_arrived["actions"]
