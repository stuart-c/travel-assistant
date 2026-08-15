"""Unit tests for AWS S3 bucket validation."""

from unittest.mock import MagicMock, patch
from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    BotoCoreError,
)

from app.validators import validate_train_s3_bucket


def test_validate_train_s3_bucket_empty() -> None:
    """Test S3 bucket validation with empty bucket name."""
    valid, message = validate_train_s3_bucket("")
    assert not valid
    assert "bucket name is required" in message


@patch("app.validators.s3.boto3.Session")
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


@patch("app.validators.s3.boto3.Session")
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


@patch("app.validators.s3.boto3.Session")
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


@patch("app.validators.s3.boto3.Session")
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


@patch("app.validators.s3.boto3.Session")
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


@patch("app.validators.s3.boto3.Session")
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


@patch("app.validators.s3.boto3.Session")
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


@patch("app.validators.s3.boto3.Session")
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


@patch("app.validators.s3.boto3.Session")
def test_validate_train_s3_bucket_generic_error(mock_session_cls: MagicMock) -> None:
    """Test S3 bucket validation generic error."""
    mock_session_cls.side_effect = RuntimeError("Session init failure")

    valid, message = validate_train_s3_bucket("generic-err-bucket")
    assert not valid
    assert "S3 validation error" in message
