"""Unit tests for Live Train (LDBWS OpenAPI and SOAP) validation."""

from unittest.mock import MagicMock, patch
import requests

from app.validators import validate_train_live_token


def test_validate_train_live_token_empty() -> None:
    """Test Live Train API token validation with empty token."""
    valid, message = validate_train_live_token("")
    assert not valid
    assert "token is empty" in message


@patch("app.datasources.train_live.requests.get")
def test_validate_train_live_openapi_success(mock_get: MagicMock) -> None:
    """Test OpenAPI LDBWS live train validation success."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_get.return_value = mock_resp

    valid, message = validate_train_live_token("valid_token_123")
    assert valid
    assert "valid and active" in message


@patch("app.datasources.train_live.requests.get")
def test_validate_train_live_openapi_custom_endpoint(mock_get: MagicMock) -> None:
    """Test OpenAPI LDBWS validation with custom endpoint URL."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_get.return_value = mock_resp

    valid, message = validate_train_live_token(
        "valid_token_123",
        endpoint="https://custom.rail.api/LDBWS/api/20220120",
    )
    assert valid
    assert (
        mock_get.call_args[0][0]
        == "https://custom.rail.api/LDBWS/api/20220120/GetDepartureBoard/WAT"
    )


@patch("app.datasources.train_live.requests.get")
def test_validate_train_live_openapi_unauthorised(mock_get: MagicMock) -> None:
    """Test OpenAPI LDBWS live train validation unauthorised 401."""
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_get.return_value = mock_resp

    valid, message = validate_train_live_token("bad_token")
    assert not valid
    assert "Invalid train live token or unauthorised access" in message


@patch("app.datasources.train_live.requests.get")
def test_validate_train_live_openapi_not_found(mock_get: MagicMock) -> None:
    """Test OpenAPI LDBWS live train validation 404 endpoint not found."""
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_get.return_value = mock_resp

    valid, message = validate_train_live_token("some_token")
    assert not valid
    assert "OpenAPI endpoint not found (404)" in message


@patch("app.datasources.train_live.requests.get")
def test_validate_train_live_openapi_other_error(mock_get: MagicMock) -> None:
    """Test OpenAPI LDBWS live train validation unexpected status code."""
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mock_get.return_value = mock_resp

    valid, message = validate_train_live_token("some_token")
    assert not valid
    assert "unexpected status code 503" in message


@patch("app.datasources.train_live.requests.get")
def test_validate_train_live_openapi_timeout(mock_get: MagicMock) -> None:
    """Test OpenAPI LDBWS live train validation timeout."""
    mock_get.side_effect = requests.exceptions.Timeout("Timeout")

    valid, message = validate_train_live_token("some_token", timeout=2.5)
    assert not valid
    assert "timed out after 2.5s" in message


@patch("app.datasources.train_live.requests.get")
def test_validate_train_live_openapi_conn_error(mock_get: MagicMock) -> None:
    """Test OpenAPI LDBWS live train validation connection error."""
    mock_get.side_effect = requests.exceptions.ConnectionError("Refused")

    valid, message = validate_train_live_token("some_token")
    assert not valid
    assert "Network error during train live validation" in message


@patch("app.datasources.train_live.requests.get")
def test_validate_train_live_openapi_generic_exception(mock_get: MagicMock) -> None:
    """Test OpenAPI LDBWS live train validation generic exception."""
    mock_get.side_effect = RuntimeError("Fatal OpenAPI crash")

    valid, message = validate_train_live_token("some_token")
    assert not valid
    assert "Unexpected error during train live validation" in message


@patch("app.datasources.train_live.requests.post")
def test_validate_train_live_soap_success(mock_post: MagicMock) -> None:
    """Test Darwin SOAP live train validation success."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = (
        "<GetStationBoardResult><StationName>"
        "Paddington</StationName></GetStationBoardResult>"
    )
    mock_post.return_value = mock_resp

    valid, message = validate_train_live_token(
        "valid_soap_token",
        endpoint="https://lite.realtime.nationalrail.co.uk/OpenLDBWS/ldb11.asmx",
    )
    assert valid
    assert "valid and active (SOAP)" in message


@patch("app.datasources.train_live.requests.post")
def test_validate_train_live_soap_invalid_token(mock_post: MagicMock) -> None:
    """Test Darwin SOAP live train validation invalid token response body."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<faultstring>Invalid token value or unauthorised</faultstring>"
    mock_post.return_value = mock_resp

    valid, message = validate_train_live_token(
        "invalid_soap_token",
        endpoint="https://lite.realtime.nationalrail.co.uk/OpenLDBWS/ldb11.asmx",
    )
    assert not valid
    assert "Invalid train live token (SOAP authentication failed)" in message


@patch("app.datasources.train_live.requests.post")
def test_validate_train_live_soap_other_status(mock_post: MagicMock) -> None:
    """Test Darwin SOAP live train validation unexpected status code."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"
    mock_post.return_value = mock_resp

    valid, message = validate_train_live_token(
        "bad_token",
        endpoint="https://lite.realtime.nationalrail.co.uk/OpenLDBWS/ldb11.asmx",
    )
    assert not valid
    assert "unexpected status code 500" in message


@patch("app.datasources.train_live.requests.post")
def test_validate_train_live_soap_timeout(mock_post: MagicMock) -> None:
    """Test Darwin SOAP live train validation timeout."""
    mock_post.side_effect = requests.exceptions.Timeout("SOAP Timeout")

    valid, message = validate_train_live_token(
        "token",
        endpoint="https://lite.realtime.nationalrail.co.uk/OpenLDBWS/ldb11.asmx",
        timeout=1.5,
    )
    assert not valid
    assert "timed out after 1.5s" in message


@patch("app.datasources.train_live.requests.post")
def test_validate_train_live_soap_conn_error(mock_post: MagicMock) -> None:
    """Test Darwin SOAP live train validation network error."""
    mock_post.side_effect = requests.exceptions.ConnectionError(
        "SOAP Connection refused"
    )

    valid, message = validate_train_live_token(
        "token",
        endpoint="https://lite.realtime.nationalrail.co.uk/OpenLDBWS/ldb11.asmx",
    )
    assert not valid
    assert "Network error during train live SOAP validation" in message
