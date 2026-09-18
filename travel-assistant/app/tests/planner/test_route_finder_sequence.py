"""Unit tests for RouteLeg modal sequence validation and loop guards."""

from __future__ import annotations

from app.services.planner.models import RouteLeg
from app.services.planner.route_finder import (
    get_leg_mode,
    is_valid_leg_sequence,
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


def test_is_valid_leg_sequence_walking_rules() -> None:
    """Verify Rule 1: Walking cannot be followed by more walking."""
    # Empty list is invalid
    assert not is_valid_leg_sequence([])

    # Single walk leg is valid (direct walking journey)
    walk_single = [_make_test_leg(leg_type="walk", transport_mode="walk")]
    assert is_valid_leg_sequence(walk_single)

    # Consecutive walking legs: walk -> walk (invalid)
    consecutive_walk = [
        _make_test_leg(leg_type="walk", transport_mode="walk"),
        _make_test_leg(leg_type="walk", transport_mode="walk"),
    ]
    assert not is_valid_leg_sequence(consecutive_walk)

    # Walk -> Interchange (both are walking mode, invalid)
    walk_and_interchange = [
        _make_test_leg(leg_type="walk", transport_mode="walk"),
        _make_test_leg(leg_type="interchange", transport_mode="walk"),
    ]
    assert not is_valid_leg_sequence(walk_and_interchange)

    # Platform transfer -> Walk (invalid)
    transfer_and_walk = [
        _make_test_leg(leg_type="platform_transfer", transport_mode="walk"),
        _make_test_leg(leg_type="walk", transport_mode="walk"),
    ]
    assert not is_valid_leg_sequence(transfer_and_walk)

    # Walk -> Transit -> Walk (valid)
    walk_transit_walk = [
        _make_test_leg(leg_type="walk", transport_mode="walk"),
        _make_test_leg(leg_type="transit", transport_mode="bus"),
        _make_test_leg(leg_type="walk", transport_mode="walk"),
    ]
    assert is_valid_leg_sequence(walk_transit_walk)

    # Walk -> Bus -> Interchange -> Rail -> Walk (valid, interleaved walks)
    valid_multi_modal = [
        _make_test_leg(leg_type="walk", transport_mode="walk"),
        _make_test_leg(leg_type="transit", transport_mode="bus"),
        _make_test_leg(leg_type="interchange", transport_mode="walk"),
        _make_test_leg(leg_type="transit", transport_mode="rail"),
        _make_test_leg(leg_type="walk", transport_mode="walk"),
    ]
    assert is_valid_leg_sequence(valid_multi_modal)

    # Bus -> Walk -> Walk -> Rail (consecutive walks in middle, invalid)
    walks_in_middle = [
        _make_test_leg(leg_type="transit", transport_mode="bus"),
        _make_test_leg(leg_type="walk", transport_mode="walk"),
        _make_test_leg(leg_type="interchange", transport_mode="walk"),
        _make_test_leg(leg_type="transit", transport_mode="rail"),
    ]
    assert not is_valid_leg_sequence(walks_in_middle)


def test_is_valid_leg_sequence_same_mode_rules() -> None:
    """Verify Rule 2: Maximum of 4 of the same mode in a row (up to 3 transfers per stage)."""
    # 1 of mode (valid)
    assert is_valid_leg_sequence([_make_test_leg(transport_mode="bus")])

    # 2, 3, 4 of same mode in a row (valid, up to 3 intra-modal transfers)
    assert is_valid_leg_sequence(
        [
            _make_test_leg(transport_mode="bus"),
            _make_test_leg(transport_mode="bus"),
        ]
    )
    assert is_valid_leg_sequence(
        [
            _make_test_leg(transport_mode="bus"),
            _make_test_leg(transport_mode="bus"),
            _make_test_leg(transport_mode="bus"),
        ]
    )
    assert is_valid_leg_sequence(
        [
            _make_test_leg(transport_mode="bus"),
            _make_test_leg(transport_mode="bus"),
            _make_test_leg(transport_mode="bus"),
            _make_test_leg(transport_mode="bus"),
        ]
    )

    # 5 of same mode in a row (invalid, exceeds 3 transfers per stage)
    assert not is_valid_leg_sequence(
        [
            _make_test_leg(transport_mode="bus"),
            _make_test_leg(transport_mode="bus"),
            _make_test_leg(transport_mode="bus"),
            _make_test_leg(transport_mode="bus"),
            _make_test_leg(transport_mode="bus"),
        ]
    )

    # 3 rail legs in a row (valid)
    assert is_valid_leg_sequence(
        [
            _make_test_leg(transport_mode="rail"),
            _make_test_leg(transport_mode="rail"),
            _make_test_leg(transport_mode="rail"),
        ]
    )

    # 2 bus legs, followed by walk, followed by 2 bus legs (valid, reset by walk)
    interleaved_same_mode = [
        _make_test_leg(transport_mode="bus"),
        _make_test_leg(transport_mode="bus"),
        _make_test_leg(leg_type="walk", transport_mode="walk"),
        _make_test_leg(transport_mode="bus"),
        _make_test_leg(transport_mode="bus"),
    ]
    assert is_valid_leg_sequence(interleaved_same_mode)

    # 2 rail legs, followed by 2 bus legs (valid, different modes)
    rail_then_bus = [
        _make_test_leg(transport_mode="rail"),
        _make_test_leg(transport_mode="rail"),
        _make_test_leg(transport_mode="bus"),
        _make_test_leg(transport_mode="bus"),
    ]
    assert is_valid_leg_sequence(rail_then_bus)


def test_get_leg_mode_resolution() -> None:
    """Verify get_leg_mode correctly identifies walking and transit modes."""
    leg_walk = _make_test_leg(leg_type="walk", transport_mode="walk")
    assert get_leg_mode(leg_walk) == "walk"

    leg_interchange = _make_test_leg(leg_type="interchange", transport_mode="")
    assert get_leg_mode(leg_interchange) == "walk"

    leg_platform = _make_test_leg(leg_type="platform_transfer", transport_mode="")
    assert get_leg_mode(leg_platform) == "walk"

    leg_bus = _make_test_leg(leg_type="transit", transport_mode="bus")
    assert get_leg_mode(leg_bus) == "bus"

    leg_rail = _make_test_leg(leg_type="transit", transport_mode="rail")
    assert get_leg_mode(leg_rail) == "rail"


def test_is_valid_leg_sequence_loop_guards() -> None:
    """Test that is_valid_leg_sequence rejects same-line turnaround loops and spatial cycles."""
    # 1. Valid multi-modal sequence
    valid_legs = [
        RouteLeg(
            stage_index=1,
            step_index=1,
            leg_type="walk",
            from_type="ha",
            from_id="home",
            from_name="Home",
            to_type="bus",
            to_id="stop_1",
            to_name="Stop 1",
            duration_minutes=5,
            transport_mode="walk",
        ),
        RouteLeg(
            stage_index=2,
            step_index=2,
            leg_type="transit",
            from_type="bus",
            from_id="stop_1",
            from_name="Stop 1",
            to_type="bus",
            to_id="stop_2",
            to_name="Stop 2",
            duration_minutes=15,
            transport_mode="bus",
            line_name="Bus 73: Victoria to Stoke Newington",
        ),
        RouteLeg(
            stage_index=3,
            step_index=3,
            leg_type="transit",
            from_type="bus",
            from_id="stop_2",
            from_name="Stop 2",
            to_type="rail",
            to_id="stop_3",
            to_name="Stop 3",
            duration_minutes=30,
            transport_mode="rail",
            line_name="Thameslink",
        ),
    ]
    assert is_valid_leg_sequence(valid_legs) is True

    # 2. Reject same line turnaround (e.g. Bus 37X to Bus Station, then Bus 37X back)
    turnaround_legs = [
        RouteLeg(
            stage_index=1,
            step_index=1,
            leg_type="transit",
            from_type="bus",
            from_id="stop_1",
            from_name="The Crown",
            to_type="bus",
            to_id="stop_bs",
            to_name="Bus Station",
            duration_minutes=10,
            transport_mode="bus",
            line_name="Bus 37X: The Crown Inn to Bus Station",
        ),
        RouteLeg(
            stage_index=2,
            step_index=2,
            leg_type="transit",
            from_type="bus",
            from_id="stop_bs",
            from_name="Bus Station",
            to_type="bus",
            to_id="stop_1",
            to_name="The Crown",
            duration_minutes=10,
            transport_mode="bus",
            line_name="Bus 37X: Bus Station to The Crown Inn",
        ),
    ]
    assert is_valid_leg_sequence(turnaround_legs) is False

    # 3. Reject spatial return loop where a transit leg ends at a previously departed stop
    spatial_loop_legs = [
        RouteLeg(
            stage_index=1,
            step_index=1,
            leg_type="transit",
            from_type="bus",
            from_id="stop_a",
            from_name="Stop A",
            to_type="bus",
            to_id="stop_b",
            to_name="Stop B",
            duration_minutes=10,
            transport_mode="bus",
            line_name="Line 1",
        ),
        RouteLeg(
            stage_index=2,
            step_index=2,
            leg_type="transit",
            from_type="bus",
            from_id="stop_b",
            from_name="Stop B",
            to_type="bus",
            to_id="stop_a",
            to_name="Stop A",
            duration_minutes=10,
            transport_mode="bus",
            line_name="Line 2",
        ),
    ]
    assert is_valid_leg_sequence(spatial_loop_legs) is False
