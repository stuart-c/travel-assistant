"""Unit tests for TrainS3Client."""

import json
from io import BytesIO
from unittest.mock import MagicMock, patch
import pytest
from botocore.exceptions import BotoCoreError, ClientError
from flask import Flask

from app.datasources.train_s3 import TrainS3Client
from app.datasources.exceptions import (
    DataSourceAuthError,
    DataSourceConfigError,
    DataSourceConnectionError,
    DataSourceError,
)
from app.db.settings import SettingsRepository


def test_train_s3_from_settings(app: Flask) -> None:
    """Test TrainS3Client initialisation from SettingsRepository."""
    with app.app_context():
        repo = SettingsRepository()
        repo.set("train_s3_bucket", "my-rail-bucket")
        repo.set("train_s3_region", "eu-west-2")
        repo.set("train_s3_access_key", "AKIA123")
        repo.set("train_s3_secret_key", "SECRET456")

        client = TrainS3Client.from_settings(repo)
        assert client.bucket_name == "my-rail-bucket"
        assert client.region == "eu-west-2"
        assert client.access_key == "AKIA123"
        assert client.secret_key == "SECRET456"
        assert client.provider_name == "train_s3"


def test_train_s3_get_client_caching() -> None:
    """Test get_client creates boto3 client or reuses injected client."""
    mock_boto = MagicMock()
    client = TrainS3Client(bucket_name="b", s3_client=mock_boto)
    assert client.get_client() is mock_boto


@patch("boto3.Session")
def test_train_s3_get_client_instantiation(mock_session_cls: MagicMock) -> None:
    """Test get_client passes credentials to boto3.Session."""
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    client = TrainS3Client(
        bucket_name="b",
        region="eu-west-1",
        access_key="KEY",
        secret_key="SEC",
    )
    client.get_client()
    mock_session_cls.assert_called_once()
    kwargs = mock_session_cls.call_args[1]
    assert kwargs["aws_access_key_id"] == "KEY"
    assert kwargs["aws_secret_access_key"] == "SEC"


def test_train_s3_validate_credentials_empty() -> None:
    """Test validate_credentials with empty bucket name."""
    client = TrainS3Client(bucket_name="")
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "required" in res["message"]


def test_train_s3_validate_credentials_success() -> None:
    """Test validate_credentials when head_bucket succeeds."""
    mock_boto = MagicMock()
    mock_boto.head_bucket.return_value = {}
    client = TrainS3Client(bucket_name="test-bucket", s3_client=mock_boto)
    res = client.validate_credentials()
    assert res["valid"] is True
    assert "valid and accessible" in res["message"]


def test_train_s3_validate_credentials_client_errors() -> None:
    """Test validate_credentials with various ClientError status codes."""
    mock_boto = MagicMock()
    client = TrainS3Client(bucket_name="test-bucket", s3_client=mock_boto)

    # 403 Access Denied
    mock_boto.head_bucket.side_effect = ClientError(
        {"Error": {"Code": "403", "Message": "Forbidden"}}, "HeadBucket"
    )
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "Access denied" in res["message"]

    # 404 Not Found
    mock_boto.head_bucket.side_effect = ClientError(
        {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadBucket"
    )
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "does not exist" in res["message"]

    # 301 Permanent Redirect
    mock_boto.head_bucket.side_effect = ClientError(
        {"Error": {"Code": "301", "Message": "Moved"}}, "HeadBucket"
    )
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "different region" in res["message"]

    # Other code
    mock_boto.head_bucket.side_effect = ClientError(
        {"Error": {"Code": "500", "Message": "Internal"}}, "HeadBucket"
    )
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "S3 bucket error (500)" in res["message"]


def test_train_s3_validate_credentials_botocore_error() -> None:
    """Test validate_credentials with BotoCoreError."""
    mock_boto = MagicMock()
    mock_boto.head_bucket.side_effect = BotoCoreError()
    client = TrainS3Client(bucket_name="test-bucket", s3_client=mock_boto)
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "AWS S3 error" in res["message"]


def test_train_s3_validate_credentials_generic_exception() -> None:
    """Test validate_credentials with general Exception."""
    mock_boto = MagicMock()
    mock_boto.head_bucket.side_effect = RuntimeError("Fatal")
    client = TrainS3Client(bucket_name="test-bucket", s3_client=mock_boto)
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "S3 validation error" in res["message"]


def test_train_s3_fetch_stations_empty_bucket() -> None:
    """Test fetch_stations raises DataSourceConfigError when bucket is empty."""
    client = TrainS3Client(bucket_name="")
    with pytest.raises(DataSourceConfigError):
        client.fetch_stations()


def test_train_s3_fetch_stations_success_formats() -> None:
    """Test fetch_stations with dictionary and list JSON structures."""
    mock_boto = MagicMock()
    client = TrainS3Client(bucket_name="rail-bucket", s3_client=mock_boto)

    # 1. Dict format with "stations" key
    payload_dict = {
        "stations": [
            {
                "crs_code": "pad",
                "name": "London Paddington",
                "tiploc": "PADTON",
                "latitude": 51.5154,
                "longitude": -0.1755,
                "operator": "GWR",
            },
            {"crs_code": "", "name": "Invalid Station"},
        ]
    }
    mock_boto.get_object.return_value = {
        "Body": BytesIO(json.dumps(payload_dict).encode("utf-8"))
    }
    stations = client.fetch_stations()
    assert len(stations) == 1
    assert stations[0]["crs_code"] == "PAD"
    assert stations[0]["name"] == "London Paddington"

    # 2. List format
    payload_list = [
        {
            "crs": "OXF",
            "station_name": "Oxford",
            "tiploc_code": "OXFD",
            "latitude": 51.7534,
            "longitude": -1.2700,
            "toc": "GWR",
        }
    ]
    mock_boto.get_object.return_value = {
        "Body": BytesIO(json.dumps(payload_list).encode("utf-8"))
    }
    stations2 = client.fetch_stations()
    assert len(stations2) == 1
    assert stations2[0]["crs_code"] == "OXF"
    assert stations2[0]["name"] == "Oxford"

    # 3. Invalid JSON structure (not list or dict with stations)
    mock_boto.get_object.return_value = {
        "Body": BytesIO(json.dumps("plain-string").encode("utf-8"))
    }
    stations3 = client.fetch_stations()
    assert len(stations3) == 0


def test_train_s3_fetch_stations_errors() -> None:
    """Test fetch_stations error branches."""
    mock_boto = MagicMock()
    client = TrainS3Client(bucket_name="rail-bucket", s3_client=mock_boto)

    # Auth error
    mock_boto.get_object.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}, "GetObject"
    )
    with pytest.raises(DataSourceAuthError):
        client.fetch_stations()

    # Other ClientError
    mock_boto.get_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "Missing"}}, "GetObject"
    )
    with pytest.raises(DataSourceError):
        client.fetch_stations()

    # BotoCoreError
    mock_boto.get_object.side_effect = BotoCoreError()
    with pytest.raises(DataSourceConnectionError):
        client.fetch_stations()

    # Corrupt JSON
    mock_boto.get_object.side_effect = None
    mock_boto.get_object.return_value = {"Body": BytesIO(b"not json at all <xml>")}
    with pytest.raises(DataSourceError):
        client.fetch_stations()

    # Generic Exception
    mock_boto.get_object.side_effect = RuntimeError("Broken")
    with pytest.raises(DataSourceError):
        client.fetch_stations()
