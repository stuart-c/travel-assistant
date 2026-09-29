"""Unit tests for transit service and next step description formatting."""

from app.services.dispatcher.tracker.service_description import (
    _format_departure_timing_with_delay,
    _format_platform_label,
    _format_transit_service_desc,
    _format_upcoming_change_platforms,
    format_next_step_for_departure,
)
from app.services.planner.models import (
    ItineraryEndpoint,
    ItineraryLeg,
)


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


def test_format_departure_timing_with_delay() -> None:
    """Test _format_departure_timing_with_delay with on-time, delay, and cancellation."""
    assert (
        _format_departure_timing_with_delay("08:08", "On time")
        == "08:08 (scheduled 08:08, expected 08:08 - on time)"
    )
    assert _format_departure_timing_with_delay("08:08", None) == "08:08 (scheduled)"
    assert (
        _format_departure_timing_with_delay("08:08", "08:13", "a signal fault")
        == "08:13 (scheduled 08:08, expected 08:13 due to a signal fault)"
    )
    assert (
        _format_departure_timing_with_delay("08:08", "Cancelled")
        == "08:08 (scheduled 08:08, cancelled)"
    )


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


def test_format_next_step_for_departure_with_live_rail_client() -> None:
    """Test format_next_step_for_departure resolves platform and etd from live rail client without AttributeError."""
    from unittest.mock import MagicMock
    from app.datasources.train_live import TrainLiveClient
    from app.services.dispatcher.tracker.service_description import (
        format_next_step_for_departure,
        format_next_step_for_on_transit,
    )

    legs = [
        ItineraryLeg(
            leg_index=0,
            mode="bus",
            line="Bus 73",
            operator="Arriva London",
            origin=ItineraryEndpoint(
                id="490000000A", name="Kings Cross Station (Stop E)"
            ),
            destination=ItineraryEndpoint(
                id="490000000B", name="Euston Station (Stop AZ)"
            ),
            dep_time="07:15",
            arr_time="07:25",
            duration_minutes=10,
        ),
        ItineraryLeg(
            leg_index=1,
            mode="walk",
            origin=ItineraryEndpoint(id="490000000B", name="Euston Station (Stop AZ)"),
            destination=ItineraryEndpoint(
                id="atco:9100EUSTON", name="London Euston Rail Station"
            ),
            dep_time="07:25",
            arr_time="07:30",
            duration_minutes=5,
        ),
        ItineraryLeg(
            leg_index=2,
            mode="rail",
            line="Avanti West Coast",
            operator="Avanti West Coast",
            origin=ItineraryEndpoint(
                id="atco:9100EUSTON", name="London Euston Rail Station"
            ),
            destination=ItineraryEndpoint(
                id="atco:9100MANCRPIC", name="Manchester Piccadilly"
            ),
            dep_time="07:40",
            arr_time="09:45",
            duration_minutes=125,
        ),
    ]

    mock_live = MagicMock(spec=TrainLiveClient)
    # 1. On-time with platform announced
    mock_live.get_fastest_departures.return_value = [
        {
            "std": "07:40",
            "etd": "On time",
            "platform": "5",
            "destination": [{"crs": "MAN"}],
        }
    ]

    next_step = format_next_step_for_departure(
        legs=legs,
        current_transit_leg=legs[0],
        only_transit=True,
        live_client=mock_live,
    )
    assert "London Euston Rail Station" in next_step
    assert "Platform 5" in next_step
    assert "07:40 (scheduled 07:40, expected 07:40 - on time)" in next_step

    # 2. Delayed with reason clause
    mock_live.get_fastest_departures.return_value = [
        {
            "std": "07:40",
            "etd": "07:52",
            "platform": "6",
            "delayReason": "a points failure",
            "destination": [{"crs": "MAN"}],
        }
    ]
    next_step_delayed = format_next_step_for_departure(
        legs=legs,
        current_transit_leg=legs[0],
        only_transit=True,
        live_client=mock_live,
    )
    assert "Platform 6" in next_step_delayed
    assert (
        "07:52 (scheduled 07:40, expected 07:52 due to a points failure)"
        in next_step_delayed
    )

    # 3. Transfer clause test with live rail status
    clause = format_next_step_for_on_transit(
        legs=legs,
        current_leg_index=0,
        current_leg=legs[0],
        live_client=mock_live,
    )
    assert "Platform 6" in clause
    assert "07:52" in clause
