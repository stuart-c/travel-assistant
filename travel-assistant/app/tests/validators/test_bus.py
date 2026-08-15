"""Unit tests for Bus Open Data Service (BODS) validation."""

from unittest.mock import MagicMock, patch
import requests

from app.validators import validate_bus_api_key


def test_validate_bus_api_key_empty() -> None:
    """Test Bus API validation with empty key."""
    valid, message = validate_bus_api_key("")
    assert not valid
    assert "Bus API key is empty" in message

    valid, message = validate_bus_api_key("   ")
    assert not valid
    assert "Bus API key is empty" in message


@patch("app.datasources.bods.requests.get")
def test_validate_bus_api_key_success(mock_get: MagicMock) -> None:
    """Test Bus API validation success."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_get.return_value = mock_resp

    valid, message = validate_bus_api_key("valid_bus_token")
    assert valid
    assert "valid and active" in message
    assert mock_get.call_args[1]["params"] == {
        "api_key": "valid_bus_token",
        "limit": 1,
    }


@patch("app.datasources.bods.requests.get")
def test_validate_bus_api_key_custom_base_url(mock_get: MagicMock) -> None:
    """Test Bus API validation with custom base URL."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_get.return_value = mock_resp

    valid, message = validate_bus_api_key(
        "valid_bus_token", base_url="https://custom.bods.api/v1/dataset"
    )
    assert valid
    assert mock_get.call_args[0][0] == "https://custom.bods.api/v1/dataset"


@patch("app.datasources.bods.requests.get")
def test_validate_bus_api_key_unauthorised(mock_get: MagicMock) -> None:
    """Test Bus API validation with 401/403 error."""
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_get.return_value = mock_resp

    valid, message = validate_bus_api_key("invalid_token")
    assert not valid
    assert "Invalid Bus API key or unauthorised access" in message


@patch("app.datasources.bods.requests.get")
def test_validate_bus_api_key_other_api_error(mock_get: MagicMock) -> None:
    """Test Bus API validation with non-200 non-401 error."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_get.return_value = mock_resp

    valid, message = validate_bus_api_key("some_token")
    assert not valid
    assert "unexpected status code 500" in message


@patch("app.datasources.bods.requests.get")
def test_validate_bus_api_key_timeout(mock_get: MagicMock) -> None:
    """Test Bus API validation request timeout."""
    mock_get.side_effect = requests.exceptions.Timeout("Timed out")

    valid, message = validate_bus_api_key("some_token", timeout=2.0)
    assert not valid
    assert "timed out after 2.0s" in message


@patch("app.datasources.bods.requests.get")
def test_validate_bus_api_key_request_exception(mock_get: MagicMock) -> None:
    """Test Bus API validation network error."""
    mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")

    valid, message = validate_bus_api_key("some_token")
    assert not valid
    assert "Network error during Bus API validation" in message


@patch("app.datasources.bods.requests.get")
def test_validate_bus_api_key_generic_exception(mock_get: MagicMock) -> None:
    """Test Bus API validation unexpected runtime error."""
    mock_get.side_effect = RuntimeError("Fatal crash")

    valid, message = validate_bus_api_key("some_token")
    assert not valid
    assert "Unexpected error during Bus API validation" in message
