"""Unit tests for credential validation services."""

from unittest.mock import MagicMock, patch
import requests
from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    BotoCoreError,
)
from openai import (
    AuthenticationError as OpenAIAuthError,
    APIConnectionError as OpenAIConnError,
    APITimeoutError as OpenAITimeoutError,
    APIError as OpenAIError,
)

from app.validators import (
    validate_bus_api_key,
    validate_train_s3_bucket,
    validate_train_live_token,
    validate_open_api_key,
    validate_service_credentials,
)

# --- Bus API Validation Tests ---


def test_validate_bus_api_key_empty() -> None:
    """Test Bus API validation with empty key."""
    valid, message = validate_bus_api_key("")
    assert not valid
    assert "Bus API key is empty" in message

    valid, message = validate_bus_api_key("   ")
    assert not valid
    assert "Bus API key is empty" in message


@patch("app.validators.requests.get")
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


@patch("app.validators.requests.get")
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


@patch("app.validators.requests.get")
def test_validate_bus_api_key_unauthorised(mock_get: MagicMock) -> None:
    """Test Bus API validation with 401/403 error."""
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_get.return_value = mock_resp

    valid, message = validate_bus_api_key("invalid_token")
    assert not valid
    assert "Invalid Bus API key or unauthorised access" in message

    mock_resp.status_code = 403
    valid, message = validate_bus_api_key("forbidden_token")
    assert not valid
    assert "Invalid Bus API key or unauthorised access" in message


@patch("app.validators.requests.get")
def test_validate_bus_api_key_other_api_error(mock_get: MagicMock) -> None:
    """Test Bus API validation with other API error code."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"
    mock_get.return_value = mock_resp

    valid, message = validate_bus_api_key("some_token")
    assert not valid
    assert "Bus API error (500)" in message


@patch("app.validators.requests.get")
def test_validate_bus_api_key_timeout(mock_get: MagicMock) -> None:
    """Test Bus API validation timeout exception."""
    mock_get.side_effect = requests.exceptions.Timeout("Timed out")

    valid, message = validate_bus_api_key("token_timeout")
    assert not valid
    assert "timed out" in message.lower()


@patch("app.validators.requests.get")
def test_validate_bus_api_key_request_exception(mock_get: MagicMock) -> None:
    """Test Bus API validation request connection error."""
    mock_get.side_effect = requests.exceptions.ConnectionError("Failed to connect")

    valid, message = validate_bus_api_key("token_conn_err")
    assert not valid
    assert "Unable to connect to Bus Open Data Service" in message


@patch("app.validators.requests.get")
def test_validate_bus_api_key_generic_exception(mock_get: MagicMock) -> None:
    """Test Bus API validation generic unexpected exception."""
    mock_get.side_effect = RuntimeError("Unexpected error")

    valid, message = validate_bus_api_key("token_generic_err")
    assert not valid
    assert "Bus validation error" in message


# --- Train S3 Bucket Validation Tests ---


def test_validate_train_s3_bucket_empty() -> None:
    """Test S3 bucket validation with empty bucket name."""
    valid, message = validate_train_s3_bucket("")
    assert not valid
    assert "bucket name is required" in message


@patch("app.validators.boto3.Session")
def test_validate_train_s3_bucket_success(mock_session_cls: MagicMock) -> None:
    """Test S3 bucket validation success."""
    mock_client = MagicMock()
    mock_session = MagicMock()
    mock_session.client.return_value = mock_client
    mock_session_cls.return_value = mock_session

    valid, message = validate_train_s3_bucket(
        "my-bucket",
        region="eu-west-2",
        access_key="AKIA123",
        secret_key="SECRET456",
    )
    assert valid
    assert "valid and accessible" in message
    mock_client.head_bucket.assert_called_once_with(Bucket="my-bucket")


@patch("app.validators.boto3.Session")
def test_validate_train_s3_bucket_not_found(mock_session_cls: MagicMock) -> None:
    """Test S3 bucket validation with 404 NoSuchBucket error."""
    mock_client = MagicMock()
    error_response = {"Error": {"Code": "404", "Message": "Not Found"}}
    mock_client.head_bucket.side_effect = ClientError(error_response, "head_bucket")
    mock_session = MagicMock()
    mock_session.client.return_value = mock_client
    mock_session_cls.return_value = mock_session

    valid, message = validate_train_s3_bucket("nonexistent-bucket")
    assert not valid
    assert "does not exist (404)" in message


@patch("app.validators.boto3.Session")
def test_validate_train_s3_bucket_access_denied(mock_session_cls: MagicMock) -> None:
    """Test S3 bucket validation with 403 AccessDenied error."""
    mock_client = MagicMock()
    error_response = {"Error": {"Code": "AccessDenied", "Message": "Forbidden"}}
    mock_client.head_bucket.side_effect = ClientError(error_response, "head_bucket")
    mock_session = MagicMock()
    mock_session.client.return_value = mock_client
    mock_session_cls.return_value = mock_session

    valid, message = validate_train_s3_bucket("private-bucket")
    assert not valid
    assert "Access denied" in message
    assert "403" in message


@patch("app.validators.boto3.Session")
def test_validate_train_s3_bucket_redirect(mock_session_cls: MagicMock) -> None:
    """Test S3 bucket validation with 301 PermanentRedirect error."""
    mock_client = MagicMock()
    error_response = {"Error": {"Code": "301", "Message": "Moved"}}
    mock_client.head_bucket.side_effect = ClientError(error_response, "head_bucket")
    mock_session = MagicMock()
    mock_session.client.return_value = mock_client
    mock_session_cls.return_value = mock_session

    valid, message = validate_train_s3_bucket("other-region-bucket")
    assert not valid
    assert "exists in a different region" in message


@patch("app.validators.boto3.Session")
def test_validate_train_s3_bucket_other_client_error(
    mock_session_cls: MagicMock,
) -> None:
    """Test S3 bucket validation with generic ClientError."""
    mock_client = MagicMock()
    error_response = {"Error": {"Code": "500", "Message": "Internal S3 Error"}}
    mock_client.head_bucket.side_effect = ClientError(error_response, "head_bucket")
    mock_session = MagicMock()
    mock_session.client.return_value = mock_client
    mock_session_cls.return_value = mock_session

    valid, message = validate_train_s3_bucket("error-bucket")
    assert not valid
    assert "S3 bucket error (500)" in message


@patch("app.validators.boto3.Session")
def test_validate_train_s3_bucket_timeout(mock_session_cls: MagicMock) -> None:
    """Test S3 bucket validation connection timeout."""
    mock_client = MagicMock()
    mock_client.head_bucket.side_effect = ConnectTimeoutError(
        endpoint_url="https://s3.eu-west-2.amazonaws.com"
    )
    mock_session = MagicMock()
    mock_session.client.return_value = mock_client
    mock_session_cls.return_value = mock_session

    valid, message = validate_train_s3_bucket("timeout-bucket")
    assert not valid
    assert "Connection timed out" in message


@patch("app.validators.boto3.Session")
def test_validate_train_s3_bucket_endpoint_conn_error(
    mock_session_cls: MagicMock,
) -> None:
    """Test S3 bucket validation endpoint connection error."""
    mock_client = MagicMock()
    mock_client.head_bucket.side_effect = EndpointConnectionError(
        endpoint_url="https://s3.eu-west-2.amazonaws.com"
    )
    mock_session = MagicMock()
    mock_session.client.return_value = mock_client
    mock_session_cls.return_value = mock_session

    valid, message = validate_train_s3_bucket("unreachable-bucket")
    assert not valid
    assert "Unable to connect to AWS S3 endpoint" in message


@patch("app.validators.boto3.Session")
def test_validate_train_s3_bucket_botocore_error(mock_session_cls: MagicMock) -> None:
    """Test S3 bucket validation BotoCoreError."""
    mock_client = MagicMock()
    mock_client.head_bucket.side_effect = BotoCoreError()
    mock_session = MagicMock()
    mock_session.client.return_value = mock_client
    mock_session_cls.return_value = mock_session

    valid, message = validate_train_s3_bucket("botocore-err-bucket")
    assert not valid
    assert "AWS S3 error" in message


@patch("app.validators.boto3.Session")
def test_validate_train_s3_bucket_generic_error(mock_session_cls: MagicMock) -> None:
    """Test S3 bucket validation generic error."""
    mock_session_cls.side_effect = RuntimeError("Session init failure")

    valid, message = validate_train_s3_bucket("generic-err-bucket")
    assert not valid
    assert "S3 validation error" in message


# --- Train Live Token Validation Tests ---


def test_validate_train_live_token_empty() -> None:
    """Test Live Train API token validation with empty token."""
    valid, message = validate_train_live_token("")
    assert not valid
    assert "token is empty" in message


@patch("app.validators.requests.get")
def test_validate_train_live_openapi_success(mock_get: MagicMock) -> None:
    """Test OpenAPI LDBWS live train validation success."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_get.return_value = mock_resp

    valid, message = validate_train_live_token("valid_token_123")
    assert valid
    assert "valid and active" in message


@patch("app.validators.requests.get")
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


@patch("app.validators.requests.get")
def test_validate_train_live_openapi_unauthorised(mock_get: MagicMock) -> None:
    """Test OpenAPI LDBWS live train validation unauthorised 401."""
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_get.return_value = mock_resp

    valid, message = validate_train_live_token("bad_token")
    assert not valid
    assert "Invalid train live token or unauthorised access" in message


@patch("app.validators.requests.get")
def test_validate_train_live_openapi_not_found(mock_get: MagicMock) -> None:
    """Test OpenAPI LDBWS live train validation 404 endpoint not found."""
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_get.return_value = mock_resp

    valid, message = validate_train_live_token("token_404")
    assert not valid
    assert "endpoint not found (404)" in message


@patch("app.validators.requests.get")
def test_validate_train_live_openapi_other_error(mock_get: MagicMock) -> None:
    """Test OpenAPI LDBWS live train validation other status code error."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal error on upstream server"
    mock_get.return_value = mock_resp

    valid, message = validate_train_live_token("token_500")
    assert not valid
    assert "Train live API error (500)" in message


@patch("app.validators.requests.get")
def test_validate_train_live_openapi_timeout(mock_get: MagicMock) -> None:
    """Test OpenAPI LDBWS live train validation timeout."""
    mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")

    valid, message = validate_train_live_token("token_timeout")
    assert not valid
    assert "timed out" in message.lower()


@patch("app.validators.requests.get")
def test_validate_train_live_openapi_conn_error(mock_get: MagicMock) -> None:
    """Test OpenAPI LDBWS live train validation connection error."""
    mock_get.side_effect = requests.exceptions.ConnectionError("Failed connection")

    valid, message = validate_train_live_token("token_conn_err")
    assert not valid
    assert "Unable to connect to Live Train API" in message


@patch("app.validators.requests.get")
def test_validate_train_live_openapi_generic_exception(mock_get: MagicMock) -> None:
    """Test OpenAPI LDBWS live train validation generic exception."""
    mock_get.side_effect = RuntimeError("Unexpected runtime failure")

    valid, message = validate_train_live_token("token_generic_err")
    assert not valid
    assert "Train live validation error" in message


@patch("app.validators.requests.post")
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


@patch("app.validators.requests.post")
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


@patch("app.validators.requests.post")
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


@patch("app.validators.requests.post")
def test_validate_train_live_soap_timeout(mock_post: MagicMock) -> None:
    """Test SOAP OpenLDBWS live train validation timeout."""
    mock_post.side_effect = requests.exceptions.Timeout("Timeout")

    valid, message = validate_train_live_token(
        "soap_token",
        endpoint="https://lite.realtime.nationalrail.co.uk/OpenLDBWS/ldb11.asmx",
    )
    assert not valid
    assert "timed out" in message.lower()


@patch("app.validators.requests.post")
def test_validate_train_live_soap_conn_error(mock_post: MagicMock) -> None:
    """Test SOAP OpenLDBWS live train validation connection error."""
    mock_post.side_effect = requests.exceptions.ConnectionError("Conn failed")

    valid, message = validate_train_live_token(
        "soap_token",
        endpoint="https://lite.realtime.nationalrail.co.uk/OpenLDBWS/ldb11.asmx",
    )
    assert not valid
    assert "Unable to connect to train live service" in message


# --- Open API Validation Tests ---


def test_validate_open_api_key_empty() -> None:
    """Test Open API validation with empty key."""
    valid, message = validate_open_api_key("")
    assert not valid
    assert "Open API key is empty" in message


@patch("app.validators.OpenAI")
def test_validate_open_api_key_success(mock_openai_cls: MagicMock) -> None:
    """Test Open API validation success."""
    mock_instance = MagicMock()
    mock_instance.models.list.return_value = MagicMock()
    mock_openai_cls.return_value = mock_instance

    valid, message = validate_open_api_key("sk-valid123")
    assert valid
    assert "valid and active" in message


@patch("app.validators.OpenAI")
def test_validate_open_api_key_unauthorised(mock_openai_cls: MagicMock) -> None:
    """Test Open API validation unauthorised key."""
    mock_instance = MagicMock()
    mock_response = MagicMock(status_code=401)
    mock_instance.models.list.side_effect = OpenAIAuthError(
        "Invalid API key", response=mock_response, body=None
    )
    mock_openai_cls.return_value = mock_instance

    valid, message = validate_open_api_key("sk-invalid")
    assert not valid
    assert "Invalid Open API key or unauthorised access" in message


@patch("app.validators.OpenAI")
def test_validate_open_api_key_timeout(mock_openai_cls: MagicMock) -> None:
    """Test Open API validation timeout."""
    mock_instance = MagicMock()
    mock_instance.models.list.side_effect = OpenAITimeoutError(request=MagicMock())
    mock_openai_cls.return_value = mock_instance

    valid, message = validate_open_api_key("sk-timeout")
    assert not valid
    assert "timed out" in message.lower()


@patch("app.validators.OpenAI")
def test_validate_open_api_key_conn_error(mock_openai_cls: MagicMock) -> None:
    """Test Open API validation connection error."""
    mock_instance = MagicMock()
    mock_instance.models.list.side_effect = OpenAIConnError(request=MagicMock())
    mock_openai_cls.return_value = mock_instance

    valid, message = validate_open_api_key(
        "sk-conn-err", base_url="https://custom.endpoint.ai/v1"
    )
    assert not valid
    assert "Unable to connect to Open API endpoint" in message


@patch("app.validators.OpenAI")
def test_validate_open_api_key_api_error(mock_openai_cls: MagicMock) -> None:
    """Test Open API validation generic OpenAIError."""
    mock_instance = MagicMock()
    mock_instance.models.list.side_effect = OpenAIError(
        "Rate limit or server error",
        request=MagicMock(),
        body=None,
    )
    mock_openai_cls.return_value = mock_instance

    valid, message = validate_open_api_key("sk-error")
    assert not valid
    assert "Open API error" in message


@patch("app.validators.OpenAI")
def test_validate_open_api_key_generic_exception(mock_openai_cls: MagicMock) -> None:
    """Test Open API validation unexpected exception."""
    mock_instance = MagicMock()
    mock_instance.models.list.side_effect = RuntimeError("OpenAI crash")
    mock_openai_cls.return_value = mock_instance

    valid, message = validate_open_api_key("sk-crash")
    assert not valid
    assert "Open API validation error" in message


# --- Service Dispatcher Tests ---


def test_validate_service_credentials_dispatcher() -> None:
    """Test service credentials dispatcher for all services and unknown service."""
    with patch("app.validators.validate_bus_api_key") as mock_bus:
        mock_bus.return_value = (True, "bus ok")
        valid, msg = validate_service_credentials("bus", {"bus_api_key": "k"})
        assert valid
        assert msg == "bus ok"

    with patch("app.validators.validate_train_s3_bucket") as mock_s3:
        mock_s3.return_value = (True, "s3 ok")
        valid, msg = validate_service_credentials("train_s3", {"train_s3_bucket": "b"})
        assert valid
        assert msg == "s3 ok"

        valid, msg = validate_service_credentials("train-s3", {"train_s3_bucket": "b"})
        assert valid
        assert msg == "s3 ok"

    with patch("app.validators.validate_train_live_token") as mock_live:
        mock_live.return_value = (True, "live ok")
        valid, msg = validate_service_credentials(
            "train_live", {"train_live_api_key": "k"}
        )
        assert valid
        assert msg == "live ok"

        valid, msg = validate_service_credentials("ldbws", {"train_live_api_key": "k"})
        assert valid
        assert msg == "live ok"

    with patch("app.validators.validate_open_api_key") as mock_openai:
        mock_openai.return_value = (True, "openai ok")
        valid, msg = validate_service_credentials("open_api", {"open_api_key": "k"})
        assert valid
        assert msg == "openai ok"

        valid, msg = validate_service_credentials("openai", {"open_api_key": "k"})
        assert valid
        assert msg == "openai ok"

    valid, msg = validate_service_credentials("unknown_service_xyz", {})
    assert not valid
    assert "Unknown service" in msg
