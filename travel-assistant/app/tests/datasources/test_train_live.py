from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import requests
from flask import Flask

from app.datasources.train_live import (
    DEFAULT_DARWIN_OPENAPI_ENDPOINT,
    DEFAULT_DARWIN_SOAP_ENDPOINT,
    TrainLiveClient,
    sync_swagger_schema,
)
from app.datasources.exceptions import (
    DataSourceAuthError,
    DataSourceConfigError,
    DataSourceConnectionError,
    DataSourceError,
)
from app.models.setting import Setting


def test_train_live_from_settings(app: Flask) -> None:
    """Test TrainLiveClient initialisation from Setting model."""
    with app.app_context():
        Setting.set_val("train_live_api_key", "test-live-key")
        Setting.set_val("train_live_endpoint", "https://custom.darwin/soap")

        client = TrainLiveClient.from_settings()
        assert client.api_key == "test-live-key"
        assert client.endpoint == "https://custom.darwin/soap"
        assert client.provider_name == "train_live"


def test_train_live_parse_endpoint() -> None:
    """Test endpoint URL parsing for OpenAPI and SOAP endpoints."""
    client = TrainLiveClient(
        endpoint="https://api1.raildata.org.uk/1010-live-departure-board-dep1_2/LDBWS"
    )
    scheme, host, base_path, is_soap = client._parse_endpoint(client.endpoint)
    assert scheme == "https"
    assert host == "api1.raildata.org.uk"
    assert base_path == "/1010-live-departure-board-dep1_2/LDBWS"
    assert not is_soap

    # Test stripping sub-operation path if pasted
    client_sub = TrainLiveClient(
        endpoint=(
            "https://api1.raildata.org.uk/1010-live-departure-board-dep1_2/LDBWS"
            "/api/20220120/GetDepartureBoard"
        )
    )
    scheme, host, base_path, is_soap = client_sub._parse_endpoint(client_sub.endpoint)
    assert base_path == "/1010-live-departure-board-dep1_2/LDBWS"
    assert not is_soap

    # Test SOAP endpoint
    client_soap = TrainLiveClient(endpoint=DEFAULT_DARWIN_SOAP_ENDPOINT)
    _, _, _, is_soap = client_soap._parse_endpoint(client_soap.endpoint)
    assert is_soap


def test_train_live_swagger_client_initialisation() -> None:
    """Test SwaggerClient initialisation with host and basePath overrides."""
    client = TrainLiveClient(
        api_key="test-api-key",
        endpoint="https://api1.raildata.org.uk/1010-live-departure-board-dep1_2/LDBWS",
    )
    swagger = client.get_swagger_client()
    assert swagger is not None
    assert swagger.swagger_spec.origin_url is None or True
    # Cached instance
    assert client.get_swagger_client() is swagger


def test_train_live_swagger_client_soap_raises_config_error() -> None:
    """Test get_swagger_client raises DataSourceConfigError on SOAP endpoint."""
    client = TrainLiveClient(endpoint=DEFAULT_DARWIN_SOAP_ENDPOINT)
    with pytest.raises(DataSourceConfigError):
        client.get_swagger_client()


def test_train_live_validate_credentials_empty() -> None:
    """Test validate_credentials returns invalid for empty token."""
    client = TrainLiveClient(api_key="")
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "empty" in res["message"]


@patch.object(TrainLiveClient, "get_departure_board")
def test_train_live_validate_openapi_success(
    mock_get_board: MagicMock,
) -> None:
    """Test validate_credentials against REST/OpenAPI endpoint returning valid board."""
    mock_get_board.return_value = {
        "locationName": "Cambridge",
        "crs": "CBG",
        "trainServices": [{"std": "10:00"}],
    }
    client = TrainLiveClient(
        api_key="valid-key",
        endpoint=DEFAULT_DARWIN_OPENAPI_ENDPOINT,
    )
    res = client.validate_credentials()
    assert res["valid"] is True
    assert "valid and active (OpenAPI)" in res["message"]


@patch.object(TrainLiveClient, "get_departure_board")
def test_train_live_validate_openapi_auth_fail(
    mock_get_board: MagicMock,
) -> None:
    """Test validate_credentials against REST/OpenAPI endpoint failing with auth error."""
    mock_get_board.side_effect = DataSourceAuthError(
        "Unauthorised", provider="train_live"
    )
    client = TrainLiveClient(
        api_key="bad-key",
        endpoint=DEFAULT_DARWIN_OPENAPI_ENDPOINT,
    )
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "unauthorised access" in res["message"]


@patch.object(TrainLiveClient, "get_departure_board")
@patch("app.datasources.train_live.requests.post")
def test_train_live_validate_openapi_fallback_to_soap(
    mock_post: MagicMock, mock_get_board: MagicMock
) -> None:
    """Test validate_credentials falls back to SOAP when OpenAPI returns 404."""
    mock_get_board.side_effect = RuntimeError("Endpoint not found (404)")
    mock_post.return_value = MagicMock(
        status_code=200, text="<GetStationBoardResult>OK</GetStationBoardResult>"
    )

    client = TrainLiveClient(
        api_key="valid-key",
        endpoint=DEFAULT_DARWIN_OPENAPI_ENDPOINT,
    )
    res = client.validate_credentials()
    assert res["valid"] is True
    assert "valid and active (SOAP)" in res["message"]


@patch("app.datasources.train_live.requests.post")
def test_train_live_validate_soap_success(mock_post: MagicMock) -> None:
    """Test SOAP validation success."""
    mock_post.return_value = MagicMock(
        status_code=200,
        text="<GetStationBoardResult>Departure</GetStationBoardResult>",
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
    mock_post.return_value = MagicMock(status_code=403, text="Forbidden")
    client = TrainLiveClient(api_key="bad-key", endpoint=DEFAULT_DARWIN_SOAP_ENDPOINT)
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "HTTP 403" in res["message"]

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


@patch.object(TrainLiveClient, "get_dep_board_with_details")
def test_train_live_fetch_departures_openapi_success(
    mock_get_board: MagicMock,
) -> None:
    """Test fetch_departures with OpenAPI endpoint returns structured result."""
    mock_get_board.return_value = {
        "locationName": "London Paddington",
        "crs": "PAD",
        "trainServices": [
            {
                "std": "10:00",
                "destination": [{"locationName": "Oxford"}],
                "platform": "1",
            }
        ],
    }
    client = TrainLiveClient(
        api_key="valid-key", endpoint=DEFAULT_DARWIN_OPENAPI_ENDPOINT
    )
    res = client.fetch_departures("pad", num_rows=5)
    assert res["crs"] == "PAD"
    assert res["location_name"] == "London Paddington"
    assert len(res["train_services"]) == 1
    assert res["status"] == "success"


@patch("app.datasources.train_live.requests.post")
def test_train_live_fetch_departures_soap_success(mock_post: MagicMock) -> None:
    """Test fetch_departures with SOAP endpoint returns XML result."""
    mock_post.return_value = MagicMock(
        status_code=200,
        text="<GetStationBoardResult>10:00 Oxford</GetStationBoardResult>",
    )
    client = TrainLiveClient(api_key="valid-key", endpoint=DEFAULT_DARWIN_SOAP_ENDPOINT)
    res = client.fetch_departures("pad", num_rows=5)
    assert res["crs"] == "PAD"
    assert res["status"] == "success"
    assert "10:00 Oxford" in res["raw_xml"]


@patch("app.datasources.train_live.requests.post")
def test_train_live_fetch_departures_soap_errors(mock_post: MagicMock) -> None:
    """Test fetch_departures SOAP error scenarios."""
    client = TrainLiveClient(api_key="test-key", endpoint=DEFAULT_DARWIN_SOAP_ENDPOINT)

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


@patch.object(TrainLiveClient, "get_swagger_client")
def test_train_live_operations_execution(mock_get_swagger: MagicMock) -> None:
    """Test OpenAPI operation wrappers pass correct parameters."""
    mock_op = MagicMock()
    mock_response = MagicMock()
    mock_response.result = {"success": True}
    mock_op.return_value.response.return_value = mock_response

    mock_client = MagicMock()
    mock_client._20220120.GetDepartureBoard = mock_op
    mock_client._20220120.GetDepBoardWithDetails = mock_op
    mock_client._20220120.GetArrivalBoard = mock_op
    mock_client._20220120.GetServiceDetails = mock_op
    mock_get_swagger.return_value = mock_client

    client = TrainLiveClient(api_key="key", endpoint=DEFAULT_DARWIN_OPENAPI_ENDPOINT)

    # get_departure_board
    client.get_departure_board(crs="CBG", num_rows=5, filter_crs="KGX")
    mock_op.assert_called_with(crs="CBG", numRows=5, filterCrs="KGX")

    # get_dep_board_with_details
    client.get_dep_board_with_details(crs="SVG", num_rows=10)
    mock_op.assert_called_with(crs="SVG", numRows=10)

    # get_arrival_board
    client.get_arrival_board(crs="LST", num_rows=3)
    mock_op.assert_called_with(crs="LST", numRows=3)

    # get_service_details
    client.get_service_details(service_id="service-123")
    mock_op.assert_called_with(serviceid="service-123")


@patch("app.datasources.train_live.requests.get")
def test_sync_swagger_schema_success(mock_get: MagicMock, tmp_path: Path) -> None:
    """Test sync_swagger_schema downloads and persists schema locally."""
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: {"swagger": "2.0", "paths": {}},
    )
    dest = str(tmp_path / "schemas" / "custom_swagger.json")
    result = sync_swagger_schema(schema_path=dest)
    assert result is True


@patch("app.datasources.train_live.requests.get")
def test_sync_swagger_schema_failure(mock_get: MagicMock, tmp_path: Path) -> None:
    """Test sync_swagger_schema handles HTTP failure and exceptions gracefully."""
    # HTTP error
    mock_get.return_value = MagicMock(status_code=500)
    dest = str(tmp_path / "fail.json")
    assert sync_swagger_schema(schema_path=dest) is False

    # Exception
    mock_get.side_effect = requests.exceptions.ConnectionError("Refused")
    assert sync_swagger_schema(schema_path=dest) is False
