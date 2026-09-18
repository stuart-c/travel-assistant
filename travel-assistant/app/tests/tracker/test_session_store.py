"""Unit tests for active journey session persistence."""

from flask import Flask

from app.models.setting import Setting
from app.services.dispatcher.tracker.models import JourneyStepStatus
from app.services.dispatcher.tracker.session_store import (
    clear_active_journey_session,
    load_active_journey_sessions,
    save_active_journey_session,
)
from app.tests.tracker.conftest import create_sample_active_journey


def test_active_journey_session_persistence_roundtrip(app: Flask) -> None:
    """Test saving, loading, and clearing active journey sessions via Setting storage."""
    with app.app_context():
        active = create_sample_active_journey(journey_id=99, with_rail=True)
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


def test_load_active_journey_sessions_empty_and_corrupt(app: Flask) -> None:
    """Test load_active_journey_sessions handles missing or corrupt Setting values gracefully."""
    with app.app_context():
        # Missing
        Setting.delete_key("active_journey_sessions")
        assert load_active_journey_sessions() == {}

        # Invalid JSON
        Setting.set_val("active_journey_sessions", "not-valid-json")
        assert load_active_journey_sessions() == {}

        # Non-dict JSON
        Setting.set_val("active_journey_sessions", "[1, 2, 3]")
        assert load_active_journey_sessions() == {}
