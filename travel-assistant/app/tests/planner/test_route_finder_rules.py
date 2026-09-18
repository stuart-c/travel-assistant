"""Unit tests for route finding rules, timetable window checks, and Pareto pruning."""

from __future__ import annotations

from flask import Flask

from app.models.timetable import (
    Timetable,
    TimetableContent,
    TimetableStop,
    TimetableTrip,
)
from app.services.planner.models import RouteLeg, RouteTemplate
from app.services.planner.route_finder import (
    extract_route_base_name,
    find_routes,
    prune_route_templates,
    timetable_operates_in_window,
)


def _make_test_leg(
    leg_type: str = "transit",
    transport_mode: str = "bus",
    stage_index: int = 1,
    step_index: int = 1,
    from_id: str = "A",
    to_id: str = "B",
) -> RouteLeg:
    """Helper to construct lightweight RouteLeg for testing."""
    return RouteLeg(
        stage_index=stage_index,
        step_index=step_index,
        leg_type=leg_type,
        from_type="bus" if transport_mode == "bus" else "rail",
        from_id=from_id,
        from_name=f"Stop {from_id}",
        to_type="bus" if transport_mode == "bus" else "rail",
        to_id=to_id,
        to_name=f"Stop {to_id}",
        duration_minutes=5,
        transport_mode=transport_mode,
    )


def test_extract_route_base_name() -> None:
    """Test normalising diverse transit line strings into route base codes."""
    assert extract_route_base_name("Bus SB1: Woodcock Road to Bus Station") == "sb1"
    assert extract_route_base_name("Bus 37X: The Crown Inn to Bus Station") == "37x"
    assert extract_route_base_name("Route 73") == "73"
    assert extract_route_base_name("Bus 73") == "73"
    assert extract_route_base_name("Thameslink: London to Cambridge") == "thameslink"
    assert extract_route_base_name(None) == ""
    assert extract_route_base_name("") == ""


def test_timetable_operates_in_window(app: Flask) -> None:
    """Test checking if a timetable has trips operating in a specified time window."""
    with app.app_context():
        tt = Timetable.create(
            name="Morning Express",
            transport_type="rail",
            auto_added=False,
            stops_count=2,
            trips_count=1,
            content=TimetableContent(
                stops=[
                    TimetableStop(id="9100KNGX", name="London King's Cross"),
                    TimetableStop(id="9100CAMB", name="Cambridge"),
                ],
                trips=[
                    TimetableTrip(
                        id="trip_1",
                        times=[
                            {"dep": "08:15", "arr": "08:15"},
                            {"dep": "09:05", "arr": "09:05"},
                        ],
                    )
                ],
            ),
        )

        # 08:15 falls in 08:00-09:00 window (480 to 540 minutes)
        assert timetable_operates_in_window(tt, 480, 540) is True
        # 08:15 does not fall in 06:00-07:30 window (360 to 450 minutes)
        assert timetable_operates_in_window(tt, 360, 450) is False
        # Test empty timetable
        empty_tt = Timetable.create(
            name="Empty",
            transport_type="bus",
            auto_added=False,
            stops_count=0,
            trips_count=0,
            content_json="{}",
        )
        assert timetable_operates_in_window(empty_tt, 0, 1440) is False


def test_prune_route_templates_filters_invalid_sequences() -> None:
    """Verify prune_route_templates discards templates violating sequence rules."""
    valid_template = RouteTemplate(
        corridor_id="valid_1",
        name="Valid Corridor",
        summary_text="Walk → Bus → Walk",
        primary_mode="bus",
        total_duration_est_minutes=20,
        transfer_count=0,
        stages_count=3,
        legs=[
            _make_test_leg(leg_type="walk", transport_mode="walk"),
            _make_test_leg(leg_type="transit", transport_mode="bus"),
            _make_test_leg(leg_type="walk", transport_mode="walk"),
        ],
    )

    invalid_walk_template = RouteTemplate(
        corridor_id="invalid_walk",
        name="Invalid Walk Corridor",
        summary_text="Walk → Walk → Bus",
        primary_mode="bus",
        total_duration_est_minutes=25,
        transfer_count=0,
        stages_count=3,
        legs=[
            _make_test_leg(leg_type="walk", transport_mode="walk"),
            _make_test_leg(leg_type="walk", transport_mode="walk"),
            _make_test_leg(leg_type="transit", transport_mode="bus"),
        ],
    )

    invalid_five_buses_template = RouteTemplate(
        corridor_id="invalid_buses",
        name="Invalid 5 Buses",
        summary_text="Bus → Bus → Bus → Bus → Bus",
        primary_mode="bus",
        total_duration_est_minutes=50,
        transfer_count=4,
        stages_count=5,
        legs=[
            _make_test_leg(transport_mode="bus", from_id="1", to_id="2"),
            _make_test_leg(transport_mode="bus", from_id="2", to_id="3"),
            _make_test_leg(transport_mode="bus", from_id="3", to_id="4"),
            _make_test_leg(transport_mode="bus", from_id="4", to_id="5"),
            _make_test_leg(transport_mode="bus", from_id="5", to_id="6"),
        ],
    )

    pruned = prune_route_templates(
        [valid_template, invalid_walk_template, invalid_five_buses_template]
    )
    assert len(pruned) == 1
    assert pruned[0].corridor_id == "valid_1"


def test_pruning_pareto_dominance(seeded_planner: Flask) -> None:
    """Verify Pareto dominance filtering eliminates strictly slower routes with equal/more transfers."""
    with seeded_planner.app_context():
        # Create a slow parallel bus line between same stops
        tt_slow = Timetable.create(
            name="Slow Bus 73X",
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
        tt_slow.set_content(
            TimetableContent(
                stops=[
                    TimetableStop(
                        id="490000077E", name="King's Cross Station", type="bus"
                    ),
                    TimetableStop(id="490000077C", name="Euston Station", type="bus"),
                ],
                trips=[
                    TimetableTrip(
                        id="slow_01",
                        headsign="Euston Station Slow",
                        operator="Arriva London",
                        times=[{"dep": "07:30"}, {"arr": "08:30"}],  # 60 min vs 12 min
                    )
                ],
            )
        )
        tt_slow.save()

        routes = find_routes(
            from_type="bus",
            from_id="490000077E",
            to_type="bus",
            to_id="490000077C",
            days_of_week=["mon"],
        )
        # Should only retain the fastest non-dominated Bus 73
        assert len(routes) == 1
        assert routes[0].legs[0].line_name == "Bus 73"
