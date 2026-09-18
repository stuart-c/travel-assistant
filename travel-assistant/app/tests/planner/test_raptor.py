"""Unit tests for Mode 2 RAPTOR concrete scheduled itinerary planning engine."""

from __future__ import annotations

from flask import Flask

from app.models.timetable import (
    Timetable,
    TimetableContent,
    TimetableStop,
    TimetableTrip,
)
from app.models.transit import Stop, StopInterchange
from app.services.planner.models import ScheduledItinerary
from app.services.planner.raptor import (
    _ParsedTrip,
    _is_invalid_transfer,
    _load_interchanges_for_stops,
    plan_journey,
)
from app.services.planner.transfers import parse_time_to_minutes


def test_plan_journey_depart_mode(seeded_planner: Flask) -> None:
    """Verify Mode 2 RAPTOR planning with depart_after constraint."""
    with seeded_planner.app_context():
        itineraries = plan_journey(
            from_type="ha",
            from_id="ha:home",
            to_type="ha",
            to_id="ha:work",
            timing_mode="depart",
            time_str="07:25",
            days_of_week=["mon"],
        )
        assert len(itineraries) >= 1
        it = itineraries[0]
        assert isinstance(it, ScheduledItinerary)
        assert it.arrival_time == "08:41"
        assert it.total_duration_minutes > 0
        assert it.transfers_count == 1
        assert "slack" in it.robustness_score.lower()

        # Verify legs sequence
        assert len(it.legs) >= 3
        assert it.legs[0].mode == "walk"
        assert it.legs[0].origin.id == "ha:home"
        assert it.legs[-1].destination.id == "ha:work"


def test_plan_journey_arrive_mode(seeded_planner: Flask) -> None:
    """Verify Mode 2 RAPTOR planning with arrive_by constraint."""
    with seeded_planner.app_context():
        itineraries = plan_journey(
            from_type="ha",
            from_id="ha:home",
            to_type="ha",
            to_id="ha:work",
            timing_mode="arrive",
            time_str="09:15",
            days_of_week=["mon"],
        )
        assert len(itineraries) >= 1
        it = itineraries[0]
        assert parse_time_to_minutes(it.arrival_time) <= parse_time_to_minutes("09:15")
        # Latest valid departure
        assert parse_time_to_minutes(it.departure_time) >= parse_time_to_minutes(
            "07:00"
        )


def test_plan_journey_window_mode(seeded_planner: Flask) -> None:
    """Verify Mode 2 RAPTOR planning over a multi-hour time window."""
    with seeded_planner.app_context():
        itineraries = plan_journey(
            from_type="ha",
            from_id="ha:home",
            to_type="ha",
            to_id="ha:work",
            timing_mode="window",
            time_str="07:00",
            time_window_end="08:30",
            days_of_week=["mon"],
        )
        assert (
            len(itineraries) >= 2
        )  # Should capture both 07:30 and 08:00 bus departures
        for it in itineraries:
            dep_m = parse_time_to_minutes(it.departure_time)
            assert dep_m >= parse_time_to_minutes("07:00")
            assert dep_m <= parse_time_to_minutes("08:30")


def test_direct_walk_planning_modes(seeded_planner: Flask) -> None:
    """Verify direct walking in arrive and window timing modes."""
    with seeded_planner.app_context():
        # Arrive mode for direct walk
        it_arr = plan_journey(
            from_type="ha",
            from_id="ha:home",
            to_type="custom",
            to_id="custom:parents_house",
            timing_mode="arrive",
            time_str="10:00",
        )
        assert len(it_arr) == 1
        assert it_arr[0].arrival_time == "10:00"
        assert it_arr[0].departure_time == "09:48"

        # Window mode default end time
        it_win = plan_journey(
            from_type="ha",
            from_id="ha:home",
            to_type="custom",
            to_id="custom:parents_house",
            timing_mode="window",
            time_str="10:00",
            time_window_end=None,  # Tests default +120 min window
        )
        assert len(it_win) == 1


def test_timetable_with_string_times(seeded_planner: Flask) -> None:
    """Verify handling of timetables with plain string times and empty stop sequences."""
    with seeded_planner.app_context():
        tt_str = Timetable.create(
            name="Express Shuttle",
            transport_type="bus",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
            saturday=True,
            sunday=True,
            bank_holiday=True,
        )
        tt_str.set_content(
            TimetableContent(
                stops=[
                    TimetableStop(
                        id="490000077E", name="King's Cross Station", type="bus"
                    ),
                    TimetableStop(id="490000077C", name="Euston Station", type="bus"),
                ],
                trips=[
                    TimetableTrip(
                        id="shuttle_01",
                        headsign="Express",
                        operator="ShuttleCorp",
                        times=["08:30", "08:40"],  # Plain string times
                    )
                ],
            )
        )
        tt_str.save()

        it = plan_journey(
            from_type="bus",
            from_id="490000077E",
            to_type="bus",
            to_id="490000077C",
            timing_mode="depart",
            time_str="08:25",
            days_of_week=["mon"],
        )
        assert len(it) >= 1
        assert any(leg.line == "Express Shuttle" for plan in it for leg in plan.legs)


def test_raptor_midnight_rollover(app: Flask) -> None:
    """Test that trips traversing midnight (e.g. 23:50 -> 00:35) plan cleanly without looping."""
    with app.app_context():
        Stop.create(
            atco_code="9100KGX_NIGHT",
            naptan_code="KGX_NIGHT",
            name="London King's Cross Night",
            stop_type="rail",
        )
        Stop.create(
            atco_code="9100CBG_NIGHT",
            naptan_code="CBG_NIGHT",
            name="Cambridge Night",
            stop_type="rail",
        )

        tt = Timetable.create(
            name="Late Night Sleeper",
            transport_type="rail",
            monday=True,
            tuesday=True,
        )
        tt.set_content(
            TimetableContent(
                stops=[
                    TimetableStop(
                        id="9100KGX_NIGHT",
                        name="London King's Cross Night",
                        type="rail",
                    ),
                    TimetableStop(
                        id="9100CBG_NIGHT",
                        name="Cambridge Night",
                        type="rail",
                    ),
                ],
                trips=[
                    TimetableTrip(
                        id="sleeper_1",
                        times=[{"dep": "23:50"}, {"arr": "00:35"}],
                    )
                ],
            )
        )
        tt.save()

        plans = plan_journey(
            from_type="rail",
            from_id="9100KGX_NIGHT",
            to_type="rail",
            to_id="9100CBG_NIGHT",
            timing_mode="depart",
            time_str="23:45",
            days_of_week=["mon"],
        )

        assert len(plans) == 1
        itin = plans[0]
        assert itin.departure_time == "23:50"
        assert itin.arrival_time == "00:35"
        assert itin.total_duration_minutes == 45


def test_load_interchanges_for_stops_filtering_and_chunking(app: Flask) -> None:
    """Test that _load_interchanges_for_stops only retrieves relevant stops and handles chunking."""
    with app.app_context():
        # Empty set returns empty dict without DB queries
        assert _load_interchanges_for_stops(set()) == {}

        # Seed test interchanges
        StopInterchange.create(
            from_stop_atco="2100_STOP_A",
            from_stop_name="Stop A",
            to_stop_atco="2100_STOP_B",
            to_stop_name="Stop B",
            distance_metres=100,
            estimated_walk_minutes=2,
        )
        StopInterchange.create(
            from_stop_atco="2100_STOP_C",
            from_stop_name="Stop C",
            to_stop_atco="2100_STOP_D",
            to_stop_name="Stop D",
            distance_metres=150,
            estimated_walk_minutes=3,
        )
        StopInterchange.create(
            from_stop_atco="2100_UNRELATED",
            from_stop_name="Unrelated",
            to_stop_atco="2100_OTHER",
            to_stop_name="Other",
            distance_metres=200,
            estimated_walk_minutes=4,
        )

        # Only query for STOP_A and STOP_C
        res = _load_interchanges_for_stops({"2100_STOP_A", "2100_STOP_C"})
        assert "2100_STOP_A" in res
        assert res["2100_STOP_A"] == [("2100_STOP_B", 2)]
        assert "2100_STOP_C" in res
        assert res["2100_STOP_C"] == [("2100_STOP_D", 3)]
        assert "2100_UNRELATED" not in res

        # Test chunking with >500 dummy stops
        large_stops = {f"dummy_stop_{i}" for i in range(550)}
        large_stops.add("2100_STOP_A")
        chunked_res = _load_interchanges_for_stops(large_stops)
        assert "2100_STOP_A" in chunked_res
        assert chunked_res["2100_STOP_A"] == [("2100_STOP_B", 2)]


def test_raptor_same_line_transfer_suppression() -> None:
    """Test that _is_invalid_transfer rejects boarding trips on the same base line in reverse."""
    # Trip on Bus 37X heading outbound
    trip_37x = _ParsedTrip(
        trip_id="tr_2",
        timetable_id=102,
        line_name="Bus 37X: Bus Station to The Crown Inn",
        transport_mode="bus",
        operator=None,
        headsign=None,
        stops=["stop_bs", "stop_crown"],
        arr_times=[500, 520],
        dep_times=[500, 520],
    )

    leg_pointer = {
        0: {},
        1: {
            "stop_bs": {
                "mode": "bus",
                "line": "Bus 37X: The Crown Inn to Bus Station",
                "from_stop": "stop_crown",
                "to_stop": "stop_bs",
            }
        },
    }

    # At round 2, boarding 37X after arriving on 37X should be rejected
    assert _is_invalid_transfer(trip_37x, "stop_bs", 2, leg_pointer) is True

    # At round 1 (first boarding), should not be rejected
    assert _is_invalid_transfer(trip_37x, "stop_bs", 1, leg_pointer) is False
