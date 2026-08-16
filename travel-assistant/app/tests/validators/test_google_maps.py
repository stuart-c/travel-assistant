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
    """Test Google Maps API validation with successful geocoding probe."""
    mock_instance = MagicMock()
    mock_instance.geocode.return_value = [{"formatted_address": "London, UK"}]
    mock_client_cls.return_value = mock_instance

    valid, message = validate_google_maps_api_key(
        "AIzaValidKey", region="gb", timeout=3.0
    )
    assert valid is True
    assert "Google Maps credentials valid." in message
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
    """Test dispatcher routes google_maps service key correctly."""
    mock_instance = MagicMock()
    mock_instance.geocode.return_value = [{"formatted_address": "London, UK"}]
    mock_client_cls.return_value = mock_instance

    valid, msg, extra = validate_service_credentials(
        "google_maps",
        {"google_maps_api_key": "AIzaTest", "google_maps_region": "uk"},
    )
    assert valid is True
    assert "Google Maps credentials valid." in msg
    assert extra == {}
