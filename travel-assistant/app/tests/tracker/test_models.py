"""Unit tests for ActiveJourney and tracker models."""

import datetime

from app.services.dispatcher.tracker.models import (
    ActiveJourney,
    JourneyStepStatus,
    LiveRailStatus,
)
from app.services.planner.models import (
    ItineraryEndpoint,
    ItineraryLeg,
    ScheduledItinerary,
)
from app.tests.tracker.conftest import create_sample_active_journey


def test_active_journey_post_init_defaults() -> None:
    """Test ActiveJourney model validator populates legs and expected_arrival_time."""
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


def test_active_journey_serialization_roundtrip_with_debouncing_attributes() -> None:
    """Test ActiveJourney to_dict and from_dict preserve notification debouncing attributes."""
    now = datetime.datetime(2026, 9, 7, 8, 30, 0)
    active = create_sample_active_journey(with_rail=False)
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


def test_live_rail_status_defaults() -> None:
    """Test LiveRailStatus default field initialisation."""
    status = LiveRailStatus()
    assert status.platform is None
    assert status.delay_minutes == 0
    assert status.etd is None
    assert status.is_cancelled is False
    assert status.cancel_reason is None
    assert status.delay_reason is None
