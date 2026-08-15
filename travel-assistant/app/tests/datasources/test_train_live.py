"""Unit tests for TrainLiveClient."""

from unittest.mock import MagicMock, patch
import pytest
import requests
from flask import Flask

from app.datasources.train_live import (
    DEFAULT_DARWIN_SOAP_ENDPOINT,
    TrainLiveClient,
)
from app.datasources.exceptions import (
    DataSourceAuthError,
    DataSourceConfigError,
    DataSourceConnectionError,
    DataSourceError,
)
from app.db.settings import SettingsRepository


def test_train_live_from_settings(app: Flask) -> None:
    """Test TrainLiveClient initialisation from SettingsRepository."""
    with app.app_context():
        repo = SettingsRepository()
        repo.set("train_live_api_key", "test-live-key")
        repo.set("train_live_endpoint", "https://custom.darwin/soap")

        client = TrainLiveClient.from_settings(repo)
        assert client.api_key == "test-live-key"
        assert client.endpoint == "https://custom.darwin/soap"
        assert client.provider_name == "train_live"


def test_train_live_validate_credentials_empty() -> None:
    """Test validate_credentials returns invalid for empty token."""
    client = TrainLiveClient(api_key="")
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "empty" in res["message"]


@patch("app.datasources.train_live.requests.get")
def test_train_live_validate_openapi_success(mock_get: MagicMock) -> None:
    """Test validate_credentials against REST/OpenAPI endpoint returning 200."""
    mock_get.return_value = MagicMock(status_code=200)
    client = TrainLiveClient(
        api_key="valid-key", endpoint="https://api.nationalrail.co.uk/v1"
    )
    res = client.validate_credentials()
    assert res["valid"] is True
    assert "valid and active (OpenAPI)" in res["message"]


@patch("app.datasources.train_live.requests.get")
def test_train_live_validate_openapi_auth_fail(mock_get: MagicMock) -> None:
    """Test validate_credentials against REST/OpenAPI endpoint returning 401."""
    mock_get.return_value = MagicMock(status_code=401)
    client = TrainLiveClient(
        api_key="bad-key", endpoint="https://api.nationalrail.co.uk/v1"
    )
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "unauthorised access" in res["message"]


@patch("app.datasources.train_live.requests.get")
@patch("app.datasources.train_live.requests.post")
def test_train_live_validate_openapi_fallback_to_soap(
    mock_post: MagicMock, mock_get: MagicMock
) -> None:
    """Test validate_credentials falls back to SOAP when OpenAPI returns 404."""
    mock_get.return_value = MagicMock(status_code=404)
    mock_post.return_value = MagicMock(
        status_code=200, text="<GetStationBoardResult>OK</GetStationBoardResult>"
    )

    client = TrainLiveClient(
        api_key="valid-key", endpoint="https://api.nationalrail.co.uk/v1"
    )
    res = client.validate_credentials()
    assert res["valid"] is True
    assert "valid and active (SOAP)" in res["message"]


@patch("app.datasources.train_live.requests.post")
def test_train_live_validate_soap_success(mock_post: MagicMock) -> None:
    """Test SOAP validation success."""
    mock_post.return_value = MagicMock(
        status_code=200, text="<GetStationBoardResult>Departure</GetStationBoardResult>"
    )
    client = TrainLiveClient(
        api_key="valid-soap-key", endpoint=DEFAULT_DARWIN_SOAP_ENDPOINT
    )
    res = client.validate_credentials()
    assert res["valid"] is True
    assert "valid and active (SOAP)" in res["message"]


@patch("app.datasources.train_live.requests.post")
def test_train_live_validate_soap_invalid_token(mock_post: MagicMock) -> None:
    """Test SOAP validation with Invalid token string in response body."""
    mock_post.return_value = MagicMock(
        status_code=200, text="<faultstring>Invalid token value</faultstring>"
    )
    client = TrainLiveClient(
        api_key="bad-soap-key", endpoint=DEFAULT_DARWIN_SOAP_ENDPOINT
    )
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "authentication failed" in res["message"]


@patch("app.datasources.train_live.requests.post")
def test_train_live_validate_soap_http_errors(mock_post: MagicMock) -> None:
    """Test SOAP validation with HTTP 403 and unexpected 500 status codes."""
    # 403 Forbidden
    mock_post.return_value = MagicMock(status_code=403, text="Forbidden")
    client = TrainLiveClient(api_key="bad-key", endpoint=DEFAULT_DARWIN_SOAP_ENDPOINT)
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "HTTP 403" in res["message"]

    # 500 Unexpected
    mock_post.return_value = MagicMock(status_code=500, text="Server Error")
    res2 = client.validate_credentials()
    assert res2["valid"] is False
    assert "unexpected status code 500" in res2["message"]


@patch("app.datasources.train_live.requests.post")
def test_train_live_validate_soap_exceptions(mock_post: MagicMock) -> None:
    """Test SOAP validation timeout, request error, and generic exception."""
    client = TrainLiveClient(api_key="test-key", endpoint=DEFAULT_DARWIN_SOAP_ENDPOINT)

    # Timeout
    mock_post.side_effect = requests.exceptions.Timeout("Timed out")
    res_t = client.validate_credentials()
    assert res_t["valid"] is False
    assert "timed out" in res_t["message"]

    # RequestException
    mock_post.side_effect = requests.exceptions.ConnectionError("Refused")
    res_r = client.validate_credentials()
    assert res_r["valid"] is False
    assert "Network error" in res_r["message"]

    # Generic Exception
    mock_post.side_effect = RuntimeError("Crash")
    res_g = client.validate_credentials()
    assert res_g["valid"] is False
    assert "Unexpected error" in res_g["message"]


def test_train_live_fetch_departures_empty_token() -> None:
    """Test fetch_departures raises DataSourceConfigError when token is missing."""
    client = TrainLiveClient(api_key="")
    with pytest.raises(DataSourceConfigError):
        client.fetch_departures("PAD")


@patch("app.datasources.train_live.requests.post")
def test_train_live_fetch_departures_success(mock_post: MagicMock) -> None:
    """Test fetch_departures returns departure result."""
    mock_post.return_value = MagicMock(
        status_code=200,
        text="<GetStationBoardResult>10:00 Oxford</GetStationBoardResult>",
    )
    client = TrainLiveClient(api_key="valid-key")
    res = client.fetch_departures("pad", num_rows=5)
    assert res["crs"] == "PAD"
    assert res["status"] == "success"
    assert "10:00 Oxford" in res["raw_xml"]


@patch("app.datasources.train_live.requests.post")
def test_train_live_fetch_departures_errors(mock_post: MagicMock) -> None:
    """Test fetch_departures error scenarios."""
    client = TrainLiveClient(api_key="test-key")

    # Auth error
    mock_post.return_value = MagicMock(status_code=401, text="Unauthorized")
    with pytest.raises(DataSourceAuthError):
        client.fetch_departures("PAD")

    # Other HTTP error
    mock_post.return_value = MagicMock(status_code=502, text="Bad Gateway")
    with pytest.raises(DataSourceError):
        client.fetch_departures("PAD")

    # Timeout
    mock_post.side_effect = requests.exceptions.Timeout("Timed out")
    with pytest.raises(DataSourceConnectionError):
        client.fetch_departures("PAD")

    # Connection Error
    mock_post.side_effect = requests.exceptions.ConnectionError("Refused")
    with pytest.raises(DataSourceConnectionError):
        client.fetch_departures("PAD")

    # Generic Exception
    mock_post.side_effect = RuntimeError("Crash")
    with pytest.raises(DataSourceError):
        client.fetch_departures("PAD")
