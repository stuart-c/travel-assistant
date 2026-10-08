"""Unit tests for journey notification formatting across all lifecycle stages."""

import datetime
from flask import Flask

from app.models.setting import Setting
from app.services.dispatcher.tracker.models import JourneyStepStatus
from app.services.dispatcher.tracker.notification_formatter import (
    format_progress_notification,
)
from app.services.planner.models import (
    ItineraryEndpoint,
    ItineraryLeg,
    ScheduledItinerary,
)
from app.tests.tracker.conftest import create_sample_active_journey
from app.services.dispatcher.tracker.models import ActiveJourney


def test_format_progress_notification_stages() -> None:
    """Test notification message formatting across all journey step stages."""
    active = create_sample_active_journey(with_rail=True)

    # 1. PRE_DEPARTURE
    active.current_status = JourneyStepStatus.PRE_DEPARTURE
    title, msg, data = format_progress_notification(active)
    assert title == "Travel Alert: Daily Office Commute"
    assert "Depart by 08:00 (walk 8m)" in msg
    assert "Govia to Cambridge" in msg
    assert "08:08 ➔ Cambridge 08:22" in msg
    assert "🏁 Arrive Tech Campus by 08:28" in msg
    assert data["tag"] == "journey_1"
    assert data["url"] == "/journey?journey_id=1"
    assert data["clickAction"] == "/journey?journey_id=1"
    assert data["group"] == "travel_assistant_journeys"
    assert data["persistent"] is True
    assert data["sticky"] is True
    assert data["alert_once"] is False
    assert data["importance"] == "high"
    assert data["priority"] == "high"
    assert data["channel"] == "Travel Assistant"

    # PRE_DEPARTURE with announced platform
    active.platform = "4"
    active.live_status = "On time"
    _, msg_plat, _ = format_progress_notification(active)
    assert "(Platform 4)" in msg_plat
    assert "08:08" in msg_plat
    assert "(on time)" in msg_plat

    # 2. EN_ROUTE_TO_STOP
    active.current_status = JourneyStepStatus.EN_ROUTE_TO_STOP
    active.current_leg_index = 0
    _, msg_en_route, _ = format_progress_notification(active)
    assert "On your way to London King's Cross" in msg_en_route
    assert "Govia to Cambridge (Platform 4)" in msg_en_route
    assert "(on time)" in msg_en_route
    assert "🏁 Arrive Tech Campus by 08:28" in msg_en_route

    # 3. AT_DEPARTURE_STOP (Rail)
    active.current_status = JourneyStepStatus.AT_DEPARTURE_STOP
    active.current_leg_index = 1
    active.platform = "4"
    active.live_status = "On time"
    _, msg_at_stop, _ = format_progress_notification(active)
    assert "At London King's Cross" in msg_at_stop
    assert "(Platform 4)" in msg_at_stop
    assert "departing at 08:08 (on time)" in msg_at_stop
    assert "🏁 Arrive Tech Campus by 08:28" in msg_at_stop

    # 3b. AT_DEPARTURE_STOP (Rail, platform unannounced)
    active.platform = None
    active.live_status = None
    _, msg_unannounced, _ = format_progress_notification(active)
    assert "Platform to be announced" in msg_unannounced
    assert "🏁 Arrive Tech Campus by 08:28" in msg_unannounced

    # 3c. AT_DEPARTURE_STOP (Bus)
    active_bus = create_sample_active_journey(with_rail=False)
    active_bus.current_status = JourneyStepStatus.AT_DEPARTURE_STOP
    active_bus.current_leg_index = 1
    _, msg_bus_stop, _ = format_progress_notification(active_bus)
    assert "At King's Cross (Stop E)" in msg_bus_stop
    assert "Bus 73 to Euston Station (Stop C) • departing at 08:08" in msg_bus_stop
    assert "🏁 Arrive Tech Campus by 08:28" in msg_bus_stop

    # 4. ON_TRANSIT (with next leg walk)
    active.current_status = JourneyStepStatus.ON_TRANSIT
    active.current_leg_index = 1
    active.platform = "4"
    _, msg_transit, _ = format_progress_notification(active)
    assert "On board Govia to Cambridge (Platform 4)" in msg_transit
    assert "Alighting Cambridge 08:22" in msg_transit
    assert "🏁 Arrive Tech Campus by 08:28" in msg_transit

    # 4b. ON_TRANSIT (with next leg transit transfer)
    multi_active = create_sample_active_journey()
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
    assert "Bus 14 to North Office" in msg_transfer
    assert "🏁 Arrive Tech Campus by 08:28" in msg_transfer

    # 5. AT_INTERCHANGE
    active.current_status = JourneyStepStatus.AT_INTERCHANGE
    active.current_leg_index = 1
    active.platform = "2"
    _, msg_interchange, _ = format_progress_notification(active)
    assert "At London King's Cross" in msg_interchange
    assert "Platform 2" in msg_interchange
    assert "🏁 Arrive Tech Campus by 08:28" in msg_interchange

    # 6. EN_ROUTE_TO_DESTINATION
    active.current_status = JourneyStepStatus.EN_ROUTE_TO_DESTINATION
    active.current_leg_index = 2
    _, msg_egress, _ = format_progress_notification(active)
    assert "Final leg: Walk to Tech Campus" in msg_egress
    assert "ETA 08:28" in msg_egress

    # 7. ARRIVED
    active.current_status = JourneyStepStatus.ARRIVED
    _, msg_arrived, _ = format_progress_notification(active)
    assert "Journey complete: Arrived at Tech Campus (08:28)." in msg_arrived
    assert "Have a great day!" in msg_arrived


def test_format_progress_notification_empty_leg_fallbacks() -> None:
    """Test notification formatting fallbacks when current_leg is None."""
    active = create_sample_active_journey()
    active.current_leg_index = 99  # beyond legs length

    active.current_status = JourneyStepStatus.AT_DEPARTURE_STOP
    _, msg1, _ = format_progress_notification(active)
    assert "At departure stop" in msg1
    assert "🏁 Arrive Tech Campus by 08:28" in msg1

    active.current_status = JourneyStepStatus.ON_TRANSIT
    _, msg2, _ = format_progress_notification(active)
    assert "In transit towards Tech Campus" in msg2
    assert "🏁 Arrive Tech Campus by 08:28" in msg2

    active.current_status = JourneyStepStatus.AT_INTERCHANGE
    _, msg3, _ = format_progress_notification(active)
    assert "At Interchange" in msg3
    assert "🏁 Arrive Tech Campus by 08:28" in msg3

    # Fallback status
    active.current_status = JourneyStepStatus.EXPIRED
    _, msg4, _ = format_progress_notification(active)
    assert "Journey update: en route to Tech Campus" in msg4
    assert "🏁 Arrive Tech Campus by 08:28" in msg4


def test_format_notification_with_custom_ingress_panel_slug(app: Flask) -> None:
    """Test that notifications route clickAction to the configured Home Assistant ingress panel slug."""
    with app.app_context():
        Setting.set_val("ingress_panel_slug", "1a842e7e_travel_assistant_dev")
        active = create_sample_active_journey(with_rail=True)
        active.current_status = JourneyStepStatus.ON_TRANSIT
        _, _, data = format_progress_notification(active)
        assert data["url"] == "/1a842e7e_travel_assistant_dev/journey?journey_id=1"
        assert (
            data["clickAction"] == "/1a842e7e_travel_assistant_dev/journey?journey_id=1"
        )


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
    assert "At Stevenage Rail Station" in msg
    assert "Great Northern to Cambridge Rail Station" in msg
    assert "06:48" in msg
    assert "On board Interchange" not in msg


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
    assert "At Shuttle Bus" in msg
    assert "Shuttle Bus to Cambridge North Rail Station • departing at 17:40" in msg
    assert "Great Northern to London Kings Cross Rail Station" in msg
    assert "Cambridge North Rail Station 17:54 ➔ Stevenage Rail Station 18:39" in msg
    assert "🏁 Arrive Home by 18:45" in msg

    # 2. PRE_DEPARTURE
    active.current_status = JourneyStepStatus.PRE_DEPARTURE
    _, msg_pre, _ = format_progress_notification(active)
    assert "Depart by 17:36 (walk 4m)" in msg_pre
    assert "Shuttle Bus to Cambridge North Rail Station" in msg_pre
    assert "Great Northern to London Kings Cross Rail Station" in msg_pre
    assert "🏁 Arrive Home by 18:45" in msg_pre

    # 3. EN_ROUTE_TO_STOP
    active.current_status = JourneyStepStatus.EN_ROUTE_TO_STOP
    _, msg_en_route, _ = format_progress_notification(active)
    assert "On your way to Shuttle Bus" in msg_en_route
    assert "Shuttle Bus to Cambridge North Rail Station" in msg_en_route
    assert "Great Northern to London Kings Cross Rail Station" in msg_en_route
    assert "🏁 Arrive Home by 18:45" in msg_en_route


def test_format_progress_notification_bus_interchange_no_platform() -> None:
    """Test AT_INTERCHANGE for bus does not include 'Platform' or 'Platform to be announced'."""
    active = create_sample_active_journey(with_rail=False)
    active.current_status = JourneyStepStatus.AT_INTERCHANGE
    active.current_leg_index = 1
    active.platform = None
    _, msg, _ = format_progress_notification(active)
    assert "Platform" not in msg
    assert "At King's Cross (Stop E)" in msg
    assert "Bus 73 to Euston Station (Stop C) • departing at 08:08" in msg

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
    active = create_sample_active_journey(with_rail=True)
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
    active_office = create_sample_active_journey(with_rail=True)
    active_office.to_name = "Tech Campus"
    active_office.current_status = JourneyStepStatus.ARRIVED
    active_office.expected_arrival_time = "08:28"
    morning_dt = datetime.datetime(2026, 9, 14, 8, 28)
    _, msg_morning, _ = format_progress_notification(
        active_office, current_dt=morning_dt
    )
    assert "Arrived at Tech Campus (08:28)." in msg_morning
    assert "Have a great day!" in msg_morning


def test_persistent_notification_state_lifecycle(app: Flask) -> None:
    """Test that notifications are persistent during journey progression and dismissible upon arrival."""
    with app.app_context():
        Setting.set_val("ingress_panel_slug", "travel_assistant")
        active = create_sample_active_journey(with_rail=True)

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


def test_format_progress_notification_arrival_time_fallbacks() -> None:
    """Test resolution of expected arrival time when primary attributes are unset."""
    active = create_sample_active_journey(with_rail=True)
    active.expected_arrival_time = ""
    active.current_status = JourneyStepStatus.AT_DEPARTURE_STOP
    active.current_leg_index = 1

    # 1. Fallback to itinerary.arrival_time
    assert active.itinerary is not None
    active.itinerary.arrival_time = "08:35"
    _, msg1, _ = format_progress_notification(active)
    assert "🏁 Arrive Tech Campus by 08:35" in msg1

    # 2. Fallback to legs[-1].arr_time when itinerary is None
    active.itinerary = None
    active.legs[-1].arr_time = "08:40"
    _, msg2, _ = format_progress_notification(active)
    assert "🏁 Arrive Tech Campus by 08:40" in msg2

    # 3. Fallback to current_dt + remaining durations when legs arr_time is empty
    active.legs[-1].arr_time = ""
    active.legs[1].duration_minutes = 15
    active.legs[2].duration_minutes = 5
    now_dt = datetime.datetime(2026, 9, 29, 8, 10)
    # Remaining from index 1: 15 + 5 = 20 mins -> 08:30
    _, msg3, _ = format_progress_notification(active, current_dt=now_dt)
    assert "🏁 Arrive Tech Campus by 08:30" in msg3


def test_format_progress_notification_stale_arrival_time_recalculated() -> None:
    """Test that stored arrival time in the past is dynamically advanced using current time and remaining durations."""
    active = create_sample_active_journey(with_rail=True)
    # Stale arrival time fixed at 19:02
    active.expected_arrival_time = "19:02"
    active.current_status = JourneyStepStatus.ON_TRANSIT
    active.current_leg_index = 1
    active.legs[1].duration_minutes = 15
    active.legs[2].duration_minutes = 5

    # Commuter is en route at 19:15 (past the 19:02 arrival time)
    now_dt = datetime.datetime(2026, 9, 29, 19, 15)
    # Dynamic recalculation: 19:15 + (15 + 5 mins) = 19:35
    _, msg, _ = format_progress_notification(active, current_dt=now_dt)
    assert "19:02" not in msg
    assert "🏁 Arrive Tech Campus by 19:35" in msg
    assert active.expected_arrival_time == "19:35"


def test_platform_not_leaked_to_bus_notifications() -> None:
    """Verify that rail platforms are never leaked onto bus departure or en-route messages."""
    active = create_sample_active_journey(with_rail=False)
    # first_transit is bus 73
    active.platform = "4"  # Spurious downstream platform
    active.current_status = JourneyStepStatus.PRE_DEPARTURE
    active.current_leg_index = 0

    _, msg_pre_dep, _ = format_progress_notification(active)
    assert "Platform 4" not in msg_pre_dep
    assert "Bus 73" in msg_pre_dep

    active.current_status = JourneyStepStatus.EN_ROUTE_TO_STOP
    _, msg_en_route, _ = format_progress_notification(active)
    assert "Platform 4" not in msg_en_route
    assert "Bus 73" in msg_en_route
