"""Unit tests for live rail platform resolution."""

from unittest.mock import MagicMock

from app.datasources.train_live import TrainLiveClient
from app.services.dispatcher.tracker.models import LiveRailStatus
from app.services.dispatcher.tracker.platform_service import (
    _clean_delay_reason,
    resolve_live_rail_arrival_platform,
    resolve_live_rail_platform,
)


def test_clean_delay_reason() -> None:
    """Test _clean_delay_reason strips boilerplate prefix."""
    raw = "This service has been delayed by a signalling fault"
    assert _clean_delay_reason(raw) == "a signalling fault"
    assert _clean_delay_reason("Minor delays") == "Minor delays"
    assert _clean_delay_reason(None) is None


def test_resolve_live_rail_platform_no_client() -> None:
    """Test resolve_live_rail_platform returns default LiveRailStatus when live_client is None."""
    res = resolve_live_rail_platform("naptan:KGX", "naptan:CBG", "08:08", None)
    assert isinstance(res, LiveRailStatus)
    assert res.platform is None
    assert res.etd is None
    assert res.delay_minutes == 0
    assert res.delay_reason is None


def test_resolve_live_rail_platform_invalid_crs() -> None:
    """Test resolve_live_rail_platform with invalid or non-rail CRS codes."""
    mock_live = MagicMock(spec=TrainLiveClient)
    # Long ATCO code
    res = resolve_live_rail_platform(
        "atco:490000077E", "atco:490000077C", "08:08", mock_live
    )
    assert res.platform is None
    assert res.etd is None
    mock_live.get_fastest_departures.assert_not_called()

    # Numeric code
    res = resolve_live_rail_platform("1234", "CBG", "08:08", mock_live)
    assert res.platform is None
    assert res.etd is None
    mock_live.get_fastest_departures.assert_not_called()


def test_resolve_live_rail_platform_matching_departure() -> None:
    """Test resolve_live_rail_platform when matching departure is found."""
    mock_live = MagicMock(spec=TrainLiveClient)
    mock_live.get_fastest_departures.return_value = [
        {"std": "08:05", "etd": "On time", "platform": "1"},
        {
            "std": "08:08",
            "etd": "Delayed",
            "platform": "4B",
            "delayReason": "This service has been delayed by a fault with the signalling system",
        },
    ]

    res = resolve_live_rail_platform("naptan:KGX", "naptan:CBG", "08:08", mock_live)
    assert res.platform == "4B"
    assert res.etd == "Delayed"
    assert res.delay_reason == "a fault with the signalling system"
    mock_live.get_fastest_departures.assert_called_once_with("KGX", ["CBG"])


def test_resolve_live_rail_platform_first_departure_when_time_empty() -> None:
    """Test resolve_live_rail_platform returns first departure when scheduled_time is empty."""
    mock_live = MagicMock(spec=TrainLiveClient)
    mock_live.get_fastest_departures.return_value = [
        {"std": "08:05", "etd": "On time", "platform": "2"},
    ]
    res = resolve_live_rail_platform("KGX", "CBG", "", mock_live)
    assert res.platform == "2"
    assert res.etd == "On time"


def test_resolve_live_rail_platform_not_found_or_exception() -> None:
    """Test resolve_live_rail_platform handles empty list and exceptions gracefully."""
    mock_live = MagicMock(spec=TrainLiveClient)
    mock_live.get_fastest_departures.return_value = []
    res = resolve_live_rail_platform("KGX", "CBG", "08:08", mock_live)
    assert res.platform is None
    assert res.etd is None

    mock_live.get_fastest_departures.side_effect = RuntimeError(
        "Darwin connection reset"
    )
    res = resolve_live_rail_platform("KGX", "CBG", "08:08", mock_live)
    assert res.platform is None
    assert res.etd is None


def test_resolve_live_rail_platform_with_atco_and_tiploc() -> None:
    """Test resolve_live_rail_platform successfully maps ATCO and TIPLOC codes to CRS."""
    mock_live = MagicMock(spec=TrainLiveClient)
    mock_live.get_fastest_departures.return_value = [
        {"std": "08:15", "etd": "08:18", "platform": "1"},
    ]
    res = resolve_live_rail_platform(
        "atco:9100KNGX", "atco:9100PADTON", "08:15", mock_live
    )
    assert res.platform == "1"
    assert res.etd == "08:18"
    assert res.delay_minutes == 3
    mock_live.get_fastest_departures.assert_called_once_with("KGX", ["PAD"])


def test_resolve_live_rail_platform_with_openapi_dict() -> None:
    """Test resolve_live_rail_platform correctly extracts platforms from Darwin OpenAPI DeparturesBoard dict."""
    mock_live = MagicMock(spec=TrainLiveClient)
    mock_live.get_fastest_departures.return_value = {
        "departures": [
            {
                "crs": "PAD",
                "service": {
                    "std": "08:15",
                    "etd": "08:20",
                    "platform": "3",
                    "delayReason": "This service has been delayed by a track inspection",
                    "cancelReason": None,
                    "isCancelled": False,
                },
            }
        ]
    }

    res = resolve_live_rail_platform("KGX", "PAD", "08:15", mock_live)
    assert res.platform == "3"
    assert res.etd == "08:20"
    assert res.delay_minutes == 5
    assert res.delay_reason == "a track inspection"
    mock_live.get_fastest_departures.assert_called_once_with("KGX", ["PAD"])


def test_resolve_live_rail_platform_fallback_to_departure_board() -> None:
    """Test resolve_live_rail_platform falls back to get_departure_board when fastest departures has no platform."""
    mock_live = MagicMock(spec=TrainLiveClient)
    mock_live.get_fastest_departures.return_value = {
        "departures": [
            {
                "crs": "PAD",
                "service": {
                    "std": "08:15",
                    "etd": "On time",
                    "platform": None,
                },
            }
        ]
    }
    mock_live.get_departure_board.return_value = {
        "trainServices": [
            {
                "std": "08:15",
                "etd": "On time",
                "platform": "5A",
            }
        ]
    }

    res = resolve_live_rail_platform("KGX", "PAD", "08:15", mock_live)
    assert res.platform == "5A"
    assert res.etd == "On time"
    mock_live.get_departure_board.assert_called_once_with(
        crs="KGX", filter_crs="PAD", num_rows=5
    )


def test_resolve_live_rail_platform_past_scheduled_fallback() -> None:
    """Test resolve_live_rail_platform falls back to next upcoming departure if scheduled time is past."""
    mock_live = MagicMock(spec=TrainLiveClient)
    mock_live.get_fastest_departures.return_value = [
        {
            "std": "17:14",
            "etd": "On time",
            "platform": "1",
            "delayReason": None,
            "cancelReason": None,
            "isCancelled": False,
        },
        {
            "std": "17:21",
            "etd": "17:25",
            "platform": "4",
            "delayReason": "a track fault",
            "cancelReason": None,
            "isCancelled": False,
        },
    ]

    status = resolve_live_rail_platform(
        origin_id="naptan:CBG",
        dest_id="naptan:SVG",
        scheduled_time="16:51",
        live_client=mock_live,
    )
    assert status.platform == "1"
    assert status.std == "17:14"
    assert status.etd == "On time"


def test_resolve_live_rail_arrival_platform_scenarios() -> None:
    """Test resolve_live_rail_arrival_platform across varied live arrival responses and edge cases."""
    # 1. No live client returns None
    assert resolve_live_rail_arrival_platform("naptan:KGX", "naptan:CBG") is None

    # 2. Unknown destination CRS returns None
    mock_live = MagicMock(spec=TrainLiveClient)
    assert (
        resolve_live_rail_arrival_platform(
            "naptan:KGX", "invalid:unknown", live_client=mock_live
        )
        is None
    )

    # 3. Exact arrival time match
    mock_live.get_arrival_board.return_value = {
        "trainServices": [
            {"sta": "08:45", "eta": "On time", "platform": "1"},
            {"sta": "08:50", "eta": "08:52", "platform": "3"},
        ]
    }
    plat = resolve_live_rail_arrival_platform(
        "naptan:KGX", "naptan:CBG", scheduled_arr_time="08:50", live_client=mock_live
    )
    assert plat == "3"

    # 4. Approximate arrival time match (within 3 minutes)
    plat_approx = resolve_live_rail_arrival_platform(
        "naptan:KGX", "naptan:CBG", scheduled_arr_time="08:51", live_client=mock_live
    )
    assert plat_approx == "3"

    # 5. Fallback to first arrival when time does not match
    plat_fallback = resolve_live_rail_arrival_platform(
        "naptan:KGX", "naptan:CBG", scheduled_arr_time="09:30", live_client=mock_live
    )
    assert plat_fallback == "1"

    # 6. Service with missing or empty platform
    mock_live.get_arrival_board.return_value = {
        "trainServices": [
            {"sta": "08:45", "eta": "On time", "platform": None},
        ]
    }
    assert (
        resolve_live_rail_arrival_platform(
            "naptan:KGX", "naptan:CBG", live_client=mock_live
        )
        is None
    )

    # 7. Exception in get_arrival_board is swallowed gracefully
    mock_live.get_arrival_board.side_effect = RuntimeError("Network error")
    assert (
        resolve_live_rail_arrival_platform(
            "naptan:KGX", "naptan:CBG", live_client=mock_live
        )
        is None
    )


def test_resolve_live_rail_platform_destination_filtering() -> None:
    """Test that departures calling at dest_crs are prioritized over services that do not."""
    mock_live = MagicMock(spec=TrainLiveClient)
    # Service 0 departs earlier to Norwich (NRW), service 1 departs to Cambridge (CBG)
    mock_live.get_fastest_departures.return_value = [
        {
            "std": "08:00",
            "platform": "1",
            "destination": [{"crs": "NRW", "locationName": "Norwich"}],
        },
        {
            "std": "08:05",
            "platform": "7",
            "destination": [{"crs": "CBG", "locationName": "Cambridge"}],
        },
    ]

    res = resolve_live_rail_platform(
        origin_id="naptan:KGX",
        dest_id="naptan:CBG",
        scheduled_time="08:05",
        live_client=mock_live,
    )
    assert res.platform == "7"
    assert res.std == "08:05"

    # If scheduled_time is in the past, upcoming departure calling at CBG is selected
    res_upcoming = resolve_live_rail_platform(
        origin_id="naptan:KGX",
        dest_id="naptan:CBG",
        scheduled_time="07:50",
        live_client=mock_live,
    )
    assert res_upcoming.platform == "7"
