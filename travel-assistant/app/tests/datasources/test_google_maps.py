"""Unit tests for GoogleMapsClient."""

from unittest.mock import MagicMock, patch
import pytest
from flask import Flask
from googlemaps.exceptions import (
    ApiError as GoogleMapsApiError,
    Timeout as GoogleMapsTimeout,
    TransportError as GoogleMapsTransportError,
)


from app.datasources.exceptions import (
    DataSourceAuthError,
    DataSourceConfigError,
    DataSourceConnectionError,
    DataSourceError,
    DataSourceRateLimitError,
)
from app.datasources.google_maps import GoogleMapsClient
from app.models.setting import Setting


def test_google_maps_initialisation() -> None:
    """Test GoogleMapsClient direct initialisation and defaults."""
    client = GoogleMapsClient(api_key="AIzaTestKey")
    assert client.api_key == "AIzaTestKey"
    assert client.region == "uk"
    assert client.provider_name == "google_maps"
    assert client.timeout == 10.0

    client_custom = GoogleMapsClient(api_key="AIzaCustom", region="us", timeout=15.0)
    assert client_custom.api_key == "AIzaCustom"
    assert client_custom.region == "us"
    assert client_custom.timeout == 15.0


def test_google_maps_from_settings(app: Flask) -> None:
    """Test GoogleMapsClient initialisation from Setting model and dictionaries."""
    with app.app_context():
        Setting.set_val("google_maps_api_key", "AIzaDbKey")
        Setting.set_val("google_maps_region", "gb")

        client = GoogleMapsClient.from_settings()
        assert client.api_key == "AIzaDbKey"
        assert client.region == "gb"

    # From dictionary
    dict_client = GoogleMapsClient.from_settings(
        {"google_maps_api_key": "AIzaDict", "google_maps_region": "fr"}
    )
    assert dict_client.api_key == "AIzaDict"
    assert dict_client.region == "fr"

    # From object with get()
    obj_with_get = MagicMock()
    obj_with_get.get.side_effect = lambda k, default=None: {
        "google_maps_api_key": "AIzaObj",
        "google_maps_region": "de",
    }.get(k, default)
    obj_client = GoogleMapsClient.from_settings(obj_with_get)
    assert obj_client.api_key == "AIzaObj"
    assert obj_client.region == "de"

    # From object with get_val()
    obj_with_get_val = MagicMock(spec=["get_val"])
    obj_with_get_val.get_val.side_effect = lambda k, default=None: {
        "google_maps_api_key": "AIzaGetVal",
        "google_maps_region": "uk",
    }.get(k, default)
    get_val_client = GoogleMapsClient.from_settings(obj_with_get_val)
    assert get_val_client.api_key == "AIzaGetVal"
    assert get_val_client.region == "uk"


def test_google_maps_from_settings_db_exception() -> None:
    """Test GoogleMapsClient fallback when database read fails."""
    with patch("app.models.setting.Setting.get_val", side_effect=Exception("DB fail")):
        client = GoogleMapsClient.from_settings()
        assert client.api_key == ""
        assert client.region == "uk"


def test_google_maps_get_client_caching_and_error() -> None:
    """Test get_client caching, creation, and config error when API key missing."""
    mock_injected = MagicMock()
    cached_client = GoogleMapsClient(api_key="k", client=mock_injected)
    assert cached_client.get_client() is mock_injected

    empty_client = GoogleMapsClient(api_key="")
    with pytest.raises(DataSourceConfigError) as exc_info:
        empty_client.get_client()
    assert "Google Maps API key is not configured." in str(exc_info.value)

    with patch("googlemaps.Client") as mock_gm_constructor:
        new_client = GoogleMapsClient(api_key="valid-key", timeout=7.5)
        created = new_client.get_client()
        mock_gm_constructor.assert_called_once_with(key="valid-key", timeout=7.5)
        assert created == mock_gm_constructor.return_value


def test_google_maps_validate_credentials_empty() -> None:
    """Test validate_credentials returns failure when api_key is empty."""
    client = GoogleMapsClient(api_key="")
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "Google Maps API key is required." in res["message"]

    is_valid, msg = client.validate_tuple()
    assert is_valid is False
    assert "Google Maps API key is required." in msg


def test_google_maps_validate_credentials_probe_success() -> None:
    """Test validate_credentials when probe returns success directly."""
    mock_sdk = MagicMock()
    mock_sdk.geocode.return_value = [{"formatted_address": "London, UK"}]
    client = GoogleMapsClient(api_key="test-key", client=mock_sdk)

    res = client.validate_credentials()
    assert res["valid"] is True
    assert "Google Maps credentials valid." in res["message"]

    is_valid, msg = client.validate_tuple()
    assert is_valid is True


def test_google_maps_validate_credentials_zero_results() -> None:
    """Test validate_credentials handles ZERO_RESULTS as valid probe response."""
    mock_sdk = MagicMock()
    err = GoogleMapsApiError(status="ZERO_RESULTS", message="No results found")
    mock_sdk.geocode.side_effect = err
    client = GoogleMapsClient(api_key="test-key", client=mock_sdk)

    res = client.validate_credentials()
    assert res["valid"] is True
    assert "Google Maps credentials valid." in res["message"]

    is_valid, msg = client.validate_tuple()
    assert is_valid is True


def test_google_maps_validate_credentials_request_denied() -> None:
    """Test validate_credentials handles REQUEST_DENIED as invalid key."""
    mock_sdk = MagicMock()
    err = GoogleMapsApiError(
        status="REQUEST_DENIED", message="The provided API key is invalid."
    )
    mock_sdk.geocode.side_effect = err
    client = GoogleMapsClient(api_key="test-key", client=mock_sdk)

    res = client.validate_credentials()
    assert res["valid"] is False
    assert "request denied" in res["message"].lower()


def test_google_maps_validate_credentials_over_query_limit() -> None:
    """Test validate_credentials handles OVER_QUERY_LIMIT."""
    mock_sdk = MagicMock()
    err = GoogleMapsApiError(status="OVER_QUERY_LIMIT", message="Quota exceeded")
    mock_sdk.geocode.side_effect = err
    client = GoogleMapsClient(api_key="test-key", client=mock_sdk)

    res = client.validate_credentials()
    assert res["valid"] is False
    assert "quota or rate limit exceeded" in res["message"].lower()


def test_google_maps_validate_credentials_other_api_error() -> None:
    """Test validate_credentials handles unknown ApiError status."""
    mock_sdk = MagicMock()
    err = GoogleMapsApiError(status="UNKNOWN_ERROR", message="Server error")
    mock_sdk.geocode.side_effect = err
    client = GoogleMapsClient(api_key="test-key", client=mock_sdk)

    res = client.validate_credentials()
    assert res["valid"] is False
    assert "validation error" in res["message"].lower()


def test_google_maps_validate_credentials_timeout() -> None:
    """Test validate_credentials handles network timeout."""
    mock_sdk = MagicMock()
    mock_sdk.geocode.side_effect = GoogleMapsTimeout()
    client = GoogleMapsClient(api_key="test-key", client=mock_sdk)

    res = client.validate_credentials()
    assert res["valid"] is False
    assert "Connection timeout" in res["message"]


def test_google_maps_validate_credentials_transport_error() -> None:
    """Test validate_credentials handles transport/connection error."""
    mock_sdk = MagicMock()
    mock_sdk.geocode.side_effect = GoogleMapsTransportError("Network unreachable")
    client = GoogleMapsClient(api_key="test-key", client=mock_sdk)

    res = client.validate_credentials()
    assert res["valid"] is False
    assert "connection error" in res["message"].lower()


def test_google_maps_validate_credentials_unexpected_exception() -> None:
    """Test validate_credentials handles generic unexpected exception."""
    mock_sdk = MagicMock()
    mock_sdk.geocode.side_effect = RuntimeError("Fatal crash")
    client = GoogleMapsClient(api_key="test-key", client=mock_sdk)

    res = client.validate_credentials()
    assert res["valid"] is False
    assert "Unexpected error" in res["message"]


def test_google_maps_geocode_success() -> None:
    """Test geocode method returns list of results."""
    mock_sdk = MagicMock()
    mock_sdk.geocode.return_value = [
        {
            "formatted_address": "London",
            "geometry": {"location": {"lat": 51.5, "lng": -0.1}},
        }
    ]
    client = GoogleMapsClient(api_key="test-key", region="uk", client=mock_sdk)

    results = client.geocode("London", region="gb", components={"country": "GB"})
    assert len(results) == 1
    assert results[0]["formatted_address"] == "London"
    mock_sdk.geocode.assert_called_once_with(
        address="London", region="gb", components={"country": "GB"}
    )

    # Empty result
    mock_sdk.geocode.return_value = None
    assert client.geocode("Unknown place") == []


def test_google_maps_geocode_errors() -> None:
    """Test geocode exception handling."""
    mock_sdk = MagicMock()
    client = GoogleMapsClient(api_key="test-key", client=mock_sdk)

    # Auth error
    mock_sdk.geocode.side_effect = GoogleMapsApiError(
        status="REQUEST_DENIED", message="Denied"
    )
    with pytest.raises(DataSourceAuthError):
        client.geocode("London")

    # Rate limit error
    mock_sdk.geocode.side_effect = GoogleMapsApiError(
        status="OVER_QUERY_LIMIT", message="Quota hit"
    )
    with pytest.raises(DataSourceRateLimitError):
        client.geocode("London")

    # Generic ApiError
    mock_sdk.geocode.side_effect = GoogleMapsApiError(
        status="INVALID_REQUEST", message="Bad query"
    )
    with pytest.raises(DataSourceError):
        client.geocode("London")

    # Timeout
    mock_sdk.geocode.side_effect = GoogleMapsTimeout("Timeout")
    with pytest.raises(DataSourceConnectionError):
        client.geocode("London")

    # TransportError
    mock_sdk.geocode.side_effect = GoogleMapsTransportError("Network error")
    with pytest.raises(DataSourceConnectionError):
        client.geocode("London")


def test_google_maps_reverse_geocode_success_and_errors() -> None:
    """Test reverse_geocode method results and error handling."""
    mock_sdk = MagicMock()
    mock_sdk.reverse_geocode.return_value = [{"formatted_address": "Piccadilly Circus"}]
    client = GoogleMapsClient(api_key="test-key", client=mock_sdk)

    results = client.reverse_geocode(51.51, -0.13)
    assert len(results) == 1
    assert results[0]["formatted_address"] == "Piccadilly Circus"
    mock_sdk.reverse_geocode.assert_called_once_with((51.51, -0.13))

    mock_sdk.reverse_geocode.return_value = None
    assert client.reverse_geocode(0.0, 0.0) == []

    # Errors
    mock_sdk.reverse_geocode.side_effect = GoogleMapsApiError(
        status="REQUEST_DENIED", message="Key revoked"
    )
    with pytest.raises(DataSourceAuthError):
        client.reverse_geocode(51.51, -0.13)

    mock_sdk.reverse_geocode.side_effect = GoogleMapsTimeout("Timeout")
    with pytest.raises(DataSourceConnectionError):
        client.reverse_geocode(51.51, -0.13)

    mock_sdk.reverse_geocode.side_effect = GoogleMapsTransportError("Transport failure")
    with pytest.raises(DataSourceConnectionError):
        client.reverse_geocode(51.51, -0.13)


def test_google_maps_distance_matrix_success_and_errors() -> None:
    """Test distance_matrix method results and error handling."""
    mock_sdk = MagicMock()
    expected = {
        "destination_addresses": ["London"],
        "origin_addresses": ["Oxford"],
        "rows": [
            {"elements": [{"distance": {"value": 90000}, "duration": {"value": 3600}}]}
        ],
        "status": "OK",
    }
    mock_sdk.distance_matrix.return_value = expected
    client = GoogleMapsClient(api_key="test-key", region="uk", client=mock_sdk)

    matrix = client.distance_matrix(
        origins="Oxford",
        destinations="London",
        mode="walking",
        departure_time=1700000000,
        units="metric",
    )
    assert matrix == expected
    mock_sdk.distance_matrix.assert_called_once_with(
        origins="Oxford",
        destinations="London",
        mode="walking",
        departure_time=1700000000,
        units="metric",
        region="uk",
    )

    # Errors
    mock_sdk.distance_matrix.side_effect = GoogleMapsApiError(
        status="REQUEST_DENIED", message="Auth failed"
    )
    with pytest.raises(DataSourceAuthError):
        client.distance_matrix("Oxford", "London")

    mock_sdk.distance_matrix.side_effect = GoogleMapsTimeout("Timeout")
    with pytest.raises(DataSourceConnectionError):
        client.distance_matrix("Oxford", "London")

    mock_sdk.distance_matrix.side_effect = GoogleMapsTransportError("Transport error")
    with pytest.raises(DataSourceConnectionError):
        client.distance_matrix("Oxford", "London")


def test_google_maps_directions_success_and_errors() -> None:
    """Test directions method results and error handling."""
    mock_sdk = MagicMock()
    expected_routes = [{"summary": "A40", "legs": [{"distance": {"text": "50 mi"}}]}]
    mock_sdk.directions.return_value = expected_routes
    client = GoogleMapsClient(api_key="test-key", region="uk", client=mock_sdk)

    routes = client.directions(
        origin=(51.5, -0.1),
        destination=(51.7, -1.2),
        mode="transit",
        departure_time=1700000000,
        alternatives=True,
    )
    assert routes == expected_routes
    mock_sdk.directions.assert_called_once_with(
        origin=(51.5, -0.1),
        destination=(51.7, -1.2),
        mode="transit",
        departure_time=1700000000,
        alternatives=True,
        region="uk",
    )

    # Errors
    mock_sdk.directions.side_effect = GoogleMapsApiError(
        status="REQUEST_DENIED", message="Auth failed"
    )
    with pytest.raises(DataSourceAuthError):
        client.directions((51.5, -0.1), (51.7, -1.2))

    mock_sdk.directions.side_effect = GoogleMapsTimeout("Timeout")
    with pytest.raises(DataSourceConnectionError):
        client.directions((51.5, -0.1), (51.7, -1.2))

    mock_sdk.directions.side_effect = GoogleMapsTransportError("Transport error")
    with pytest.raises(DataSourceConnectionError):
        client.directions((51.5, -0.1), (51.7, -1.2))
