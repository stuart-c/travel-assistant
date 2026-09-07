"""Comprehensive unit and integration tests for Stuart's journey departure dispatcher."""

import datetime
from unittest.mock import MagicMock, patch
from flask import Flask

from app.datasources.homeassistant import HomeAssistantClient
from app.models.journey import Journey
from app.models.location import Location
from app.models.timetable import Timetable
from app.models.transit import Stop
from app.models.walking import Walking
from app.services.dispatcher.evaluator import (
    DepartureCandidate,
    apply_live_departure_adjustments,
    evaluate_journey_notification,
    extract_departure_candidates,
    format_departure_notification,
    is_journey_active_for_datetime,
)

from app.services.dispatcher.monitor import (
    DepartureMonitor,
    get_departure_monitor,
    start_departure_monitor,
)
from app.services.dispatcher.proximity import (
    haversine_distance,
    is_person_near_origin,
    resolve_endpoint_coordinates,
)


def _seed_commute_data() -> Journey:
    """Helper to seed a test commute journey with walking, stop, and bus timetable."""
    # 1. Origin HA Location: Home
    Location.create(
        id="ha:home",
        name="Home",
        latitude=51.5300,
        longitude=-0.1230,
        ha=True,
    )

    # 2. Destination HA Location: Tech Campus
    Location.create(
        id="ha:office",
        name="Tech Campus",
        latitude=51.5280,
        longitude=-0.1340,
        ha=True,
    )

    # 3. Origin Departure Bus Stop E
    Stop.create(
        atco_code="490000077E",
        naptan_code="490000077E",
        name="King's Cross Station (Stop E)",
        stop_type="bus",
        latitude=51.5302,
        longitude=-0.1225,
        locality="Camden",
        indicator="Stop E",
    )

    # 4. Destination Arrival Bus Stop C
    Stop.create(
        atco_code="490000077C",
        naptan_code="490000077C",
        name="Euston Station (Stop C)",
        stop_type="bus",
        latitude=51.5281,
        longitude=-0.1325,
        locality="Camden",
        indicator="Stop C",
    )

    # 5. Walking access leg: Home -> King's Cross Stop E (8 minutes)
    Walking.create(
        start_type="ha",
        start_id="ha:home",
        start_name="Home",
        finish_type="bus",
        finish_id="atco:490000077E",
        finish_name="King's Cross Station (Stop E)",
        time_needed_minutes=8,
        bidirectional=True,
    )

    # 6. Walking egress leg: Euston Stop C -> Tech Campus (6 minutes)
    Walking.create(
        start_type="bus",
        start_id="atco:490000077C",
        start_name="Euston Station (Stop C)",
        finish_type="ha",
        finish_id="ha:office",
        finish_name="Tech Campus",
        time_needed_minutes=6,
        bidirectional=True,
    )

    # 7. Bus 73 Timetable with 2 morning trips: 08:08 and 08:38
    tt = Timetable.create(
        name="Bus 73 Weekdays",
        transport_type="bus",
        monday=True,
        tuesday=True,
        wednesday=True,
        thursday=True,
        friday=True,
        saturday=False,
        sunday=False,
        bank_holiday=False,
    )
    tt.set_content(
        {
            "stops": [
                {
                    "id": "atco:490000077E",
                    "name": "King's Cross Station (Stop E)",
                    "type": "bus",
                },
                {
                    "id": "atco:490000077C",
                    "name": "Euston Station (Stop C)",
                    "type": "bus",
                },
            ],
            "trips": [
                {
                    "id": "trip-73-01",
                    "headsign": "Route 73",
                    "line": "73",
                    "operator": "Arriva London",
                    "times": ["08:08", "08:22"],
                },
                {
                    "id": "trip-73-02",
                    "headsign": "Route 73",
                    "line": "73",
                    "operator": "Arriva London",
                    "times": ["08:38", "08:52"],
                },
            ],
        }
    )
    tt.save()

    # 8. Journey: Home -> Tech Campus (07:30 - 09:00 Mon-Fri)
    journey = Journey.create(
        name="Morning Commute",
        from_type="ha",
        from_id="ha:home",
        from_name="Home",
        to_type="ha",
        to_id="ha:office",
        to_name="Tech Campus",
    )
    journey.set_time_settings(
        [
            {
                "days": ["mon", "tue", "wed", "thu", "fri"],
                "mode": "depart",
                "start_time": "07:30",
                "end_time": "09:00",
            }
        ]
    )
    journey.save()
    return journey


# --- Proximity Tests ---


def test_haversine_distance() -> None:
    """Test haversine distance calculation."""
    # Identical coordinates should be 0 distance
    assert haversine_distance(51.5, -0.1, 51.5, -0.1) == 0.0

    # Distance between King's Cross (51.5308, -0.1238) and Euston (51.5284, -0.1331)
    dist = haversine_distance(51.5308, -0.1238, 51.5284, -0.1331)
    assert 650.0 < dist < 750.0


def test_resolve_endpoint_coordinates(app: Flask) -> None:
    """Test resolving endpoint coordinates across HA locations, custom locations, and stops."""
    with app.app_context():
        _seed_commute_data()

        # HA Location
        lat, lon, name = resolve_endpoint_coordinates("ha", "ha:home")
        assert lat == 51.5300
        assert lon == -0.1230
        assert name == "Home"

        # Transit Stop
        lat, lon, name = resolve_endpoint_coordinates("bus", "atco:490000077E")
        assert lat == 51.5302
        assert lon == -0.1225
        assert name == "King's Cross Station (Stop E)"

        # Unknown endpoint
        lat, lon, name = resolve_endpoint_coordinates("unknown", "unknown:123")
        assert lat is None
        assert lon is None
        assert name is None

        # Empty endpoint
        lat, lon, name = resolve_endpoint_coordinates("", "")
        assert lat is None


def test_is_person_near_origin_zone(app: Flask) -> None:
    """Test zone state and in_zones proximity matching."""
    with app.app_context():
        _seed_commute_data()

        # State matching zone
        state_home = {
            "entity_id": "person.stuart",
            "state": "home",
            "attributes": {},
        }
        assert is_person_near_origin(state_home, "ha", "ha:home") is True
        assert is_person_near_origin(state_home, "ha", "ha:office") is False

        # in_zones matching zone
        state_in_zones = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"in_zones": ["zone.home"]},
        }
        assert is_person_near_origin(state_in_zones, "ha", "ha:home") is True

        # None / invalid state
        assert is_person_near_origin(None, "ha", "ha:home") is False
        assert is_person_near_origin({}, "ha", "ha:home") is False


def test_is_person_near_origin_gps(app: Flask) -> None:
    """Test GPS coordinate radius proximity matching."""
    with app.app_context():
        _seed_commute_data()

        # GPS point ~50m from Home (51.5300, -0.1230)
        state_near = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5304, "longitude": -0.1230},
        }
        assert (
            is_person_near_origin(
                state_near, "ha", "ha:home", max_distance_metres=200.0
            )
            is True
        )

        # GPS point ~1 km away from Home
        state_far = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5400, "longitude": -0.1230},
        }
        assert (
            is_person_near_origin(state_far, "ha", "ha:home", max_distance_metres=200.0)
            is False
        )

        # Invalid GPS values
        state_bad_coords = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": "invalid", "longitude": "invalid"},
        }
        assert is_person_near_origin(state_bad_coords, "ha", "ha:home") is False


# --- Evaluator Tests ---


def test_is_journey_active_for_datetime(app: Flask) -> None:
    """Test day and active time window matching for journeys."""
    with app.app_context():
        journey = _seed_commute_data()

        # Monday 07:45 (active day, within 07:30 - 09:00)
        mon_dt = datetime.datetime(2026, 9, 7, 7, 45)  # 2026-09-07 is Monday
        is_active, ts = is_journey_active_for_datetime(journey, mon_dt)
        assert is_active is True
        assert ts is not None

        # Monday 07:15 (20 mins before start time 07:30 - active due to 30m advance margin)
        early_mon = datetime.datetime(2026, 9, 7, 7, 15)
        is_active, _ = is_journey_active_for_datetime(journey, early_mon)
        assert is_active is True

        # Monday 06:30 (outside active window)
        too_early = datetime.datetime(2026, 9, 7, 6, 30)
        is_active, _ = is_journey_active_for_datetime(journey, too_early)
        assert is_active is False

        # Sunday 07:45 (inactive day)
        sun_dt = datetime.datetime(2026, 9, 13, 7, 45)  # 2026-09-13 is Sunday
        is_active, _ = is_journey_active_for_datetime(journey, sun_dt)
        assert is_active is False

        # Journey without time settings
        journey_no_time = Journey.create(
            name="Anytime Journey",
            from_type="ha",
            from_id="ha:home",
            from_name="Home",
            to_type="ha",
            to_id="ha:office",
            to_name="Tech Campus",
        )
        is_active, _ = is_journey_active_for_datetime(journey_no_time, mon_dt)
        assert is_active is False


def test_extract_departure_candidates_and_lead_time(app: Flask) -> None:
    """Test that candidate departure has leave_time and trigger exactly 15m before leave time."""
    with app.app_context():
        journey = _seed_commute_data()

        # Monday at 07:40
        now = datetime.datetime(2026, 9, 7, 7, 40)
        candidates = extract_departure_candidates(journey, now)

        assert len(candidates) >= 1
        cand = candidates[0]

        # Bus departs at 08:08 (488 mins past midnight)
        assert cand.transit_dep_time == "08:08"
        assert cand.transit_dep_minutes == 488

        # 8 minutes walk from Home to Stop E -> Leave time: 08:00 (480 mins past midnight)
        assert cand.walk_minutes == 8
        assert cand.leave_time == "08:00"
        assert cand.leave_minutes == 480

        # Notification trigger: 15 minutes before leave time -> 07:45 (465 mins past midnight)
        assert cand.notification_trigger_minutes == 465
        assert "73" in cand.line_name


def test_evaluate_journey_notification_trigger_window(app: Flask) -> None:
    """Test evaluate_journey_notification fires at 15m before leave time."""
    with app.app_context():
        journey = _seed_commute_data()

        # 07:45 is exactly 15m before 08:00 leave time
        now_45 = datetime.datetime(2026, 9, 7, 7, 45)
        cand = evaluate_journey_notification(journey, now_45, sent_keys=set())
        assert cand is not None
        assert cand.leave_time == "08:00"
        assert cand.transit_dep_time == "08:08"

        # 07:35 is 25m before leave time (too early -> None)
        now_35 = datetime.datetime(2026, 9, 7, 7, 35)
        cand_early = evaluate_journey_notification(journey, now_35, sent_keys=set())
        assert cand_early is None

        # Once candidate service key is recorded in sent_keys -> None (no duplicate)
        cand_duplicate = evaluate_journey_notification(
            journey, now_45, sent_keys={cand.service_key}
        )
        assert cand_duplicate is None


def test_subsequent_departure_if_stuart_does_not_leave(app: Flask) -> None:
    """Test progression to next transit departure if Stuart remains at origin past leave time."""
    with app.app_context():
        journey = _seed_commute_data()

        # Stuart did not leave at 08:00 for the 08:08 bus.
        # Next bus is at 08:38, with 8m walk -> leave time is 08:30 (510 mins).
        # Notification trigger for the next bus is 15m before 08:30 -> 08:15 (495 mins).

        # At 08:05, the 08:08 bus leave time (08:00) has passed.
        # The next candidate is the 08:38 bus, but it's not 08:15 yet.
        now_05 = datetime.datetime(2026, 9, 7, 8, 5)
        cand_05 = evaluate_journey_notification(journey, now_05, sent_keys=set())
        assert cand_05 is None

        # At 08:15 (15m before 08:30 leave time for the 08:38 bus), alert fires!
        now_15 = datetime.datetime(2026, 9, 7, 8, 15)
        cand_15 = evaluate_journey_notification(journey, now_15, sent_keys=set())
        assert cand_15 is not None
        assert cand_15.transit_dep_time == "08:38"
        assert cand_15.leave_time == "08:30"


def test_format_departure_notification() -> None:
    """Test notification text and metadata in British English."""
    cand = DepartureCandidate(
        journey_id=1,
        journey_name="Daily Office Commute",
        service_key="test_key_1",
        transit_mode="bus",
        line_name="73",
        operator_name="Arriva London",
        origin_stop_name="King's Cross Station (Stop E)",
        origin_stop_id="atco:490000077E",
        dest_stop_name="Euston Station (Stop C)",
        dest_stop_id="atco:490000077C",
        final_dest_name="Tech Campus",
        transit_dep_minutes=488,
        transit_dep_time="08:08",
        walk_minutes=8,
        leave_minutes=480,
        leave_time="08:00",
        arrival_time="08:28",
        notification_trigger_minutes=465,
    )

    title, message, data = format_departure_notification(cand)
    assert title == "Travel Alert: Daily Office Commute"
    assert "Leave by 08:00 (walk 8m)" in message
    assert "Bus 73" in message
    assert "departing at 08:08" in message
    assert "Estimated arrival at Tech Campus by 08:28." in message
    assert data["url"] == "/journey"
    assert data["clickAction"] == "/journey"
    assert data["tag"] == "journey_1"


# --- Monitor Tests ---


def test_departure_monitor_check_and_dispatch(app: Flask) -> None:
    """Test DepartureMonitor.check_and_dispatch end-to-end with mocked HA client."""
    with app.app_context():
        _seed_commute_data()

        monitor = DepartureMonitor(
            app=app,
            target_person="person.stuart",
            target_notify_service="mobile_app_stuart_mobile",
        )

        mock_ha_client = MagicMock(spec=HomeAssistantClient)
        mock_ha_client.token = "mock-token"
        # Stuart is at home
        mock_ha_client.get_entity_state.return_value = {
            "entity_id": "person.stuart",
            "state": "home",
            "attributes": {"latitude": 51.5300, "longitude": -0.1230},
        }
        mock_ha_client.send_mobile_notification.return_value = True

        # Run at 07:45 (15m before 08:00 leave time)
        now_45 = datetime.datetime(2026, 9, 7, 7, 45)
        count = monitor.check_and_dispatch(ha_client=mock_ha_client, now=now_45)
        assert count == 1
        mock_ha_client.send_mobile_notification.assert_called_once()
        call_kwargs = mock_ha_client.send_mobile_notification.call_args[1]
        assert call_kwargs["service_name"] == "mobile_app_stuart_mobile"
        assert "Leave by 08:00 (walk 8m)" in call_kwargs["message"]

        # Re-run immediately at 07:45 -> should be deduplicated (count 0)
        count_dup = monitor.check_and_dispatch(ha_client=mock_ha_client, now=now_45)
        assert count_dup == 0

        # Stuart far away -> count 0
        mock_ha_client.get_entity_state.return_value = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 52.0, "longitude": 0.0},
        }
        count_far = monitor.check_and_dispatch(ha_client=mock_ha_client, now=now_45)
        assert count_far == 0


def test_departure_monitor_lifecycle(app: Flask) -> None:
    """Test starting, stopping, and key cleanup on DepartureMonitor."""
    monitor = DepartureMonitor(app=app, check_interval_seconds=10.0)
    assert not monitor.is_running()

    monitor.start()
    assert monitor.is_running()

    # Calling start again when alive should be a no-op
    monitor.start()
    assert monitor.is_running()

    monitor.stop()
    assert not monitor.is_running()

    # Test key cleanup
    tomorrow = datetime.date(2026, 9, 8)
    monitor.sent_keys = {
        "j1_bus_73_08:08_2026-09-08",
        "j1_bus_73_08:08_2026-09-07",
    }
    monitor._cleanup_old_keys_if_needed(tomorrow)
    assert "j1_bus_73_08:08_2026-09-08" in monitor.sent_keys
    assert "j1_bus_73_08:08_2026-09-07" not in monitor.sent_keys


def test_start_departure_monitor_singleton(app: Flask) -> None:
    """Test start_departure_monitor and get_departure_monitor singleton functions."""
    with patch.object(DepartureMonitor, "start"):
        m1 = start_departure_monitor(app)
        assert m1 is not None
        m2 = get_departure_monitor()
        assert m1 is m2


def test_apply_live_departure_adjustments() -> None:
    """Test live departure adjustments for rail candidates."""
    base_cand = DepartureCandidate(
        journey_id=1,
        journey_name="Train Commute",
        service_key="test_rail_1",
        transit_mode="rail",
        line_name="Thameslink",
        operator_name="Thameslink",
        origin_stop_name="London King's Cross",
        origin_stop_id="naptan:KGX",
        dest_stop_name="Cambridge",
        dest_stop_id="naptan:CBG",
        final_dest_name="Cambridge",
        transit_dep_minutes=488,
        transit_dep_time="08:08",
        walk_minutes=10,
        leave_minutes=478,
        leave_time="07:58",
        arrival_time="08:55",
        notification_trigger_minutes=463,
    )

    # 1. No live client -> unchanged
    assert apply_live_departure_adjustments(base_cand, None) == base_cand

    # 2. Non-rail transit mode -> unchanged
    bus_cand = DepartureCandidate(
        journey_id=1,
        journey_name="Bus Commute",
        service_key="test_bus_1",
        transit_mode="bus",
        line_name="73",
        operator_name=None,
        origin_stop_name="Stop E",
        origin_stop_id="atco:490000077E",
        dest_stop_name="Stop C",
        dest_stop_id="atco:490000077C",
        final_dest_name="Tech Campus",
        transit_dep_minutes=488,
        transit_dep_time="08:08",
        walk_minutes=0,
        leave_minutes=488,
        leave_time="08:08",
        arrival_time="08:22",
        notification_trigger_minutes=473,
    )
    mock_live = MagicMock()
    assert apply_live_departure_adjustments(bus_cand, mock_live) == bus_cand

    # 3. Invalid CRS code -> unchanged
    invalid_crs_cand = DepartureCandidate(
        journey_id=1,
        journey_name="Train Commute",
        service_key="test_rail_2",
        transit_mode="rail",
        line_name="Thameslink",
        operator_name=None,
        origin_stop_name="Stop",
        origin_stop_id="naptan:INVALID_LONG_CODE",
        dest_stop_name="Dest",
        dest_stop_id="naptan:CBG",
        final_dest_name="Dest",
        transit_dep_minutes=488,
        transit_dep_time="08:08",
        walk_minutes=0,
        leave_minutes=488,
        leave_time="08:08",
        arrival_time="08:50",
        notification_trigger_minutes=473,
    )
    assert (
        apply_live_departure_adjustments(invalid_crs_cand, mock_live)
        == invalid_crs_cand
    )

    # 4. Live departure with delay
    mock_live.get_fastest_departures.return_value = [{"std": "08:08", "etd": "08:14"}]
    adjusted = apply_live_departure_adjustments(base_cand, mock_live)
    assert adjusted.is_live is True
    assert adjusted.delay_minutes == 6
    assert adjusted.transit_dep_time == "08:14"
    assert adjusted.transit_dep_minutes == 494
    assert adjusted.leave_minutes == 484
    assert adjusted.leave_time == "08:04"
    assert adjusted.notification_trigger_minutes == 469

    # 5. Live departure probe error -> handles gracefully without crashing
    mock_live.get_fastest_departures.side_effect = RuntimeError("Darwin API down")
    safe_cand = apply_live_departure_adjustments(base_cand, mock_live)
    assert safe_cand.is_live is True  # preserved from previous or unchanged


def test_monitor_error_handling_and_empty_token(app: Flask) -> None:
    """Test DepartureMonitor when HA token is missing or network call fails."""
    with app.app_context():
        _seed_commute_data()
        monitor = DepartureMonitor(app=app)

        # 1. Empty token
        mock_ha_no_token = MagicMock()
        mock_ha_no_token.token = ""
        assert monitor.check_and_dispatch(ha_client=mock_ha_no_token) == 0

        # 2. Entity state is None
        mock_ha_no_state = MagicMock()
        mock_ha_no_state.token = "valid"
        mock_ha_no_state.get_entity_state.return_value = None
        assert monitor.check_and_dispatch(ha_client=mock_ha_no_state) == 0

        # 3. Notification dispatch exception
        mock_ha_err = MagicMock()
        mock_ha_err.token = "valid"
        mock_ha_err.get_entity_state.return_value = {
            "entity_id": "person.stuart",
            "state": "home",
            "attributes": {"latitude": 51.5300, "longitude": -0.1230},
        }
        mock_ha_err.send_mobile_notification.side_effect = RuntimeError("Push failed")
        now_45 = datetime.datetime(2026, 9, 7, 7, 45)
        # Should catch error, log, and return 0 without crashing
        assert monitor.check_and_dispatch(ha_client=mock_ha_err, now=now_45) == 0


def test_proximity_unknown_origin_coordinates(app: Flask) -> None:
    """Test is_person_near_origin when origin location has no coordinates in database."""
    with app.app_context():
        state = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5300, "longitude": -0.1230},
        }
        # Origin not in database
        assert is_person_near_origin(state, "custom", "custom:non_existent") is False


def test_evaluator_all_day_window_and_planning_error(app: Flask) -> None:
    """Test journey with all-day time window and error during journey planning."""
    with app.app_context():
        journey = Journey.create(
            name="All Day Journey",
            from_type="ha",
            from_id="ha:home",
            from_name="Home",
            to_type="ha",
            to_id="ha:office",
            to_name="Tech Campus",
        )
        journey.set_time_settings([{"days": ["mon"], "start_time": "", "end_time": ""}])
        journey.save()

        now = datetime.datetime(2026, 9, 7, 12, 0)
        is_active, ts = is_journey_active_for_datetime(journey, now)
        assert is_active is True

        # When plan_journey raises JourneyPlanningError, extract_departure_candidates returns empty list
        with patch("app.services.dispatcher.evaluator.plan_journey") as mock_plan:
            from app.services.planner.exceptions import NoTripsInWindowError

            mock_plan.side_effect = NoTripsInWindowError("No trips in window")
            cands = extract_departure_candidates(journey, now)
            assert cands == []


def test_format_departure_notification_variations() -> None:
    """Test notification formatting with empty line name and live delay note."""
    cand = DepartureCandidate(
        journey_id=2,
        journey_name="Train Commute",
        service_key="test_key_2",
        transit_mode="rail",
        line_name="",
        operator_name=None,
        origin_stop_name="London King's Cross",
        origin_stop_id="naptan:KGX",
        dest_stop_name="Cambridge",
        dest_stop_id="naptan:CBG",
        final_dest_name="Cambridge",
        transit_dep_minutes=494,
        transit_dep_time="08:14",
        walk_minutes=0,
        leave_minutes=494,
        leave_time="08:14",
        arrival_time="08:58",
        notification_trigger_minutes=479,
        is_live=True,
        delay_minutes=6,
    )
    title, message, data = format_departure_notification(cand)
    assert title == "Travel Alert: Train Commute"
    assert "Leave by 08:14 (direct departure) for Rail (delayed by 6m)" in message
    assert "departing at 08:14" in message


def test_evaluator_journey_time_setting_types(app: Flask) -> None:
    """Test is_journey_active_for_datetime with typed JourneyTimeSetting and invalid objects."""
    with app.app_context():
        from app.models.journey import JourneyTimeSetting

        journey = Journey.create(
            name="Typed Time Setting Journey",
            from_type="ha",
            from_id="ha:home",
            from_name="Home",
            to_type="ha",
            to_id="ha:office",
            to_name="Tech Campus",
        )
        # Pass both a typed object and an invalid non-dict/non-setting entry
        journey.time_settings = [
            JourneyTimeSetting(
                days=["mon"], mode="depart", start_time="07:30", end_time="08:30"
            ),
            "invalid_string_setting",
        ]
        now = datetime.datetime(2026, 9, 7, 7, 45)
        is_active, ts = is_journey_active_for_datetime(journey, now)
        assert is_active is True
        assert ts is not None


def test_extract_departure_candidates_empty_legs() -> None:
    """Test extract_departure_candidates filtering of empty legs or missing transit times."""
    from app.services.planner.models import (
        ItineraryEndpoint,
        ItineraryLeg,
        ScheduledItinerary,
    )

    journey = Journey(
        id=99,
        name="Empty Legs Journey",
        from_type="ha",
        from_id="ha:home",
        from_name="Home",
        to_type="ha",
        to_id="ha:office",
        to_name="Tech Campus",
    )
    now = datetime.datetime(2026, 9, 7, 7, 45)

    with patch("app.services.dispatcher.evaluator.plan_journey") as mock_plan:
        mock_plan.return_value = [
            # 1. Empty legs itinerary
            ScheduledItinerary(
                departure_time="08:00",
                arrival_time="08:30",
                total_duration_minutes=30,
                transfers_count=0,
                robustness_score="High",
                legs=[],
            ),
            # 2. Walk-only with no second leg
            ScheduledItinerary(
                departure_time="08:00",
                arrival_time="08:10",
                total_duration_minutes=10,
                transfers_count=0,
                robustness_score="High",
                legs=[
                    ItineraryLeg(
                        leg_index=1,
                        mode="walk",
                        origin=ItineraryEndpoint(id="ha:home", name="Home"),
                        destination=ItineraryEndpoint(id="atco:123", name="Stop"),
                        dep_time="08:00",
                        arr_time="08:10",
                        duration_minutes=10,
                    )
                ],
            ),
            # 3. Direct transit leg with missing/empty dep_time
            ScheduledItinerary(
                departure_time="08:00",
                arrival_time="08:20",
                total_duration_minutes=20,
                transfers_count=0,
                robustness_score="High",
                legs=[
                    ItineraryLeg(
                        leg_index=1,
                        mode="bus",
                        origin=ItineraryEndpoint(id="atco:123", name="Stop"),
                        destination=ItineraryEndpoint(id="atco:456", name="Dest"),
                        dep_time="",
                        arr_time="08:20",
                        duration_minutes=20,
                    )
                ],
            ),
            # 4. Direct transit leg with unparseable dep_time
            ScheduledItinerary(
                departure_time="08:00",
                arrival_time="08:20",
                total_duration_minutes=20,
                transfers_count=0,
                robustness_score="High",
                legs=[
                    ItineraryLeg(
                        leg_index=1,
                        mode="bus",
                        origin=ItineraryEndpoint(id="atco:123", name="Stop"),
                        destination=ItineraryEndpoint(id="atco:456", name="Dest"),
                        dep_time="invalid_time",
                        arr_time="08:20",
                        duration_minutes=20,
                    )
                ],
            ),
        ]
        cands = extract_departure_candidates(journey, now)
        assert cands == []
