"""Unit tests for journey tracking significance and arrival status determination."""

from app.services.dispatcher.tracker.models import JourneyStepStatus
from app.services.dispatcher.tracker.significance import (
    _determine_transit_arrival_status,
    is_significant_progress_update,
)
from app.tests.tracker.conftest import create_sample_active_journey


def test_determine_transit_arrival_status_coverage() -> None:
    """Test _determine_transit_arrival_status edge cases."""
    active = create_sample_active_journey()
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


def test_is_significant_progress_update() -> None:
    """Test is_significant_progress_update criteria for dispatching notifications."""
    active = create_sample_active_journey()
    active.current_status = JourneyStepStatus.PRE_DEPARTURE
    active.current_leg_index = 0
    active.platform = None
    active.delay_minutes = 0

    # No change
    assert (
        is_significant_progress_update(
            active,
            old_status=JourneyStepStatus.PRE_DEPARTURE,
            old_leg_idx=0,
            old_platform=None,
            old_delay=0,
        )
        is False
    )

    # Status progression
    active.current_status = JourneyStepStatus.EN_ROUTE_TO_STOP
    assert (
        is_significant_progress_update(
            active,
            old_status=JourneyStepStatus.PRE_DEPARTURE,
            old_leg_idx=0,
            old_platform=None,
            old_delay=0,
        )
        is True
    )

    # Platform announcement
    active.current_status = JourneyStepStatus.EN_ROUTE_TO_STOP
    active.platform = "Platform 3"
    assert (
        is_significant_progress_update(
            active,
            old_status=JourneyStepStatus.EN_ROUTE_TO_STOP,
            old_leg_idx=0,
            old_platform=None,
            old_delay=0,
        )
        is True
    )

    # Major delay change >= 5 minutes
    active.delay_minutes = 6
    assert (
        is_significant_progress_update(
            active,
            old_status=JourneyStepStatus.EN_ROUTE_TO_STOP,
            old_leg_idx=0,
            old_platform="Platform 3",
            old_delay=0,
        )
        is True
    )

    # Cancellation
    active.live_status = "Cancelled"
    assert (
        is_significant_progress_update(
            active,
            old_status=JourneyStepStatus.EN_ROUTE_TO_STOP,
            old_leg_idx=0,
            old_platform="Platform 3",
            old_delay=6,
            old_live_status="On time",
        )
        is True
    )
