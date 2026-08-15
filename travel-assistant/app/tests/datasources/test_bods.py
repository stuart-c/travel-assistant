"""Unit tests for BodsClient."""

from unittest.mock import MagicMock, patch
import pytest
import requests
from flask import Flask

from app.datasources.bods import BodsClient
from app.datasources.exceptions import (
    DataSourceAuthError,
    DataSourceConfigError,
    DataSourceConnectionError,
    DataSourceError,
    DataSourceRateLimitError,
)
from app.models.setting import Setting


def test_bods_client_from_settings(app: Flask) -> None:
    """Test BodsClient initialisation from Setting model."""
    with app.app_context():
        Setting.set_val("bus_api_key", "test-bus-key-123")
        client = BodsClient.from_settings()
        assert client.api_key == "test-bus-key-123"
        assert client.provider_name == "bods"


def test_bods_validate_credentials_empty() -> None:
    """Test validate_credentials returns invalid on empty key."""
    client = BodsClient(api_key="")
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "empty" in res["message"]


@patch("app.datasources.bods.requests.get")
def test_bods_validate_credentials_success(mock_get: MagicMock) -> None:
    """Test validate_credentials with HTTP 200 success."""
    mock_get.return_value = MagicMock(status_code=200)
    client = BodsClient(api_key="valid-key")
    res = client.validate_credentials()
    assert res["valid"] is True
    assert "valid and active" in res["message"]


@patch("app.datasources.bods.requests.get")
def test_bods_validate_credentials_auth_fail(mock_get: MagicMock) -> None:
    """Test validate_credentials with HTTP 401 / 403."""
    mock_get.return_value = MagicMock(status_code=401)
    client = BodsClient(api_key="bad-key")
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "unauthorised access" in res["message"]


@patch("app.datasources.bods.requests.get")
def test_bods_validate_credentials_rate_limit(mock_get: MagicMock) -> None:
    """Test validate_credentials with HTTP 429."""
    mock_get.return_value = MagicMock(status_code=429)
    client = BodsClient(api_key="rate-key")
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "rate limit" in res["message"]


@patch("app.datasources.bods.requests.get")
def test_bods_validate_credentials_unexpected_code(mock_get: MagicMock) -> None:
    """Test validate_credentials with HTTP 500."""
    mock_get.return_value = MagicMock(status_code=500, text="Internal server error")
    client = BodsClient(api_key="any-key")
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "unexpected status code 500" in res["message"]


@patch("app.datasources.bods.requests.get")
def test_bods_validate_credentials_timeout(mock_get: MagicMock) -> None:
    """Test validate_credentials timeout handling."""
    mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")
    client = BodsClient(api_key="timeout-key")
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "timed out" in res["message"]


@patch("app.datasources.bods.requests.get")
def test_bods_validate_credentials_request_exception(mock_get: MagicMock) -> None:
    """Test validate_credentials RequestException handling."""
    mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")
    client = BodsClient(api_key="conn-key")
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "Network error" in res["message"]


@patch("app.datasources.bods.requests.get")
def test_bods_validate_credentials_general_exception(mock_get: MagicMock) -> None:
    """Test validate_credentials general Exception handling."""
    mock_get.side_effect = RuntimeError("Crash")
    client = BodsClient(api_key="crash-key")
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "Unexpected error" in res["message"]


def test_bods_fetch_routes_empty_key() -> None:
    """Test fetch_routes raises DataSourceConfigError when key is missing."""
    client = BodsClient(api_key="")
    with pytest.raises(DataSourceConfigError) as exc_info:
        client.fetch_routes()
    assert "not configured" in str(exc_info.value)


@patch("app.datasources.bods.requests.get")
def test_bods_fetch_routes_success(mock_get: MagicMock) -> None:
    """Test fetch_routes successfully parses routes with and without lines array."""
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {
        "results": [
            {
                "id": 101,
                "name": "Oxford City Lines",
                "operator_name": "Oxford Bus Company",
                "noc": ["OBC"],
                "description": "City routes",
                "lines": ["1", "5"],
                "origin": "City Centre",
                "destination": "Blackbird Leys",
            },
            {
                "id": 102,
                "name": "London Express",
                "operator_name": "Stagecoach",
                "noc": ["SC"],
                "description": "Express coach",
                "lines": [],
                "origin": "Gloucester Green",
                "destination": "Victoria",
            },
        ]
    }
    mock_get.return_value = mock_response

    client = BodsClient(api_key="valid-key")
    routes = client.fetch_routes(limit=10)
    assert len(routes) == 3
    assert routes[0]["route_number"] == "1"
    assert routes[0]["operator_name"] == "Oxford Bus Company"
    assert routes[1]["route_number"] == "5"
    assert routes[2]["route_number"] == "DS-102"


@patch("app.datasources.bods.requests.get")
def test_bods_fetch_routes_auth_error(mock_get: MagicMock) -> None:
    """Test fetch_routes raises DataSourceAuthError on 401."""
    mock_get.return_value = MagicMock(status_code=401)
    client = BodsClient(api_key="bad-key")
    with pytest.raises(DataSourceAuthError):
        client.fetch_routes()


@patch("app.datasources.bods.requests.get")
def test_bods_fetch_routes_rate_limit(mock_get: MagicMock) -> None:
    """Test fetch_routes raises DataSourceRateLimitError on 429."""
    mock_get.return_value = MagicMock(status_code=429)
    client = BodsClient(api_key="rate-key")
    with pytest.raises(DataSourceRateLimitError):
        client.fetch_routes()


@patch("app.datasources.bods.requests.get")
def test_bods_fetch_routes_timeout(mock_get: MagicMock) -> None:
    """Test fetch_routes raises DataSourceConnectionError on timeout."""
    mock_get.side_effect = requests.exceptions.Timeout("Timed out")
    client = BodsClient(api_key="key")
    with pytest.raises(DataSourceConnectionError):
        client.fetch_routes()


@patch("app.datasources.bods.requests.get")
def test_bods_fetch_routes_request_exception(mock_get: MagicMock) -> None:
    """Test fetch_routes raises DataSourceConnectionError on RequestException."""
    mock_get.side_effect = requests.exceptions.ConnectionError("Refused")
    client = BodsClient(api_key="key")
    with pytest.raises(DataSourceConnectionError):
        client.fetch_routes()


@patch("app.datasources.bods.requests.get")
def test_bods_fetch_routes_general_exception(mock_get: MagicMock) -> None:
    """Test fetch_routes raises DataSourceError on generic Exception."""
    mock_get.side_effect = ValueError("Corrupt JSON")
    client = BodsClient(api_key="key")
    with pytest.raises(DataSourceError):
        client.fetch_routes()
