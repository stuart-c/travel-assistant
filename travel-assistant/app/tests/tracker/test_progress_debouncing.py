"""Unit tests for journey notification debouncing, cooldown bypass, and stable walking ETA."""

import datetime
from unittest.mock import MagicMock, patch
from flask import Flask

from app.datasources.homeassistant import HomeAssistantClient
from app.datasources.train_live import TrainLiveClient
from app.models.location import Location
from app.models.transit import Stop
from app.services.dispatcher.tracker.models import (
    JourneyStepStatus,
    LiveRailStatus,
)
from app.services.dispatcher.tracker.progress import update_journey_progress
from app.tests.tracker.conftest import create_sample_active_journey


def test_update_journey_progress_debouncing_minor_telemetry_within_cooldown(
    app: Flask,
) -> None:
    """Test update_journey_progress suppresses minor ETA drift when within the 120s cooldown period."""
    with app.app_context():
        active = create_sample_active_journey(with_rail=False)
        active.current_status = JourneyStepStatus.ON_TRANSIT
        active.current_leg_index = 1
        t0 = datetime.datetime(2026, 9, 7, 8, 10, 0)
        active.last_notification_time = t0
        active.last_notification_message = "On board Bus 73 towards Euston Station (Stop C). Expected arrival at 08:22. Next step: Walk 6m to Tech Campus."

        mock_ha = MagicMock(spec=HomeAssistantClient)
        state_transit = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5270, "longitude": -0.1280},
        }

        # 30 seconds later: minor telemetry drift changes message string slightly
        t1 = datetime.datetime(2026, 9, 7, 8, 10, 30)
        with patch(
            "app.services.dispatcher.tracker.format_progress_notification",
            return_value=(
                "Travel Alert: Commute to Work",
                "On board Bus 73 towards Euston Station (Stop C). Expected arrival at 08:23. Next step: Walk 6m to Tech Campus.",
                {"tag": f"journey_{active.journey_id}"},
            ),
        ):
            dispatched = update_journey_progress(active, state_transit, t1, mock_ha)
            assert dispatched is False
            mock_ha.send_mobile_notification.assert_not_called()
            # last_notification_time should remain at t0
            assert active.last_notification_time == t0


def test_update_journey_progress_debouncing_minor_telemetry_after_cooldown_elapses(
    app: Flask,
) -> None:
    """Test update_journey_progress allows minor telemetry update after 120s cooldown elapses."""
    with app.app_context():
        active = create_sample_active_journey(with_rail=False)
        active.current_status = JourneyStepStatus.ON_TRANSIT
        active.current_leg_index = 1
        t0 = datetime.datetime(2026, 9, 7, 8, 10, 0)
        active.last_notification_time = t0
        active.last_notification_message = "On board Bus 73 towards Euston Station (Stop C). Expected arrival at 08:22. Next step: Walk 6m to Tech Campus."

        mock_ha = MagicMock(spec=HomeAssistantClient)
        state_transit = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5270, "longitude": -0.1280},
        }

        # 130 seconds later (>= 120s cooldown): ETA drifts
        t2 = datetime.datetime(2026, 9, 7, 8, 12, 10)
        drift_msg = "On board Bus 73 towards Euston Station (Stop C). Expected arrival at 08:24. Next step: Walk 6m to Tech Campus."
        with patch(
            "app.services.dispatcher.tracker.format_progress_notification",
            return_value=(
                "Travel Alert: Commute to Work",
                drift_msg,
                {"tag": f"journey_{active.journey_id}"},
            ),
        ):
            dispatched = update_journey_progress(active, state_transit, t2, mock_ha)
            assert dispatched is True
            mock_ha.send_mobile_notification.assert_called_once()
            assert active.last_notification_time == t2
            assert active.last_notification_message == drift_msg


def test_update_journey_progress_bypasses_cooldown_for_step_progression(
    app: Flask,
) -> None:
    """Test update_journey_progress immediately dispatches when journey status advances, bypassing cooldown."""
    with app.app_context():
        Location.create(
            id="ha:home", name="Home", latitude=51.5350, longitude=-0.1230, ha=True
        )
        Location.create(
            id="ha:office",
            name="Tech Campus",
            latitude=51.5200,
            longitude=-0.1340,
            ha=True,
        )
        Stop.create(
            atco_code="490000077E",
            naptan_code="490000077E",
            name="King's Cross (Stop E)",
            stop_type="bus",
            latitude=51.5302,
            longitude=-0.1225,
        )

        active = create_sample_active_journey(with_rail=False)
        active.current_status = JourneyStepStatus.EN_ROUTE_TO_STOP
        active.current_leg_index = 0
        # Notification dispatched just 15 seconds ago
        t0 = datetime.datetime(2026, 9, 7, 8, 1, 45)
        active.last_notification_time = t0
        active.last_notification_message = "On your way to King's Cross (Stop E)."

        mock_ha = MagicMock(spec=HomeAssistantClient)
        # Stuart arrives at King's Cross Stop E at 8:02:00 (15 seconds later)
        t1 = datetime.datetime(2026, 9, 7, 8, 2, 0)
        state_at_stop = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5302, "longitude": -0.1225},
        }

        dispatched = update_journey_progress(active, state_at_stop, t1, mock_ha)
        assert dispatched is True
        assert active.current_status == JourneyStepStatus.AT_DEPARTURE_STOP
        mock_ha.send_mobile_notification.assert_called_once()
        assert active.last_notification_time == t1


def test_update_journey_progress_bypasses_cooldown_for_platform_announcement(
    app: Flask,
) -> None:
    """Test update_journey_progress immediately dispatches when a rail platform is announced, bypassing cooldown."""
    with app.app_context():
        active = create_sample_active_journey(with_rail=True)
        active.current_status = JourneyStepStatus.AT_DEPARTURE_STOP
        active.current_leg_index = 1
        active.platform = None
        # Notification was sent 10 seconds ago
        t0 = datetime.datetime(2026, 9, 7, 8, 5, 0)
        active.last_notification_time = t0
        active.last_notification_message = "At London King's Cross. Train departs at 08:08 from Platform to be announced."

        mock_ha = MagicMock(spec=HomeAssistantClient)
        mock_live = MagicMock(spec=TrainLiveClient)

        t1 = datetime.datetime(2026, 9, 7, 8, 5, 10)
        state_at_station = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5310, "longitude": -0.1240},
        }

        with patch(
            "app.services.dispatcher.tracker.resolve_live_rail_platform",
            return_value=LiveRailStatus(platform="4", etd="On time"),
        ):
            dispatched = update_journey_progress(
                active, state_at_station, t1, mock_ha, live_client=mock_live
            )
            assert dispatched is True
            assert active.platform == "4"
            mock_ha.send_mobile_notification.assert_called_once()
            call_msg = mock_ha.send_mobile_notification.call_args[1]["message"]
            assert "Platform 4" in call_msg
            assert active.last_notification_time == t1


def test_update_journey_progress_bypasses_cooldown_for_major_delay_or_cancellation(
    app: Flask,
) -> None:
    """Test update_journey_progress immediately dispatches when a train experiences a major delay (>= 5 min) or cancellation."""
    with app.app_context():
        active = create_sample_active_journey(with_rail=True)
        active.current_status = JourneyStepStatus.AT_DEPARTURE_STOP
        active.current_leg_index = 1
        active.platform = "4"
        active.delay_minutes = 0
        t0 = datetime.datetime(2026, 9, 7, 8, 5, 0)
        active.last_notification_time = t0
        active.last_notification_message = (
            "At London King's Cross. Train departs at 08:08 from Platform 4."
        )

        mock_ha = MagicMock(spec=HomeAssistantClient)
        mock_live = MagicMock(spec=TrainLiveClient)
        t1 = datetime.datetime(2026, 9, 7, 8, 5, 20)
        state_at_station = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5310, "longitude": -0.1240},
        }

        # Simulate 7-minute delay announced 20s later
        with patch(
            "app.services.dispatcher.tracker.resolve_live_rail_platform",
            return_value=LiveRailStatus(
                platform="4",
                etd="08:15",
                delay_minutes=7,
                delay_reason="Signal failure",
            ),
        ):
            dispatched = update_journey_progress(
                active, state_at_station, t1, mock_ha, live_client=mock_live
            )
            assert dispatched is True
            assert active.delay_minutes == 7
            mock_ha.send_mobile_notification.assert_called_once()
            call_msg = mock_ha.send_mobile_notification.call_args[1]["message"]
            assert "08:15" in call_msg
            assert active.last_notification_time == t1


def test_update_journey_progress_walking_egress_stable_eta_no_notification_churn(
    app: Flask,
) -> None:
    """Test update_journey_progress preserves stable walking ETA and avoids notification churn on each clock tick."""
    with app.app_context():
        Location.create(
            id="ha:office",
            name="Tech Campus",
            latitude=51.5200,
            longitude=-0.1340,
            ha=True,
        )
        Stop.create(
            atco_code="490000077C",
            naptan_code="490000077C",
            name="Euston Station (Stop C)",
            stop_type="bus",
            latitude=51.5240,
            longitude=-0.1325,
        )

        active = create_sample_active_journey(with_rail=False)
        active.current_leg_index = 2
        active.current_status = JourneyStepStatus.EN_ROUTE_TO_DESTINATION
        active.expected_arrival_time = "08:28"
        t0 = datetime.datetime(2026, 9, 7, 8, 22, 0)
        active.last_notification_time = t0
        active.last_notification_message = (
            "Final leg: Walk to Tech Campus. Estimated arrival at 08:28."
        )

        mock_ha = MagicMock(spec=HomeAssistantClient)
        # Stuart is walking towards Tech Campus at 8:23:00 (1 minute later)
        t1 = datetime.datetime(2026, 9, 7, 8, 23, 0)
        state_walking = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5225, "longitude": -0.1332},
        }

        dispatched1 = update_journey_progress(active, state_walking, t1, mock_ha)
        # ETA must remain 08:28, not drift forward to 08:29
        assert active.expected_arrival_time == "08:28"
        assert dispatched1 is False
        mock_ha.send_mobile_notification.assert_not_called()

        # At 8:24:00 (2 minutes later)
        t2 = datetime.datetime(2026, 9, 7, 8, 24, 0)
        dispatched2 = update_journey_progress(active, state_walking, t2, mock_ha)
        assert active.expected_arrival_time == "08:28"
        assert dispatched2 is False
        mock_ha.send_mobile_notification.assert_not_called()
