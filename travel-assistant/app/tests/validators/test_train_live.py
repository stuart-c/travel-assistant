"""Unit tests for Live Train (LDBWS OpenAPI and SOAP) validation."""

from unittest.mock import MagicMock, patch
import requests

from app.validators import validate_train_live_token


def test_validate_train_live_token_empty() -> None:
    """Test Live Train API token validation with empty token."""
    valid, message = validate_train_live_token("")
    assert not valid
    assert "token is empty" in message


@patch("app.validators.train_live.requests.get")
def test_validate_train_live_openapi_success(mock_get: MagicMock) -> None:
    """Test OpenAPI LDBWS live train validation success."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_get.return_value = mock_resp

    valid, message = validate_train_live_token("valid_token_123")
    assert valid
    assert "valid and active" in message


@patch("app.validators.train_live.requests.get")
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


@patch("app.validators.train_live.requests.get")
def test_validate_train_live_openapi_unauthorised(mock_get: MagicMock) -> None:
    """Test OpenAPI LDBWS live train validation unauthorised 401."""
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_get.return_value = mock_resp

    valid, message = validate_train_live_token("bad_token")
    assert not valid
    assert "Invalid train live token or unauthorised access" in message


@patch("app.validators.train_live.requests.get")
def test_validate_train_live_openapi_not_found(mock_get: MagicMock) -> None:
    """Test OpenAPI LDBWS live train validation 404 endpoint not found."""
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_get.return_value = mock_resp

    valid, message = validate_train_live_token("token_404")
    assert not valid
    assert "endpoint not found (404)" in message


@patch("app.validators.train_live.requests.get")
def test_validate_train_live_openapi_other_error(mock_get: MagicMock) -> None:
    """Test OpenAPI LDBWS live train validation other status code error."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal error on upstream server"
    mock_get.return_value = mock_resp

    valid, message = validate_train_live_token("token_500")
    assert not valid
    assert "Train live API error (500)" in message


@patch("app.validators.train_live.requests.get")
def test_validate_train_live_openapi_timeout(mock_get: MagicMock) -> None:
    """Test OpenAPI LDBWS live train validation timeout."""
    mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")

    valid, message = validate_train_live_token("token_timeout")
    assert not valid
    assert "timed out" in message.lower()


@patch("app.validators.train_live.requests.get")
def test_validate_train_live_openapi_conn_error(mock_get: MagicMock) -> None:
    """Test OpenAPI LDBWS live train validation connection error."""
    mock_get.side_effect = requests.exceptions.ConnectionError("Failed connection")

    valid, message = validate_train_live_token("token_conn_err")
    assert not valid
    assert "Unable to connect to Live Train API" in message


@patch("app.validators.train_live.requests.get")
def test_validate_train_live_openapi_generic_exception(mock_get: MagicMock) -> None:
    """Test OpenAPI LDBWS live train validation generic exception."""
    mock_get.side_effect = RuntimeError("Unexpected runtime failure")

    valid, message = validate_train_live_token("token_generic_err")
    assert not valid
    assert "Train live validation error" in message


@patch("app.validators.train_live.requests.post")
def test_validate_train_live_soap_success(mock_post: MagicMock) -> None:
    """Test SOAP OpenLDBWS live train validation success."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<GetStationBoardResult>...</GetStationBoardResult>"
    mock_post.return_value = mock_resp

    valid, message = validate_train_live_token(
        "valid_soap_token",
        endpoint="https://lite.realtime.nationalrail.co.uk/OpenLDBWS/ldb11.asmx",
    )
    assert valid
    assert "valid and active" in message


@patch("app.validators.train_live.requests.post")
def test_validate_train_live_soap_invalid_token(mock_post: MagicMock) -> None:
    """Test SOAP OpenLDBWS live train validation with invalid token."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "<soap:Fault><faultstring>Invalid Token</faultstring></soap:Fault>"
    mock_post.return_value = mock_resp

    valid, message = validate_train_live_token(
        "bad_soap_token",
        endpoint="https://lite.realtime.nationalrail.co.uk/OpenLDBWS/ldb11.asmx",
    )
    assert not valid
    assert "Invalid train live token or unauthorised access" in message


@patch("app.validators.train_live.requests.post")
def test_validate_train_live_soap_other_status(mock_post: MagicMock) -> None:
    """Test SOAP OpenLDBWS live train validation status code error."""
    mock_resp = MagicMock()
    mock_resp.status_code = 502
    mock_resp.text = "Bad Gateway"
    mock_post.return_value = mock_resp

    valid, message = validate_train_live_token(
        "soap_token_502",
        endpoint="https://lite.realtime.nationalrail.co.uk/OpenLDBWS/ldb11.asmx",
    )
    assert not valid
    assert "status 502" in message


@patch("app.validators.train_live.requests.post")
def test_validate_train_live_soap_timeout(mock_post: MagicMock) -> None:
    """Test SOAP OpenLDBWS live train validation timeout."""
    mock_post.side_effect = requests.exceptions.Timeout("Timeout")

    valid, message = validate_train_live_token(
        "soap_token",
        endpoint="https://lite.realtime.nationalrail.co.uk/OpenLDBWS/ldb11.asmx",
    )
    assert not valid
    assert "timed out" in message.lower()


@patch("app.validators.train_live.requests.post")
def test_validate_train_live_soap_conn_error(mock_post: MagicMock) -> None:
    """Test SOAP OpenLDBWS live train validation connection error."""
    mock_post.side_effect = requests.exceptions.ConnectionError("Conn failed")

    valid, message = validate_train_live_token(
        "soap_token",
        endpoint="https://lite.realtime.nationalrail.co.uk/OpenLDBWS/ldb11.asmx",
    )
    assert not valid
    assert "Unable to connect to train live service" in message
