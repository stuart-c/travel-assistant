"""Unit tests for Google Maps credentials validator."""

from unittest.mock import MagicMock, patch
from googlemaps.exceptions import ApiError as GoogleMapsApiError

from app.validators import validate_google_maps_api_key
from app.validators.dispatcher import validate_service_credentials


def test_validate_google_maps_api_key_empty() -> None:
    """Test Google Maps API validation with empty key."""
    valid, message = validate_google_maps_api_key("")
    assert not valid
    assert "Google Maps API key is required." in message


@patch("app.datasources.google_maps.googlemaps.Client")
def test_validate_google_maps_api_key_success(mock_client_cls: MagicMock) -> None:
    """Test Google Maps API validation with zero-cost probe (INVALID_REQUEST)."""
    mock_instance = MagicMock()
    mock_instance.geocode.side_effect = GoogleMapsApiError(
        status="INVALID_REQUEST", message="Missing address"
    )
    mock_client_cls.return_value = mock_instance

    valid, message = validate_google_maps_api_key(
        "AIzaValidKey", region="gb", timeout=3.0
    )
    assert valid is True
    assert "zero-cost probe verified" in message
    mock_client_cls.assert_called_once_with(key="AIzaValidKey", timeout=3.0)


@patch("app.datasources.google_maps.googlemaps.Client")
def test_validate_google_maps_api_key_denied(mock_client_cls: MagicMock) -> None:
    """Test Google Maps API validation when request is denied."""
    mock_instance = MagicMock()
    mock_instance.geocode.side_effect = GoogleMapsApiError(
        status="REQUEST_DENIED", message="The provided API key is invalid"
    )
    mock_client_cls.return_value = mock_instance

    valid, message = validate_google_maps_api_key("AIzaInvalidKey")
    assert valid is False
    assert "request denied" in message.lower()


@patch("app.datasources.google_maps.googlemaps.Client")
def test_dispatcher_google_maps(mock_client_cls: MagicMock) -> None:
    """Test dispatcher routes google_maps / googlemaps service keys correctly."""
    mock_instance = MagicMock()
    mock_instance.geocode.side_effect = GoogleMapsApiError(
        status="INVALID_REQUEST", message="Missing address"
    )
    mock_client_cls.return_value = mock_instance

    for alias in ["google_maps", "googlemaps", "google", "maps"]:
        valid, msg, extra = validate_service_credentials(
            alias,
            {"google_maps_api_key": "AIzaTest", "google_maps_region": "uk"},
        )
        assert valid is True
        assert "zero-cost probe verified" in msg
        assert extra == {}
