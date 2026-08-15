"""Unit tests for HomeAssistantClient datasource."""

import os
from unittest.mock import MagicMock, patch
import pytest
import requests
from flask import Flask

from app.datasources.exceptions import (
    DataSourceAuthError,
    DataSourceConfigError,
    DataSourceConnectionError,
    DataSourceError,
)
from app.datasources.homeassistant import HomeAssistantClient
from app.models.setting import Setting


def test_ha_client_from_settings(app: Flask) -> None:
    """Test HomeAssistantClient initialisation from Setting model and environment."""
    with app.app_context():
        Setting.set_val("ha_url", "http://192.168.1.50:8123")
        Setting.set_val("ha_token", "saved-ha-token-456")
        client = HomeAssistantClient.from_settings()
        assert client.base_url == "http://192.168.1.50:8123/api"
        assert client.token == "saved-ha-token-456"
        assert client.provider_name == "homeassistant"

        # Test from dict
        client_dict = HomeAssistantClient.from_settings(
            {"ha_url": "http://ha-local:8123", "ha_token": "dict-token"}
        )
        assert client_dict.token == "dict-token"

        # Test from custom object with get_val
        class MockSettingsObj:
            def get_val(self, key: str) -> str:
                return "obj-token" if key == "ha_token" else "http://obj-url"

        client_obj = HomeAssistantClient.from_settings(MockSettingsObj())
        assert client_obj.token == "obj-token"


def test_ha_client_from_env() -> None:
    """Test HomeAssistantClient URL and token resolution from environment variables."""
    with patch.dict(
        os.environ,
        {
            "SUPERVISOR_TOKEN": "supervisor-token-789",
            "SUPERVISOR_URL": "http://supervisor",
        },
    ):
        client = HomeAssistantClient.from_settings()
        assert client.token == "supervisor-token-789"
        assert client.base_url == "http://supervisor/core/api"


def test_ha_client_headers_missing_token() -> None:
    """Test _get_headers raises DataSourceConfigError when token is missing."""
    with patch.dict(os.environ, {}, clear=True):
        client = HomeAssistantClient(base_url="http://supervisor/core/api", token="")
        with pytest.raises(DataSourceConfigError) as exc_info:
            client._get_headers()
        assert "SUPERVISOR_TOKEN" in str(exc_info.value)


@patch("app.datasources.homeassistant.requests.get")
def test_ha_validate_credentials_success(mock_get: MagicMock) -> None:
    """Test validate_credentials with HTTP 200 success response."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "location_name": "My Smart Home",
        "version": "2026.8.0",
        "time_zone": "Europe/London",
    }
    mock_get.return_value = mock_resp

    client = HomeAssistantClient(token="valid-token")
    result = client.validate_credentials()
    assert result["valid"] is True
    assert "My Smart Home" in result["message"]
    assert result["version"] == "2026.8.0"


@patch("app.datasources.homeassistant.requests.get")
def test_ha_validate_credentials_auth_error(mock_get: MagicMock) -> None:
    """Test validate_credentials with HTTP 401 raises DataSourceAuthError."""
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "401: Unauthorized"
    mock_get.return_value = mock_resp

    client = HomeAssistantClient(token="bad-token")
    with pytest.raises(DataSourceAuthError) as exc_info:
        client.validate_credentials()
    assert "Authentication failed" in str(exc_info.value)


@patch("app.datasources.homeassistant.requests.get")
def test_ha_validate_credentials_http_error(mock_get: MagicMock) -> None:
    """Test validate_credentials with HTTP 500 raises DataSourceError."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"
    mock_get.return_value = mock_resp

    client = HomeAssistantClient(token="valid-token")
    with pytest.raises(DataSourceError) as exc_info:
        client.validate_credentials()
    assert "HTTP 500" in str(exc_info.value)


@patch("app.datasources.homeassistant.requests.get")
def test_ha_validate_credentials_timeout(mock_get: MagicMock) -> None:
    """Test validate_credentials timeout raises DataSourceConnectionError."""
    mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")
    client = HomeAssistantClient(token="valid-token")
    with pytest.raises(DataSourceConnectionError) as exc_info:
        client.validate_credentials()
    assert "Connection timed out" in str(exc_info.value)


@patch("app.datasources.homeassistant.requests.get")
def test_ha_fetch_zones_success(mock_get: MagicMock) -> None:
    """Test fetch_zones parses zone.* entities and extracts valid coordinates."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {
            "entity_id": "zone.home",
            "attributes": {
                "friendly_name": "Home",
                "latitude": 51.7520,
                "longitude": -1.2577,
                "radius": 100,
            },
        },
        {
            "entity_id": "zone.work_place",
            "attributes": {
                "latitude": "51.5074",
                "longitude": "-0.1278",
            },
        },
        {
            "entity_id": "sensor.temperature",
            "attributes": {"latitude": 51.5, "longitude": -0.1},
        },
        {
            "entity_id": "zone.invalid_coords",
            "attributes": {
                "friendly_name": "Invalid Coords",
                "latitude": "invalid",
                "longitude": -0.1,
            },
        },
        {
            "entity_id": "zone.missing_coords",
            "attributes": {"friendly_name": "Missing Coords"},
        },
        {
            "entity_id": "zone.out_of_bounds",
            "attributes": {
                "friendly_name": "Out Of Bounds",
                "latitude": 100.0,
                "longitude": -0.1,
            },
        },
    ]
    mock_get.return_value = mock_resp

    client = HomeAssistantClient(token="valid-token")
    zones = client.fetch_zones()
    assert len(zones) == 2

    home_zone = next(z for z in zones if z["entity_id"] == "zone.home")
    assert home_zone["name"] == "Home"
    assert home_zone["latitude"] == 51.7520
    assert home_zone["longitude"] == -1.2577

    work_zone = next(z for z in zones if z["entity_id"] == "zone.work_place")
    assert work_zone["name"] == "Work Place"
    assert work_zone["latitude"] == 51.5074
    assert work_zone["longitude"] == -0.1278


@patch("app.datasources.homeassistant.requests.get")
def test_ha_fetch_zones_errors(mock_get: MagicMock) -> None:
    """Test fetch_zones error conditions."""
    client = HomeAssistantClient(token="valid-token")

    # 401 Auth error
    mock_get.return_value = MagicMock(status_code=401, text="Unauthorized")
    with pytest.raises(DataSourceAuthError):
        client.fetch_zones()

    # 500 Internal error
    mock_get.return_value = MagicMock(status_code=500, text="Error")
    with pytest.raises(DataSourceError):
        client.fetch_zones()

    # Non-list response
    mock_get.return_value = MagicMock(
        status_code=200, json=lambda: {"error": "bad format"}
    )
    with pytest.raises(DataSourceError):
        client.fetch_zones()

    # Timeout
    mock_get.side_effect = requests.exceptions.Timeout("Timeout")
    with pytest.raises(DataSourceConnectionError):
        client.fetch_zones()

    # Network RequestException
    mock_get.side_effect = requests.exceptions.RequestException("Network reset")
    with pytest.raises(DataSourceConnectionError):
        client.fetch_zones()


@patch("app.datasources.homeassistant.requests.get")
def test_ha_validate_credentials_network_error(mock_get: MagicMock) -> None:
    """Test validate_credentials RequestException raises DataSourceConnectionError."""
    mock_get.side_effect = requests.exceptions.RequestException("DNS lookup failed")
    client = HomeAssistantClient(token="valid-token")
    with pytest.raises(DataSourceConnectionError) as exc_info:
        client.validate_credentials()
    assert "DNS lookup failed" in str(exc_info.value)
