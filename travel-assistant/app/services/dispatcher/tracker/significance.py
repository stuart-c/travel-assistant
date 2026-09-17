"""Debouncing logic and state significance evaluation for notifications."""

from typing import Optional

from app.services.dispatcher.tracker.models import (
    FOOT_MODES,
    ActiveJourney,
    JourneyStepStatus,
)


def _determine_transit_arrival_status(
    active: ActiveJourney,
) -> JourneyStepStatus:
    """Determine whether the next stage after reaching a stop is final walking, arrived, or interchange."""
    if active.current_leg_index >= len(active.legs):
        return JourneyStepStatus.EN_ROUTE_TO_DESTINATION
    next_leg = active.legs[active.current_leg_index]
    if active.current_leg_index == len(active.legs) - 1 and next_leg.mode in FOOT_MODES:
        return JourneyStepStatus.EN_ROUTE_TO_DESTINATION
    return JourneyStepStatus.AT_INTERCHANGE


def is_significant_progress_update(
    active: ActiveJourney,
    old_status: JourneyStepStatus,
    old_leg_idx: int,
    old_platform: Optional[str],
    old_delay: int,
    old_live_status: Optional[str] = None,
) -> bool:
    """Determine whether a journey progress state transition demands an immediate notification."""
    # 1. Step progression / leg transition
    if active.current_status != old_status or active.current_leg_index != old_leg_idx:
        return True

    # 2. Platform announcement or reassignment (e.g. None -> "Platform 4", or "Platform 3" -> "Platform 4")
    if active.platform and active.platform != old_platform:
        return True

    # 3. Major delay escalation (>= 5 minutes change)
    if abs(active.delay_minutes - old_delay) >= 5:
        return True

    # 4. Service cancellation or status change involving cancellation
    curr_status_str = (active.live_status or "").lower()
    old_status_str = (old_live_status or "").lower()
    if ("cancel" in curr_status_str) != ("cancel" in old_status_str):
        return True

    return False


__all__ = [
    "_determine_transit_arrival_status",
    "is_significant_progress_update",
]
