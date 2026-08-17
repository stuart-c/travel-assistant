from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
import pytest
import requests
from flask import Flask

from app.datasources.train_live import (
    TrainLiveClient,
    get_schema_path,
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
        Setting.set_val("train_live_endpoint", "https://example.com/darwin/ldbws")

        client = TrainLiveClient.from_settings()
        assert client.api_key == "test-live-key"
        assert client.endpoint == "https://example.com/darwin/ldbws"
        assert client.provider_name == "train_live"


def test_train_live_parse_endpoint() -> None:
    """Test endpoint URL parsing for OpenAPI endpoints and empty/default endpoints."""
    # Empty endpoint
    client_empty = TrainLiveClient()
    scheme, host, base_path = client_empty._parse_endpoint(client_empty.endpoint)
    assert scheme == ""
    assert host == ""
    assert base_path == ""

    # Custom endpoint
    client = TrainLiveClient(endpoint="https://example.com/custom-live-board/LDBWS")
    scheme, host, base_path = client._parse_endpoint(client.endpoint)
    assert scheme == "https"
    assert host == "example.com"
    assert base_path == "/custom-live-board/LDBWS"

    # Test stripping sub-operation path if pasted
    client_sub = TrainLiveClient(
        endpoint=(
            "https://example.com/custom-live-board/LDBWS"
            "/api/20220120/GetDepartureBoard"
        )
    )
    scheme, host, base_path = client_sub._parse_endpoint(client_sub.endpoint)
    assert base_path == "/custom-live-board/LDBWS"


@patch("app.datasources.train_live.os.path.exists", return_value=True)
@patch("app.datasources.train_live.open")
@patch("app.datasources.train_live.SwaggerClient.from_spec")
def test_train_live_swagger_client_initialisation(
    mock_from_spec: MagicMock, mock_open_file: MagicMock, mock_exists: MagicMock
) -> None:
    """Test SwaggerClient initialisation with host and basePath overrides."""
    mock_swagger_inst = MagicMock()
    mock_from_spec.return_value = mock_swagger_inst
    mock_open_file.return_value.__enter__.return_value.read.return_value = (
        '{"swagger": "2.0", "paths": {}}'
    )

    # Test with custom endpoint override
    client = TrainLiveClient(
        api_key="test-api-key",
        endpoint="https://example.com/custom-live-board/LDBWS",
    )
    swagger = client.get_swagger_client()
    assert swagger is mock_swagger_inst
    mock_from_spec.assert_called_once()
    assert client.get_swagger_client() is swagger

    # Test with default schema endpoint (no override)
    mock_from_spec.reset_mock()
    client_default = TrainLiveClient(api_key="test-api-key")
    swagger_def = client_default.get_swagger_client()
    assert swagger_def is mock_swagger_inst
    mock_from_spec.assert_called_once()


@patch("app.datasources.train_live.os.path.exists", return_value=False)
@patch("app.datasources.train_live.sync_swagger_schema", return_value=False)
def test_train_live_swagger_client_missing_schema_raises_config_error(
    mock_sync: MagicMock, mock_exists: MagicMock
) -> None:
    """Test get_swagger_client raises error if schema cannot be found or downloaded."""
    client = TrainLiveClient()
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
    client = TrainLiveClient(api_key="valid-key")
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
    client = TrainLiveClient(api_key="bad-key")
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "unauthorised access" in res["message"]


@patch.object(TrainLiveClient, "get_departure_board")
def test_train_live_validate_openapi_errors(mock_get_board: MagicMock) -> None:
    """Test validate_credentials handles timeout, connection errors, 404, and exceptions."""
    client = TrainLiveClient(api_key="test-key")

    # Timeout
    mock_get_board.side_effect = DataSourceConnectionError(
        "Request timed out", provider="train_live"
    )
    res_t = client.validate_credentials()
    assert res_t["valid"] is False
    assert "timed out" in res_t["message"]

    # Connection / Network error
    mock_get_board.side_effect = DataSourceConnectionError(
        "Network unreachable", provider="train_live"
    )
    res_c = client.validate_credentials()
    assert res_c["valid"] is False
    assert "Network error" in res_c["message"]

    # 404 error
    mock_get_board.side_effect = RuntimeError("Endpoint not found (404)")
    res_404 = client.validate_credentials()
    assert res_404["valid"] is False
    assert "HTTP 404" in res_404["message"]

    # Generic unexpected error
    mock_get_board.side_effect = RuntimeError("Crash")
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
    client = TrainLiveClient(api_key="valid-key")
    res = client.fetch_departures("pad", num_rows=5)
    assert res["crs"] == "PAD"
    assert res["location_name"] == "London Paddington"
    assert len(res["train_services"]) == 1
    assert res["status"] == "success"


@patch.object(TrainLiveClient, "get_dep_board_with_details")
def test_train_live_fetch_departures_errors(mock_get_board: MagicMock) -> None:
    """Test fetch_departures propagates errors correctly."""
    client = TrainLiveClient(api_key="test-key")

    # Auth error
    mock_get_board.side_effect = DataSourceAuthError(
        "Invalid token", provider="train_live"
    )
    with pytest.raises(DataSourceAuthError):
        client.fetch_departures("PAD")

    # Generic exception wrapped in DataSourceError
    mock_get_board.side_effect = RuntimeError("Service failure")
    with pytest.raises(DataSourceError):
        client.fetch_departures("PAD")


@patch.object(TrainLiveClient, "get_swagger_client")
def test_train_live_operations_execution(mock_get_swagger: MagicMock) -> None:
    """Test OpenAPI operation wrappers pass correct parameters."""
    mock_op = MagicMock()
    mock_response = MagicMock()
    mock_response.result = {"success": True}
    mock_op.return_value.response.return_value = mock_response

    class FakeNamespace:
        def __init__(self, op: Any) -> None:
            self.GetDepartureBoard = op
            self.GetDepBoardWithDetails = op
            self.GetArrivalBoard = op
            self.GetServiceDetails = op
            self.GetFastestDepartures = op

    class FakeClient:
        def __init__(self, op: Any) -> None:
            self._20220120 = FakeNamespace(op)

    mock_get_swagger.return_value = FakeClient(mock_op)

    client = TrainLiveClient(api_key="key")

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

    # get_fastest_departures
    client.get_fastest_departures(crs="CBG", filter_list="KGX")
    mock_op.assert_called_with(crs="CBG", filterList="KGX")


@patch.object(TrainLiveClient, "get_swagger_client")
def test_train_live_call_operation_errors(mock_get_swagger: MagicMock) -> None:
    """Test error handling in _call_operation across HTTP, timeout, and network errors."""

    class FakeClient:
        pass

    fake_client = FakeClient()
    mock_get_swagger.return_value = fake_client
    client = TrainLiveClient(api_key="key")

    # Missing operation
    with pytest.raises(DataSourceConfigError):
        client._call_operation("NonExistentOperation")

    # Mock operation raising errors
    mock_op = MagicMock()
    fake_client.TestOp = mock_op

    # Timeout
    mock_op.return_value.response.side_effect = requests.exceptions.Timeout("Timeout")
    with pytest.raises(DataSourceConnectionError):
        client._call_operation("TestOp")

    # HTTP 401
    resp_401 = MagicMock(status_code=401, text="Unauthorised")
    req_err_401 = requests.exceptions.RequestException(response=resp_401)
    mock_op.return_value.response.side_effect = req_err_401
    with pytest.raises(DataSourceAuthError):
        client._call_operation("TestOp")

    # HTTP 500
    resp_500 = MagicMock(status_code=500, text="Server Error")
    req_err_500 = requests.exceptions.RequestException(response=resp_500)
    mock_op.return_value.response.side_effect = req_err_500
    with pytest.raises(DataSourceError):
        client._call_operation("TestOp")

    # Network Error
    req_err_net = requests.exceptions.RequestException(response=None)
    mock_op.return_value.response.side_effect = req_err_net
    with pytest.raises(DataSourceConnectionError):
        client._call_operation("TestOp")

    # Generic 403 in message
    mock_op.return_value.response.side_effect = RuntimeError("HTTP 403 Forbidden")
    with pytest.raises(DataSourceAuthError):
        client._call_operation("TestOp")

    # Generic Timeout in message
    mock_op.return_value.response.side_effect = RuntimeError("timed out")
    with pytest.raises(DataSourceConnectionError):
        client._call_operation("TestOp")

    # Generic Other Exception
    mock_op.return_value.response.side_effect = RuntimeError("Unknown error")
    with pytest.raises(DataSourceError):
        client._call_operation("TestOp")


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


def test_get_schema_path_db_dir() -> None:
    """Test get_schema_path colocates schema in database directory."""
    with patch("app.db.core.get_db_path", return_value="/var/data/custom/test.db"):
        path = get_schema_path("ldbws_swagger.json")
        assert path == "/var/data/custom/ldbws_swagger.json"


def test_get_schema_path_ha_data_fallback() -> None:
    """Test get_schema_path uses /data if available when db is in-memory."""
    with patch("app.db.core.get_db_path", return_value=":memory:"):
        with patch("os.path.exists", side_effect=lambda p: p == "/data"):
            with patch("os.access", return_value=True):
                path = get_schema_path()
                assert path == "/data/ldbws_swagger.json"


def test_get_schema_path_instance_fallback() -> None:
    """Test get_schema_path falls back to instance directory."""
    with patch("app.db.core.get_db_path", return_value=":memory:"):
        with patch("os.path.exists", return_value=False):
            path = get_schema_path()
            assert path.endswith("instance/ldbws_swagger.json")
