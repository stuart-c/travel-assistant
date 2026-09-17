"""Unit tests for journey tracking progress updates, lifecycle and error handling."""

import datetime
from unittest.mock import MagicMock
from flask import Flask

from app.datasources.homeassistant import HomeAssistantClient
from app.datasources.train_live import TrainLiveClient
from app.models.location import Location
from app.models.transit import Stop
from app.services.dispatcher.tracker.models import (
    JourneyStepStatus,
)
from app.services.dispatcher.tracker.progress import update_journey_progress
from app.tests.tracker.conftest import create_sample_active_journey


def test_update_journey_progress_invalid_state_or_timeout(app: Flask) -> None:
    """Test update_journey_progress handles invalid person state and journey expiration."""
    with app.app_context():
        active = create_sample_active_journey()
        mock_ha = MagicMock(spec=HomeAssistantClient)

        # Invalid / None state -> False
        assert (
            update_journey_progress(active, None, datetime.datetime.now(), mock_ha)
            is False
        )
        assert (
            update_journey_progress(active, {}, datetime.datetime.now(), mock_ha)
            is False
        )

        # Expired: arrival is 08:28 (508 mins), at 10:05 (605 mins > 508 + 90) -> EXPIRED
        late_dt = datetime.datetime(2026, 9, 7, 10, 5)
        stuart_state = {
            "entity_id": "person.stuart",
            "state": "home",
            "attributes": {"latitude": 51.5300, "longitude": -0.1230},
        }
        res = update_journey_progress(active, stuart_state, late_dt, mock_ha)
        assert res is False
        assert active.current_status == JourneyStepStatus.EXPIRED


def test_update_journey_progress_missed_departure_at_origin(app: Flask) -> None:
    """Test that active journey expires if Stuart does not leave origin by leave time + 2m."""
    with app.app_context():
        active = create_sample_active_journey()
        active.current_status = JourneyStepStatus.PRE_DEPARTURE
        # Leave time is 08:00 (dep 08:08 - walk 8m)
        # At 08:03, leave time + 2 has passed and Stuart is still at home
        now_03 = datetime.datetime(2026, 9, 7, 8, 3)
        stuart_state = {
            "entity_id": "person.stuart",
            "state": "home",
            "attributes": {"latitude": 51.5300, "longitude": -0.1230},
        }
        mock_ha = MagicMock(spec=HomeAssistantClient)
        res = update_journey_progress(active, stuart_state, now_03, mock_ha)
        assert res is False
        assert active.current_status == JourneyStepStatus.EXPIRED


def test_update_journey_progress_full_journey_progression(app: Flask) -> None:
    """Test end-to-end journey progression through all stages from origin to arrival."""
    with app.app_context():
        # Setup stops and locations
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
        Stop.create(
            atco_code="490000077C",
            naptan_code="490000077C",
            name="Euston Station (Stop C)",
            stop_type="bus",
            latitude=51.5240,
            longitude=-0.1325,
        )

        active = create_sample_active_journey(with_rail=False)
        active.current_status = JourneyStepStatus.PRE_DEPARTURE
        active.last_notification_message = (
            "Leave by 08:00 (walk 8m) for Bus 73 from King's Cross (Stop E) "
            "departing at 08:08 (scheduled). Estimated arrival at Tech Campus by 08:28."
        )

        mock_ha = MagicMock(spec=HomeAssistantClient)

        # 1. Stuart is at home at 07:50 (PRE_DEPARTURE) -> no duplicate notification
        now_50 = datetime.datetime(2026, 9, 7, 7, 50)
        state_home = {
            "entity_id": "person.stuart",
            "state": "home",
            "attributes": {"latitude": 51.5350, "longitude": -0.1230},
        }
        res1 = update_journey_progress(active, state_home, now_50, mock_ha)
        assert res1 is False
        assert active.current_status == JourneyStepStatus.PRE_DEPARTURE
        mock_ha.send_mobile_notification.assert_not_called()

        # 2. Stuart starts walking: midway between Home and Stop E (51.5325, -0.1228)
        now_55 = datetime.datetime(2026, 9, 7, 7, 55)
        state_walking = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5325, "longitude": -0.1228},
        }
        res2 = update_journey_progress(active, state_walking, now_55, mock_ha)
        assert res2 is True
        assert active.current_status == JourneyStepStatus.EN_ROUTE_TO_STOP
        mock_ha.send_mobile_notification.assert_called_once()
        call_msg = mock_ha.send_mobile_notification.call_args[1]["message"]
        assert "On your way to King's Cross (Stop E)." in call_msg

        # 3. Stuart arrives at King's Cross Stop E (51.5302, -0.1225)
        mock_ha.reset_mock()
        now_02 = datetime.datetime(2026, 9, 7, 8, 2)
        state_at_stop = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5302, "longitude": -0.1225},
        }
        res3 = update_journey_progress(active, state_at_stop, now_02, mock_ha)
        assert res3 is True
        assert active.current_leg_index == 1
        assert active.current_status == JourneyStepStatus.AT_DEPARTURE_STOP
        call_msg3 = mock_ha.send_mobile_notification.call_args[1]["message"]
        assert "At King's Cross (Stop E)." in call_msg3

        # 4. Bus departs at 08:08; at 08:12 Stuart is on transit midway to Euston (51.5270, -0.1280)
        mock_ha.reset_mock()
        now_12 = datetime.datetime(2026, 9, 7, 8, 12)
        state_transit = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5270, "longitude": -0.1280},
        }
        res4 = update_journey_progress(active, state_transit, now_12, mock_ha)
        assert res4 is True
        assert active.current_status == JourneyStepStatus.ON_TRANSIT
        call_msg4 = mock_ha.send_mobile_notification.call_args[1]["message"]
        assert "On board Bus 73 towards Euston Station (Stop C)." in call_msg4
        assert "Next step: Walk 6m to Tech Campus." in call_msg4

        # 5. Bus reaches Euston Stop C (51.5240, -0.1325) -> Stuart exits and begins final walk
        mock_ha.reset_mock()
        now_22 = datetime.datetime(2026, 9, 7, 8, 22)
        state_euston = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5240, "longitude": -0.1325},
        }
        res5 = update_journey_progress(active, state_euston, now_22, mock_ha)
        assert res5 is True
        assert active.current_leg_index == 2
        assert active.current_status == JourneyStepStatus.EN_ROUTE_TO_DESTINATION
        call_msg5 = mock_ha.send_mobile_notification.call_args[1]["message"]
        assert "Final leg: Walk to Tech Campus." in call_msg5

        # 6. Stuart arrives at Tech Campus (51.5200, -0.1340)
        mock_ha.reset_mock()
        now_28 = datetime.datetime(2026, 9, 7, 8, 28)
        state_arrived = {
            "entity_id": "person.stuart",
            "state": "office",
            "attributes": {"latitude": 51.5200, "longitude": -0.1340},
        }
        res6 = update_journey_progress(active, state_arrived, now_28, mock_ha)
        assert res6 is True
        assert active.current_status == JourneyStepStatus.ARRIVED
        call_msg6 = mock_ha.send_mobile_notification.call_args[1]["message"]
        assert "Journey complete: Arrived at Tech Campus (08:28)." in call_msg6

        # 7. Next tick when already arrived -> returns False (no duplicate notification)
        mock_ha.reset_mock()
        res7 = update_journey_progress(active, state_arrived, now_28, mock_ha)
        assert res7 is False
        mock_ha.send_mobile_notification.assert_not_called()


def test_update_journey_progress_live_platform_update(app: Flask) -> None:
    """Test live platform update triggered while Stuart is waiting at station."""
    with app.app_context():
        active = create_sample_active_journey(with_rail=True)
        active.current_status = JourneyStepStatus.AT_DEPARTURE_STOP
        active.current_leg_index = 1
        active.platform = None
        active.last_notification_message = "At London King's Cross. Rail Thameslink to Cambridge departs at 08:08 (scheduled) from Platform to be announced. Next step: Walk 6m to Tech Campus."

        mock_ha = MagicMock(spec=HomeAssistantClient)
        mock_live = MagicMock(spec=TrainLiveClient)
        mock_live.get_fastest_departures.return_value = [
            {"std": "08:08", "etd": "On time", "platform": "9"},
        ]

        now = datetime.datetime(2026, 9, 7, 8, 4)
        stuart_state = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5308, "longitude": -0.1238},
        }

        res = update_journey_progress(
            active,
            stuart_state,
            now,
            mock_ha,
            live_client=mock_live,
        )
        assert res is True
        assert active.platform == "9"
        call_msg = mock_ha.send_mobile_notification.call_args[1]["message"]
        assert "from Platform 9" in call_msg
        assert "on time" in call_msg


def test_update_journey_progress_stuart_wanders_far_away(app: Flask) -> None:
    """Test that if Stuart is far off the route during initial walk, active journey expires."""
    with app.app_context():
        Location.create(
            id="ha:home", name="Home", latitude=51.5300, longitude=-0.1230, ha=True
        )
        Stop.create(
            atco_code="490000077E",
            naptan_code="490000077E",
            name="King's Cross (Stop E)",
            stop_type="bus",
            latitude=51.5302,
            longitude=-0.1225,
        )

        active = create_sample_active_journey()
        active.current_status = JourneyStepStatus.PRE_DEPARTURE

        mock_ha = MagicMock(spec=HomeAssistantClient)
        # Stuart at latitude 52.0, longitude 0.0 (~50km away)
        stuart_state = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 52.0, "longitude": 0.0},
        }
        res = update_journey_progress(
            active,
            stuart_state,
            datetime.datetime(2026, 9, 7, 7, 55),
            mock_ha,
        )
        assert res is False
        assert active.current_status == JourneyStepStatus.EXPIRED


def test_update_journey_progress_notification_exception_handling(app: Flask) -> None:
    """Test update_journey_progress catches notification dispatch errors gracefully."""
    with app.app_context():
        active = create_sample_active_journey()
        active.current_status = JourneyStepStatus.EN_ROUTE_TO_DESTINATION
        active.current_leg_index = 2

        Location.create(
            id="ha:office",
            name="Tech Campus",
            latitude=51.5200,
            longitude=-0.1340,
            ha=True,
        )
        stuart_arrived = {
            "entity_id": "person.stuart",
            "state": "office",
            "attributes": {"latitude": 51.5200, "longitude": -0.1340},
        }

        mock_ha = MagicMock(spec=HomeAssistantClient)
        mock_ha.send_mobile_notification.side_effect = RuntimeError(
            "Push notification failed"
        )

        now = datetime.datetime(2026, 9, 7, 8, 28)
        res = update_journey_progress(active, stuart_arrived, now, mock_ha)
        assert res is False

        # Exception during regular progress notification (not arrival)
        active.current_status = JourneyStepStatus.PRE_DEPARTURE
        active.current_leg_index = 0
        state_walking = {
            "entity_id": "person.stuart",
            "state": "not_home",
            "attributes": {"latitude": 51.5325, "longitude": -0.1228},
        }
        res_prog_err = update_journey_progress(active, state_walking, now, mock_ha)
        assert res_prog_err is False
