"""Unit tests for BodsClient."""

from unittest.mock import MagicMock, patch
import pytest
import requests
from flask import Flask

from app.datasources.bods import BodsClient
from app.datasources.exceptions import (
    DataSourceAuthError,
    DataSourceConfigError,
    DataSourceConnectionError,
    DataSourceError,
    DataSourceRateLimitError,
)
from app.models.setting import Setting


def test_bods_client_from_settings(app: Flask) -> None:
    """Test BodsClient initialisation from Setting model."""
    with app.app_context():
        Setting.set_val("bus_api_key", "test-bus-key-123")
        client = BodsClient.from_settings()
        assert client.api_key == "test-bus-key-123"
        assert client.provider_name == "bods"


def test_bods_validate_credentials_empty() -> None:
    """Test validate_credentials returns invalid on empty key."""
    client = BodsClient(api_key="")
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "empty" in res["message"]


@patch("app.datasources.bods.requests.get")
def test_bods_validate_credentials_success(mock_get: MagicMock) -> None:
    """Test validate_credentials with HTTP 200 success."""
    mock_get.return_value = MagicMock(status_code=200)
    client = BodsClient(api_key="valid-key")
    res = client.validate_credentials()
    assert res["valid"] is True
    assert "valid and active" in res["message"]


@patch("app.datasources.bods.requests.get")
def test_bods_validate_credentials_auth_fail(mock_get: MagicMock) -> None:
    """Test validate_credentials with HTTP 401 / 403."""
    mock_get.return_value = MagicMock(status_code=401)
    client = BodsClient(api_key="bad-key")
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "unauthorised access" in res["message"]


@patch("app.datasources.bods.requests.get")
def test_bods_validate_credentials_rate_limit(mock_get: MagicMock) -> None:
    """Test validate_credentials with HTTP 429."""
    mock_get.return_value = MagicMock(status_code=429)
    client = BodsClient(api_key="rate-key")
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "rate limit" in res["message"]


@patch("app.datasources.bods.requests.get")
def test_bods_validate_credentials_unexpected_code(mock_get: MagicMock) -> None:
    """Test validate_credentials with HTTP 500."""
    mock_get.return_value = MagicMock(status_code=500, text="Internal server error")
    client = BodsClient(api_key="any-key")
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "unexpected status code 500" in res["message"]


@patch("app.datasources.bods.requests.get")
def test_bods_validate_credentials_timeout(mock_get: MagicMock) -> None:
    """Test validate_credentials timeout handling."""
    mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")
    client = BodsClient(api_key="timeout-key")
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "timed out" in res["message"]


@patch("app.datasources.bods.requests.get")
def test_bods_validate_credentials_request_exception(mock_get: MagicMock) -> None:
    """Test validate_credentials RequestException handling."""
    mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")
    client = BodsClient(api_key="conn-key")
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "Network error" in res["message"]


@patch("app.datasources.bods.requests.get")
def test_bods_validate_credentials_general_exception(mock_get: MagicMock) -> None:
    """Test validate_credentials general Exception handling."""
    mock_get.side_effect = RuntimeError("Crash")
    client = BodsClient(api_key="crash-key")
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "Unexpected error" in res["message"]


def test_bods_fetch_routes_empty_key() -> None:
    """Test fetch_routes raises DataSourceConfigError when key is missing."""
    client = BodsClient(api_key="")
    with pytest.raises(DataSourceConfigError) as exc_info:
        client.fetch_routes()
    assert "not configured" in str(exc_info.value)


@patch("app.datasources.bods.requests.get")
def test_bods_fetch_routes_success(mock_get: MagicMock) -> None:
    """Test fetch_routes successfully parses routes with verified lines."""
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {
        "results": [
            {
                "id": 101,
                "name": "Oxford City Lines",
                "operator_name": "Oxford Bus Company",
                "noc": ["OBC"],
                "description": "City routes",
                "lines": ["1", "5"],
                "origin": "City Centre",
                "destination": "Blackbird Leys",
            },
            {
                "id": 102,
                "name": "London Express",
                "operator_name": "Stagecoach",
                "noc": ["SC"],
                "description": "Express coach",
                "lines": [],
                "origin": "Gloucester Green",
                "destination": "Victoria",
            },
        ]
    }
    mock_get.return_value = mock_response

    client = BodsClient(api_key="valid-key")
    routes = client.fetch_routes(limit=10)
    assert len(routes) == 2
    assert routes[0]["route_number"] == "1"
    assert routes[0]["operator_name"] == "Oxford Bus Company"
    assert routes[1]["route_number"] == "5"


@patch("app.datasources.bods.requests.get")
def test_bods_fetch_routes_auth_error(mock_get: MagicMock) -> None:
    """Test fetch_routes raises DataSourceAuthError on 401."""
    mock_get.return_value = MagicMock(status_code=401)
    client = BodsClient(api_key="bad-key")
    with pytest.raises(DataSourceAuthError):
        client.fetch_routes()


@patch("app.datasources.bods.requests.get")
def test_bods_fetch_routes_rate_limit(mock_get: MagicMock) -> None:
    """Test fetch_routes raises DataSourceRateLimitError on 429."""
    mock_get.return_value = MagicMock(status_code=429)
    client = BodsClient(api_key="rate-key")
    with pytest.raises(DataSourceRateLimitError):
        client.fetch_routes()


@patch("app.datasources.bods.requests.get")
def test_bods_fetch_routes_timeout(mock_get: MagicMock) -> None:
    """Test fetch_routes raises DataSourceConnectionError on timeout."""
    mock_get.side_effect = requests.exceptions.Timeout("Timed out")
    client = BodsClient(api_key="key")
    with pytest.raises(DataSourceConnectionError):
        client.fetch_routes()


@patch("app.datasources.bods.requests.get")
def test_bods_fetch_routes_request_exception(mock_get: MagicMock) -> None:
    """Test fetch_routes raises DataSourceConnectionError on RequestException."""
    mock_get.side_effect = requests.exceptions.ConnectionError("Refused")
    client = BodsClient(api_key="key")
    with pytest.raises(DataSourceConnectionError):
        client.fetch_routes()


@patch("app.datasources.bods.requests.get")
def test_bods_fetch_routes_general_exception(mock_get: MagicMock) -> None:
    """Test fetch_routes raises DataSourceError on generic Exception."""
    mock_get.side_effect = ValueError("Corrupt JSON")
    client = BodsClient(api_key="key")
    with pytest.raises(DataSourceError):
        client.fetch_routes()


SAMPLE_TRANSXCHANGE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<TransXChange xmlns="http://www.transxchange.org.uk/"
              CreationDateTime="2026-08-17T12:00:00"
              SchemaVersion="2.4">
  <Operators>
    <Operator id="O1">
      <NationalOperatorCode>ARRI</NationalOperatorCode>
      <OperatorShortName>Arriva</OperatorShortName>
    </Operator>
  </Operators>
  <StopPoints>
    <AnnotatedStopPointRef>
      <StopPointRef>049000001</StopPointRef>
      <CommonName>Stevenage Bus Station</CommonName>
      <Indicator>Stop A</Indicator>
      <LocalityName>Stevenage</LocalityName>
    </AnnotatedStopPointRef>
    <AnnotatedStopPointRef>
      <StopPointRef>049000002</StopPointRef>
      <CommonName>Hitchin High Street</CommonName>
      <Indicator>Stop B</Indicator>
      <LocalityName>Hitchin</LocalityName>
    </AnnotatedStopPointRef>
  </StopPoints>
  <JourneyPatternSections>
    <JourneyPatternSection id="JPS_1">
      <JourneyPatternTimingLink id="JPTL_1">
        <From SequenceNumber="1">
          <StopPointRef>049000001</StopPointRef>
        </From>
        <To SequenceNumber="2">
          <StopPointRef>049000002</StopPointRef>
        </To>
        <RunTime>PT15M</RunTime>
      </JourneyPatternTimingLink>
    </JourneyPatternSection>
  </JourneyPatternSections>
  <Services>
    <Service>
      <ServiceCode>PB00010</ServiceCode>
      <Lines>
        <Line id="L1">
          <LineName>10</LineName>
        </Line>
      </Lines>
      <OperatingPeriod>
        <StartDate>2026-01-01</StartDate>
        <EndDate>2026-12-31</EndDate>
      </OperatingPeriod>
      <OperatingProfile>
        <RegularDayType>
          <DaysOfWeek>
            <MondayToFriday/>
          </DaysOfWeek>
        </RegularDayType>
        <BankHolidayOperation>
          <DaysOfNonOperation>
            <AllBankHolidays/>
          </DaysOfNonOperation>
        </BankHolidayOperation>
      </OperatingProfile>
      <StandardService>
        <Origin>Stevenage</Origin>
        <Destination>Hitchin</Destination>
        <JourneyPattern id="JP_1">
          <JourneyPatternSectionRefs>JPS_1</JourneyPatternSectionRefs>
        </JourneyPattern>
      </StandardService>
    </Service>
  </Services>
  <VehicleJourneys>
    <VehicleJourney>
      <VehicleJourneyCode>VJ_1</VehicleJourneyCode>
      <ServiceRef>PB00010</ServiceRef>
      <JourneyPatternRef>JP_1</JourneyPatternRef>
      <DepartureTime>08:30:00</DepartureTime>
      <OperatorRef>O1</OperatorRef>
    </VehicleJourney>
    <VehicleJourney>
      <VehicleJourneyCode>VJ_2</VehicleJourneyCode>
      <ServiceRef>PB00010</ServiceRef>
      <JourneyPatternRef>JP_1</JourneyPatternRef>
      <DepartureTime>09:30:00</DepartureTime>
      <OperatorRef>O1</OperatorRef>
    </VehicleJourney>
  </VehicleJourneys>
</TransXChange>
"""


def test_bods_parse_transxchange_xml() -> None:
    """Test parse_transxchange_xml extracts structured timetable matrices."""
    timetables = BodsClient.parse_transxchange_xml(
        SAMPLE_TRANSXCHANGE_XML,
        target_stop_codes={"049000001"},
    )
    assert len(timetables) == 1
    tt = timetables[0]
    assert tt["name"] == "Bus 10: Stevenage to Hitchin"
    assert tt["transport_type"] == "bus"
    assert tt["auto_added"] is True
    assert tt["monday"] is True
    assert tt["friday"] is True
    assert tt["saturday"] is False
    assert tt["sunday"] is False
    assert tt["bank_holiday"] is False
    assert len(tt["content"]["stops"]) == 2
    assert tt["content"]["stops"][0]["id"] == "049000001"
    assert tt["content"]["stops"][0]["name"] == "Stevenage Bus Station"
    assert tt["content"]["stops"][1]["id"] == "049000002"
    assert len(tt["content"]["trips"]) == 2
    assert tt["content"]["trips"][0]["times"] == ["08:30", "08:45"]
    assert tt["content"]["trips"][1]["times"] == ["09:30", "09:45"]
    assert tt["content"]["trips"][0]["operator"] == "Arriva"


def test_bods_parse_transxchange_xml_unmatched_stops() -> None:
    """Test parse_transxchange_xml returns empty when target stop codes do not match."""
    timetables = BodsClient.parse_transxchange_xml(
        SAMPLE_TRANSXCHANGE_XML,
        target_stop_codes={"999999999"},
    )
    assert len(timetables) == 0


def test_bods_parse_transxchange_xml_empty_and_corrupt() -> None:
    """Test parse_transxchange_xml handles empty input and malformed XML."""
    assert BodsClient.parse_transxchange_xml("") == []
    assert BodsClient.parse_transxchange_xml(b"") == []
    with pytest.raises(DataSourceError) as exc_info:
        BodsClient.parse_transxchange_xml("<broken><xml>")
    assert "Failed to parse TransXChange XML" in str(exc_info.value)


def test_bods_parse_transxchange_dataset_zip() -> None:
    """Test parse_transxchange_dataset processes zip archives with multiple XMLs."""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("route10.xml", SAMPLE_TRANSXCHANGE_XML)
        zf.writestr("ignored.txt", "some text")

    zip_bytes = buf.getvalue()
    timetables = BodsClient.parse_transxchange_dataset(
        zip_bytes,
        target_stop_codes={"049000002"},
    )
    assert len(timetables) == 1
    assert timetables[0]["name"] == "Bus 10: Stevenage to Hitchin"


def test_bods_parse_transxchange_dataset_corrupted_zip() -> None:
    """Test parse_transxchange_dataset raises DataSourceError on bad zip."""
    bad_zip = b"PK\x03\x04invalidzipdata"
    with pytest.raises(DataSourceError) as exc_info:
        BodsClient.parse_transxchange_dataset(bad_zip)
    assert "Corrupted ZIP archive" in str(exc_info.value)


def test_bods_download_dataset_file_empty_key() -> None:
    """Test download_dataset_file raises DataSourceConfigError when key is empty."""
    client = BodsClient(api_key="")
    with pytest.raises(DataSourceConfigError):
        client.download_dataset_file("https://data.bus-data.dft.gov.uk/download/1")


def test_bods_download_dataset_file_empty_url() -> None:
    """Test download_dataset_file raises DataSourceError on empty URL."""
    client = BodsClient(api_key="key")
    with pytest.raises(DataSourceError):
        client.download_dataset_file("")


@patch("app.datasources.bods.requests.get")
def test_bods_download_dataset_file_success(mock_get: MagicMock) -> None:
    """Test download_dataset_file successfully retrieves binary bytes."""
    mock_resp = MagicMock(status_code=200, content=b"<xml></xml>")
    mock_get.return_value = mock_resp

    client = BodsClient(api_key="valid-key")
    content = client.download_dataset_file(
        "https://data.bus-data.dft.gov.uk/download/1"
    )
    assert content == b"<xml></xml>"


@patch("app.datasources.bods.requests.get")
def test_bods_download_dataset_file_errors(mock_get: MagicMock) -> None:
    """Test download_dataset_file error handling for 401, 429, timeout, and exceptions."""
    client = BodsClient(api_key="key")

    mock_get.return_value = MagicMock(status_code=401)
    with pytest.raises(DataSourceAuthError):
        client.download_dataset_file("https://example.com/data")

    mock_get.return_value = MagicMock(status_code=429)
    with pytest.raises(DataSourceRateLimitError):
        client.download_dataset_file("https://example.com/data")

    mock_get.side_effect = requests.exceptions.Timeout("Download timeout")
    with pytest.raises(DataSourceConnectionError):
        client.download_dataset_file("https://example.com/data")

    mock_get.side_effect = requests.exceptions.ConnectionError("Refused")
    with pytest.raises(DataSourceConnectionError):
        client.download_dataset_file("https://example.com/data")

    mock_get.side_effect = RuntimeError("Unknown error")
    with pytest.raises(DataSourceError):
        client.download_dataset_file("https://example.com/data")


def test_bods_fetch_timetables_empty_key() -> None:
    """Test fetch_timetables raises DataSourceConfigError when key is empty."""
    client = BodsClient(api_key="")
    with pytest.raises(DataSourceConfigError):
        client.fetch_timetables()


@patch.object(BodsClient, "download_dataset_file")
@patch("app.datasources.bods.requests.get")
def test_bods_fetch_timetables_success(
    mock_get: MagicMock, mock_download: MagicMock
) -> None:
    """Test fetch_timetables queries datasets, downloads archives, and returns parsed timetables."""
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "results": [
                {"id": 1, "url": "https://data.bus-data.dft.gov.uk/dataset/1.zip"}
            ]
        },
    )
    mock_download.return_value = SAMPLE_TRANSXCHANGE_XML.encode("utf-8")

    client = BodsClient(api_key="test-key")
    tts = client.fetch_timetables(
        target_stop_codes={"049000001"},
        admin_areas=["049"],
    )
    assert len(tts) == 1
    assert tts[0]["name"] == "Bus 10: Stevenage to Hitchin"
    mock_get.assert_called_once_with(
        "https://data.bus-data.dft.gov.uk/api/v1/dataset",
        params={
            "api_key": "test-key",
            "status": "published",
            "limit": 25,
            "adminArea": "049",
        },
        timeout=5.0,
    )


@patch("app.datasources.bods.requests.get")
def test_bods_fetch_timetables_errors(mock_get: MagicMock) -> None:
    """Test fetch_timetables handles auth, rate limit, timeout, and connection errors."""
    client = BodsClient(api_key="test-key")

    mock_get.return_value = MagicMock(status_code=401)
    with pytest.raises(DataSourceAuthError):
        client.fetch_timetables()

    mock_get.return_value = MagicMock(status_code=429)
    with pytest.raises(DataSourceRateLimitError):
        client.fetch_timetables()

    mock_get.side_effect = requests.exceptions.Timeout("Timeout")
    with pytest.raises(DataSourceConnectionError):
        client.fetch_timetables()

    mock_get.side_effect = requests.exceptions.ConnectionError("Refused")
    with pytest.raises(DataSourceConnectionError):
        client.fetch_timetables()

    mock_get.side_effect = Exception("Unknown failure")
    with pytest.raises(DataSourceError):
        client.fetch_timetables()
