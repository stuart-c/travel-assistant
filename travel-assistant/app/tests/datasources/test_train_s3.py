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
from app.models.setting import Setting


def test_train_s3_from_settings(app: Flask) -> None:
    """Test TrainS3Client initialisation from Setting model."""
    with app.app_context():
        Setting.set_val("train_s3_bucket", "my-rail-bucket")
        Setting.set_val("train_s3_region", "eu-west-2")
        Setting.set_val("train_s3_access_key", "AKIA123")
        Setting.set_val("train_s3_secret_key", "SECRET456")

        client = TrainS3Client.from_settings()
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


def test_train_s3_get_latest_timetable_key_empty_bucket() -> None:
    """Test get_latest_timetable_key raises DataSourceConfigError when bucket is empty."""
    client = TrainS3Client(bucket_name="")
    with pytest.raises(DataSourceConfigError):
        client.get_latest_timetable_key()


def test_train_s3_get_latest_timetable_key_success_and_none() -> None:
    """Test get_latest_timetable_key finds latest _v8.xml.gz or returns None."""
    mock_boto = MagicMock()
    client = TrainS3Client(bucket_name="rail-bucket", s3_client=mock_boto)

    # 1. Matching keys returned
    mock_boto.list_objects_v2.return_value = {
        "Contents": [
            {"Key": "PPTimetable/20260816_ref_v8.xml.gz"},
            {"Key": "PPTimetable/20260817_v8.xml.gz"},
            {"Key": "PPTimetable/20260815_v8.xml.gz"},
            {"Key": "PPTimetable/other_file.txt"},
        ]
    }
    latest = client.get_latest_timetable_key()
    assert latest == "PPTimetable/20260817_v8.xml.gz"

    # 2. No matching keys
    mock_boto.list_objects_v2.return_value = {
        "Contents": [{"Key": "PPTimetable/some_random_file.txt"}]
    }
    assert client.get_latest_timetable_key() is None

    # 3. Empty list
    mock_boto.list_objects_v2.return_value = {}
    assert client.get_latest_timetable_key() is None


def test_train_s3_get_latest_timetable_key_errors() -> None:
    """Test get_latest_timetable_key error handling."""
    mock_boto = MagicMock()
    client = TrainS3Client(bucket_name="rail-bucket", s3_client=mock_boto)

    mock_boto.list_objects_v2.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}, "ListObjectsV2"
    )
    with pytest.raises(DataSourceAuthError):
        client.get_latest_timetable_key()

    mock_boto.list_objects_v2.side_effect = BotoCoreError()
    with pytest.raises(DataSourceConnectionError):
        client.get_latest_timetable_key()


def test_train_s3_download_timetable_snapshot_success_and_errors() -> None:
    """Test download_timetable_snapshot byte retrieval and errors."""
    mock_boto = MagicMock()
    client = TrainS3Client(bucket_name="rail-bucket", s3_client=mock_boto)

    mock_boto.get_object.return_value = {"Body": BytesIO(b"<xml>darwin</xml>")}
    content = client.download_timetable_snapshot("PPTimetable/test.xml.gz")
    assert content == b"<xml>darwin</xml>"

    # Empty bucket
    client_empty = TrainS3Client(bucket_name="")
    with pytest.raises(DataSourceConfigError):
        client_empty.download_timetable_snapshot("key")

    # Error
    mock_boto.get_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "Not found"}}, "GetObject"
    )
    with pytest.raises(DataSourceError):
        client.download_timetable_snapshot("missing.xml.gz")


def test_train_s3_parse_darwin_timetables_gzip_and_plain() -> None:
    """Test parse_darwin_timetables extracting journeys and TOC metadata."""
    import gzip

    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<PportTimetable xmlns="http://www.thalesgroup.com/rtti/XmlTimetable/v8">
  <Journey rid="20260817111111" trainId="1T44" toc="TL" ssd="2026-08-17" isPassengerSvc="true">
    <OR tpl="STEVNG" act="TB" ptd="06:48"/>
    <IP tpl="HITCHIN" pta="06:54" ptd="06:55"/>
    <DT tpl="CAMBDGE" act="TF" pta="07:49"/>
  </Journey>
  <Journey rid="20260817222222" trainId="2P22" toc="GN" ssd="2026-08-17" isPassengerSvc="true">
    <OR tpl="STEVNG" act="TB" ptd="07:20"/>
    <IP tpl="HITCHIN" pta="07:26" ptd="07:27"/>
    <DT tpl="CAMBDGE" act="TF" pta="08:19"/>
  </Journey>
  <Journey rid="20260817333333" trainId="0Z99" toc="ZZ" ssd="2026-08-17" isPassengerSvc="false">
    <OR tpl="STEVNG" ptd="05:00"/>
    <DT tpl="CAMBDGE" pta="05:30"/>
  </Journey>
  <Journey rid="20260817444444" trainId="EMPTY" toc="TL" isPassengerSvc="true">
    <OR tpl="STEVNG" ptd="08:00"/>
  </Journey>
</PportTimetable>"""

    gz_bytes = gzip.compress(xml_content.encode("utf-8"))
    client = TrainS3Client(bucket_name="rail-bucket")

    # 1. Parse with cached stop lookup using canonical NaPTAN ATCO IDs
    stop_lookup = {
        "STEVNG": {
            "id": "9100STEVNGE",
            "name": "Stevenage",
            "type": "rail",
            "indicator": "Station",
            "icon": "train",
        },
        "HITCHIN": {
            "id": "9100HITCHIN",
            "name": "Hitchin",
            "type": "rail",
            "indicator": "Station",
            "icon": "train",
        },
        "9100CAMBDGE": {
            "id": "9100CAMBDGE",
            "name": "Cambridge",
            "type": "rail",
            "indicator": "Station",
            "icon": "train",
        },
    }

    timetables = client.parse_darwin_timetables(gz_bytes, stop_lookup=stop_lookup)
    assert len(timetables) == 1
    tt = timetables[0]
    assert tt["name"] == "Stevenage to Cambridge"
    assert tt["transport_type"] == "rail"
    assert tt["auto_added"] is True
    assert str(tt["start_date"]) == "2026-08-17"
    assert str(tt["end_date"]) == "2026-08-17"

    content = tt["content"]
    assert len(content["stops"]) == 3
    assert content["stops"][0]["id"] == "9100STEVNGE"
    assert content["stops"][0]["name"] == "Stevenage"
    assert content["stops"][1]["id"] == "9100HITCHIN"
    assert content["stops"][1]["name"] == "Hitchin"
    assert content["stops"][2]["id"] == "9100CAMBDGE"
    assert content["stops"][2]["name"] == "Cambridge"

    assert len(content["trips"]) == 2
    trip1 = content["trips"][0]
    assert trip1["toc"] == "TL"
    assert trip1["operator"] == "Thameslink"
    assert trip1["headsign"] == "TL 1T44"
    assert trip1["times"] == [
        {"arr": "", "dep": "06:48"},
        {"arr": "06:54", "dep": "06:55"},
        {"arr": "07:49", "dep": ""},
    ]

    trip2 = content["trips"][1]
    assert trip2["toc"] == "GN"
    assert trip2["operator"] == "Great Northern"
    assert trip2["headsign"] == "GN 2P22"
    assert trip2["times"] == [
        {"arr": "", "dep": "07:20"},
        {"arr": "07:26", "dep": "07:27"},
        {"arr": "08:19", "dep": ""},
    ]

    # 2. Parse raw uncompressed XML bytes
    timetables_raw = client.parse_darwin_timetables(
        xml_content.encode("utf-8"), stop_lookup=stop_lookup
    )
    assert len(timetables_raw) == 1


def test_train_s3_parse_darwin_timetables_invalid_xml() -> None:
    """Test parse_darwin_timetables raises DataSourceError for invalid XML."""
    client = TrainS3Client(bucket_name="rail-bucket")
    with pytest.raises(DataSourceError):
        client.parse_darwin_timetables(b"corrupted bytes <<>>")


def test_train_s3_fetch_timetables_workflow() -> None:
    """Test fetch_timetables full integration."""
    import gzip

    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<PportTimetable xmlns="http://www.thalesgroup.com/rtti/XmlTimetable/v8">
  <Journey rid="20260817111111" trainId="1T44" toc="TL" ssd="2026-08-17" isPassengerSvc="true">
    <OR tpl="STEVNG" ptd="06:48"/>
    <DT tpl="CAMBDGE" pta="07:49"/>
  </Journey>
</PportTimetable>"""
    gz_bytes = gzip.compress(xml_content.encode("utf-8"))

    mock_boto = MagicMock()
    mock_boto.list_objects_v2.return_value = {
        "Contents": [{"Key": "PPTimetable/20260817_v8.xml.gz"}]
    }
    mock_boto.get_object.return_value = {"Body": BytesIO(gz_bytes)}

    client = TrainS3Client(bucket_name="rail-bucket", s3_client=mock_boto)
    timetables = client.fetch_timetables()
    assert len(timetables) == 1
    assert timetables[0]["auto_added"] is True
    assert timetables[0]["content"]["trips"][0]["toc"] == "TL"

    # Empty bucket
    client_empty = TrainS3Client(bucket_name="")
    with pytest.raises(DataSourceConfigError):
        client_empty.fetch_timetables()

    # No timetable files in S3
    mock_boto.list_objects_v2.return_value = {}
    with pytest.raises(DataSourceError) as exc_info:
        client.fetch_timetables()
    assert "No Darwin XML timetable snapshots found" in str(exc_info.value)


def test_train_s3_parse_darwin_timetables_weekday_saturday_sunday() -> None:
    """Test parse_darwin_timetables partitions journeys by weekday, Saturday, and Sunday with correct day flags."""
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<PportTimetable xmlns="http://www.thalesgroup.com/rtti/XmlTimetable/v8">
  <!-- Weekday (Friday 2026-08-14) -->
  <Journey rid="20260814111111" trainId="1W01" toc="TL" ssd="2026-08-14" isPassengerSvc="true">
    <OR tpl="STEVNG" ptd="07:00"/>
    <DT tpl="CAMBDGE" pta="07:50"/>
  </Journey>
  <!-- Duplicate Weekday (Thursday 2026-08-13) with same trainId -->
  <Journey rid="20260813111111" trainId="1W01" toc="TL" ssd="2026-08-13" isPassengerSvc="true">
    <OR tpl="STEVNG" ptd="07:00"/>
    <DT tpl="CAMBDGE" pta="07:50"/>
  </Journey>
  <!-- Saturday (2026-08-15) -->
  <Journey rid="20260815222222" trainId="1S01" toc="TL" ssd="2026-08-15" isPassengerSvc="true">
    <OR tpl="STEVNG" ptd="08:00"/>
    <DT tpl="CAMBDGE" pta="08:50"/>
  </Journey>
  <!-- Sunday (2026-08-16) -->
  <Journey rid="20260816333333" trainId="1U01" toc="TL" ssd="2026-08-16" isPassengerSvc="true">
    <OR tpl="STEVNG" ptd="09:00"/>
    <DT tpl="CAMBDGE" pta="09:50"/>
  </Journey>
</PportTimetable>"""

    client = TrainS3Client(bucket_name="rail-bucket")
    stop_lookup = {
        "STEVNG": {"id": "9100STEVNGE", "name": "Stevenage", "type": "rail"},
        "CAMBDGE": {"id": "9100CAMBDGE", "name": "Cambridge", "type": "rail"},
    }
    timetables = client.parse_darwin_timetables(
        xml_content.encode("utf-8"), stop_lookup=stop_lookup
    )

    # Should have 3 timetables: Weekday (Mon-Fri), Saturday, Sunday
    assert len(timetables) == 3

    wd_tt = next((t for t in timetables if t["monday"]), None)
    sat_tt = next((t for t in timetables if t["saturday"]), None)
    sun_tt = next((t for t in timetables if t["sunday"]), None)

    assert wd_tt is not None
    assert wd_tt["name"] == "Stevenage to Cambridge (Mon-Fri)"
    assert wd_tt["monday"] is True
    assert wd_tt["friday"] is True
    assert wd_tt["saturday"] is False
    assert wd_tt["sunday"] is False
    assert wd_tt["bank_holiday"] is False
    # Verified deduplication: 1W01 only appears once in weekday timetable
    assert len(wd_tt["content"]["trips"]) == 1
    assert wd_tt["content"]["trips"][0]["headsign"] == "TL 1W01"

    assert sat_tt is not None
    assert sat_tt["name"] == "Stevenage to Cambridge (Sat)"
    assert sat_tt["monday"] is False
    assert sat_tt["friday"] is False
    assert sat_tt["saturday"] is True
    assert sat_tt["sunday"] is False
    assert sat_tt["bank_holiday"] is False
    assert len(sat_tt["content"]["trips"]) == 1
    assert sat_tt["content"]["trips"][0]["headsign"] == "TL 1S01"

    assert sun_tt is not None
    assert sun_tt["name"] == "Stevenage to Cambridge (Sun)"
    assert sun_tt["monday"] is False
    assert sun_tt["friday"] is False
    assert sun_tt["saturday"] is False
    assert sun_tt["sunday"] is True
    assert sun_tt["bank_holiday"] is True
    assert len(sun_tt["content"]["trips"]) == 1
    assert sun_tt["content"]["trips"][0]["headsign"] == "TL 1U01"
