"""Unit tests for live tracking view model builder."""

from unittest.mock import MagicMock
from flask import Flask

from app.datasources.train_live import TrainLiveClient
from app.services.dispatcher.tracker.view_model import (
    STATUS_METADATA,
    clear_tracking_cache,
    get_journey_live_tracking_data,
)
from app.tests.tracker.conftest import create_sample_active_journey


def test_get_journey_live_tracking_data_with_rail_lookahead(app: Flask) -> None:
    """Test get_journey_live_tracking_data resolves platform for connecting rail leg during initial walk."""
    with app.app_context():
        active = create_sample_active_journey(journey_id=1, with_rail=True)
        # Configure rail leg with ATCO codes
        active.legs[1].origin.id = "atco:9100KNGX"
        active.legs[1].destination.id = "atco:9100PADTON"
        active.current_leg_index = 0  # Walking leg before train

        mock_live = MagicMock(spec=TrainLiveClient)
        mock_live.get_fastest_departures.return_value = [
            {"std": "08:08", "etd": "08:12", "platform": "9"},
        ]

        data = get_journey_live_tracking_data(
            journey_id=1,
            live_client=mock_live,
            active_journeys={1: active},
        )
        assert data["selected_journey"] is not None
        assert data["selected_journey"]["is_active"] is True
        assert data["selected_journey"]["platform"] == "9"
        assert data["selected_journey"]["live_status"] == "08:12"


def test_get_journey_live_tracking_data_no_active_journey(app: Flask) -> None:
    """Test get_journey_live_tracking_data handles missing or inactive journey gracefully."""
    with app.app_context():
        clear_tracking_cache()
        data = get_journey_live_tracking_data(
            journey_id=999,
            live_client=None,
            active_journeys={},
        )
        assert data["selected_journey"] is None
        assert data["active"] is False
        assert "pre_departure" in STATUS_METADATA
