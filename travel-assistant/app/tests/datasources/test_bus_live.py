"""Unit test suite for BODS SIRI-VM live bus telemetry client (BodsLiveClient)."""

import datetime
from unittest.mock import MagicMock, patch
import pytest
import requests
from flask import Flask

from app.datasources import get_datasource
from app.datasources.bus_live import (
    BodsLiveClient,
    parse_iso_delay,
)
from app.datasources.exceptions import (
    DataSourceAuthError,
    DataSourceConfigError,
    DataSourceConnectionError,
    DataSourceError,
    DataSourceRateLimitError,
)
from app.models.setting import Setting
from app.validators.dispatcher import validate_service_credentials

SAMPLE_LONDON_SIRI_VM_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<Siri xmlns="http://www.siri.org.uk/siri" version="2.0">
  <ServiceDelivery>
    <ResponseTimestamp>2026-09-18T08:15:00Z</ResponseTimestamp>
    <VehicleMonitoringDelivery>
      <ResponseTimestamp>2026-09-18T08:15:00Z</ResponseTimestamp>
      <ValidUntil>2026-09-18T08:20:00Z</ValidUntil>
      <!-- Vehicle 1: Route 73 approaching London King's Cross, 4 mins late -->
      <VehicleActivity>
        <RecordedAtTime>2026-09-18T08:14:30Z</RecordedAtTime>
        <ItemIdentifier>item-73-01</ItemIdentifier>
        <ValidUntilTime>2026-09-18T08:20:00Z</ValidUntilTime>
        <MonitoredVehicleJourney>
          <LineRef>73</LineRef>
          <DirectionRef>inbound</DirectionRef>
          <PublishedLineName>73</PublishedLineName>
          <OperatorRef>ARHE</OperatorRef>
          <OriginRef>490000077E</OriginRef>
          <OriginName>Victoria Station</OriginName>
          <DestinationRef>490000077C</DestinationRef>
          <DestinationName>Stoke Newington Common</DestinationName>
          <OriginAimedDepartureTime>2026-09-18T08:00:00Z</OriginAimedDepartureTime>
          <Delay>PT4M</Delay>
          <VehicleLocation>
            <Longitude>-0.1245</Longitude>
            <Latitude>51.5308</Latitude>
          </VehicleLocation>
          <Bearing>45.0</Bearing>
          <VehicleRef>LTZ1073</VehicleRef>
        </MonitoredVehicleJourney>
      </VehicleActivity>
      <!-- Vehicle 2: Route 205 at London Euston, early by 2 mins -->
      <VehicleActivity>
        <RecordedAtTime>2026-09-18T08:14:00Z</RecordedAtTime>
        <ItemIdentifier>item-205-02</ItemIdentifier>
        <ValidUntilTime>2026-09-18T08:20:00Z</ValidUntilTime>
        <MonitoredVehicleJourney>
          <LineRef>205</LineRef>
          <DirectionRef>outbound</DirectionRef>
          <PublishedLineName>205</PublishedLineName>
          <OperatorRef>GAL</OperatorRef>
          <OriginRef>490000185A</OriginRef>
          <OriginName>Paddington Station</OriginName>
          <DestinationRef>490000028B</DestinationRef>
          <DestinationName>Bow Church</DestinationName>
          <OriginAimedDepartureTime>2026-09-18T08:10:00Z</OriginAimedDepartureTime>
          <Delay>-PT2M</Delay>
          <VehicleLocation>
            <Longitude>-0.1332</Longitude>
            <Latitude>51.5284</Latitude>
          </VehicleLocation>
          <Bearing>90.0</Bearing>
          <VehicleRef>LTZ1205</VehicleRef>
        </MonitoredVehicleJourney>
      </VehicleActivity>
      <!-- Vehicle 3: Route 73 Stale/Depot (recorded > 20 mins ago) -->
      <VehicleActivity>
        <RecordedAtTime>2026-09-18T07:45:00Z</RecordedAtTime>
        <ItemIdentifier>item-73-stale</ItemIdentifier>
        <MonitoredVehicleJourney>
          <LineRef>73</LineRef>
          <PublishedLineName>73</PublishedLineName>
          <OperatorRef>ARHE</OperatorRef>
          <OriginName>Depot</OriginName>
          <DestinationName>Victoria Station</DestinationName>
          <VehicleRef>LTZ9999</VehicleRef>
        </MonitoredVehicleJourney>
      </VehicleActivity>
    </VehicleMonitoringDelivery>
  </ServiceDelivery>
</Siri>"""


def test_bods_live_from_settings(app: Flask) -> None:
    """Test BodsLiveClient initialisation via settings getter and Setting model."""
    with app.app_context():
        Setting.set_val("bus_api_key", "test-bods-live-token")
        Setting.set_val(
            "bus_live_endpoint", "https://custom.bus-data.dft.gov.uk/api/v1/siri-vm"
        )

        client = BodsLiveClient.from_settings()
        assert client.api_key == "test-bods-live-token"
        assert client.base_url == "https://custom.bus-data.dft.gov.uk/api/v1/siri-vm"
        assert client.provider_name == "bus_live"

        # Test dictionary settings provider
        dict_settings = {
            "bus_api_key": "dict-bods-token",
            "bus_live_endpoint": "https://example.com/siri",
        }
        client_dict = BodsLiveClient.from_settings(dict_settings)
        assert client_dict.api_key == "dict-bods-token"
        assert client_dict.base_url == "https://example.com/siri"


def test_bods_live_registry_and_factory() -> None:
    """Test BodsLiveClient resolution through DATASOURCE_REGISTRY and get_datasource."""
    settings = {"bus_api_key": "reg-key"}
    ds = get_datasource("bus_live", settings)
    assert isinstance(ds, BodsLiveClient)
    assert ds.api_key == "reg-key"


def test_parse_iso_delay_variations() -> None:
    """Test parse_iso_delay helper across diverse ISO 8601 delay strings."""
    # None or empty
    assert parse_iso_delay(None) == (0, 0, "On time", "On time")
    assert parse_iso_delay("") == (0, 0, "On time", "On time")

    # On time / small delay within 60s
    sec, mins, status, label = parse_iso_delay("PT0S")
    assert sec == 0 and mins == 0 and status == "On time" and label == "On time"

    sec, mins, status, label = parse_iso_delay("PT45S")
    assert sec == 45 and mins == 0 and status == "On time" and label == "On time"

    # Delayed: 4 minutes
    sec, mins, status, label = parse_iso_delay("PT4M")
    assert sec == 240 and mins == 4 and status == "Delayed" and label == "+4m late"

    # Delayed with hours and seconds: 1h 15m 30s
    sec, mins, status, label = parse_iso_delay("PT1H15M30S")
    assert sec == 4530 and mins == 75 and status == "Delayed" and label == "+75m late"

    # Early: -2 minutes (-PT2M)
    sec, mins, status, label = parse_iso_delay("-PT2M")
    assert sec == -120 and mins == -2 and status == "Early" and label == "Early -2m"

    # Early by seconds: -45s
    sec, mins, status, label = parse_iso_delay("-PT45S")
    assert sec == -45 and status == "Early" and label == "Early -45s"

    # Invalid string fallback
    assert parse_iso_delay("NOT_A_DURATION") == (0, 0, "On time", "On time")


@patch("app.datasources.bus_live.requests.get")
def test_bods_live_validate_credentials(mock_get: MagicMock) -> None:
    """Test validate_credentials and validate_tuple handling HTTP responses and network errors."""
    client = BodsLiveClient(api_key="valid-key")

    # 1. Success HTTP 200
    mock_resp = MagicMock(status_code=200, ok=True)
    mock_get.return_value = mock_resp
    valid, msg = client.validate_tuple()
    assert valid is True
    assert "verified successfully" in msg
    assert client.validate_credentials() == {"valid": True, "message": msg}

    # 2. HTTP 401 Unauthorized
    mock_resp.status_code = 401
    mock_resp.ok = False
    valid, msg = client.validate_tuple()
    assert valid is False
    assert "Invalid BODS API key" in msg

    # 3. HTTP 429 Rate Limit
    mock_resp.status_code = 429
    valid, msg = client.validate_tuple()
    assert valid is False
    assert "rate limit exceeded" in msg

    # 4. HTTP 500 Server Error
    mock_resp.status_code = 500
    valid, msg = client.validate_tuple()
    assert valid is False
    assert "server error" in msg

    # 5. Missing API key
    empty_client = BodsLiveClient(api_key="")
    valid, msg = empty_client.validate_tuple()
    assert valid is False
    assert "not configured" in msg

    # 6. Timeout
    mock_get.side_effect = requests.Timeout("Connection timed out")
    valid, msg = client.validate_tuple()
    assert valid is False
    assert "timed out" in msg

    # 7. RequestException
    mock_get.side_effect = requests.ConnectionError("DNS failure")
    valid, msg = client.validate_tuple()
    assert valid is False
    assert "Network error" in msg


@patch("app.datasources.bus_live.requests.get")
def test_bods_live_fetch_live_vehicles_success(mock_get: MagicMock) -> None:
    """Test successful fetching and parsing of London bus vehicles from SIRI-VM feed."""
    mock_resp = MagicMock(status_code=200, ok=True, content=SAMPLE_LONDON_SIRI_VM_XML)
    mock_get.return_value = mock_resp

    client = BodsLiveClient(api_key="test-key")
    now_ref = datetime.datetime(2026, 9, 18, 8, 15, 0, tzinfo=datetime.timezone.utc)
    vehicles = client.fetch_live_vehicles(
        operator_ref="ARHE",
        line_ref="73",
        bounding_box=(-0.2, 51.4, 0.0, 51.6),
        now_utc=now_ref,
    )

    assert len(vehicles) == 3

    # Vehicle 1: Route 73 (Active, delayed)
    v1 = vehicles[0]
    assert v1.vehicle_id == "LTZ1073"
    assert v1.line_name == "73"
    assert v1.operator_ref == "ARHE"
    assert v1.direction == "inbound"
    assert v1.origin_name == "Victoria Station"
    assert v1.destination_name == "Stoke Newington Common"
    assert v1.origin_ref == "490000077E"
    assert v1.destination_ref == "490000077C"
    assert v1.scheduled_dep_time == "08:00"
    assert v1.delay_minutes == 4
    assert v1.delay_status == "Delayed"
    assert v1.formatted_delay == "+4m late"
    assert v1.latitude == 51.5308
    assert v1.longitude == -0.1245
    assert v1.bearing == 45.0
    assert v1.is_active is True

    # Check to_dict serialization
    d1 = v1.to_dict()
    assert d1["vehicle_id"] == "LTZ1073"
    assert d1["line_name"] == "73"
    assert d1["delay_minutes"] == 4

    # Vehicle 2: Route 205 (Active, early)
    v2 = vehicles[1]
    assert v2.vehicle_id == "LTZ1205"
    assert v2.line_name == "205"
    assert v2.delay_minutes == -2
    assert v2.delay_status == "Early"
    assert v2.formatted_delay == "Early -2m"
    assert v2.is_active is True

    # Vehicle 3: Stale / Inactive
    v3 = vehicles[2]
    assert v3.vehicle_id == "LTZ9999"
    assert v3.is_active is False
    assert v3.delay_status == "Parked"
    assert v3.formatted_delay == "Inactive"


@patch("app.datasources.bus_live.requests.get")
def test_bods_live_fetch_live_vehicles_exceptions(mock_get: MagicMock) -> None:
    """Test fetch_live_vehicles exception hierarchy on various HTTP and parse failures."""
    client = BodsLiveClient(api_key="test-key")

    # Missing API key -> DataSourceConfigError
    no_key_client = BodsLiveClient(api_key="")
    with pytest.raises(DataSourceConfigError):
        no_key_client.fetch_live_vehicles()

    # HTTP 401 -> DataSourceAuthError
    mock_get.return_value = MagicMock(status_code=401, ok=False)
    with pytest.raises(DataSourceAuthError):
        client.fetch_live_vehicles()

    # HTTP 429 -> DataSourceRateLimitError
    mock_get.return_value = MagicMock(status_code=429, ok=False)
    with pytest.raises(DataSourceRateLimitError):
        client.fetch_live_vehicles()

    # HTTP 503 -> DataSourceConnectionError
    mock_get.return_value = MagicMock(
        status_code=503, ok=False, text="Service Unavailable"
    )
    with pytest.raises(DataSourceConnectionError):
        client.fetch_live_vehicles()

    # Timeout -> DataSourceConnectionError
    mock_get.side_effect = requests.Timeout("Read timeout")
    with pytest.raises(DataSourceConnectionError):
        client.fetch_live_vehicles()

    # Malformed XML -> DataSourceError
    mock_get.side_effect = None
    mock_get.return_value = MagicMock(
        status_code=200, ok=True, content=b"<BrokenXml>>>"
    )
    with pytest.raises(DataSourceError):
        client.fetch_live_vehicles()


@patch("app.datasources.bus_live.requests.get")
def test_bods_live_get_matching_vehicle(mock_get: MagicMock) -> None:
    """Test matching active vehicle for a scheduled service leg."""
    mock_resp = MagicMock(status_code=200, ok=True, content=SAMPLE_LONDON_SIRI_VM_XML)
    mock_get.return_value = mock_resp

    client = BodsLiveClient(api_key="test-key")

    # 1. Exact match on scheduled origin departure time 08:00
    match = client.get_matching_vehicle(
        line_name="73",
        scheduled_time="08:00",
        origin_ref="490000077E",
    )
    assert match is not None
    assert match.vehicle_id == "LTZ1073"

    # 2. Tolerant match within +/- 5 minutes (e.g. scheduled at 08:03, vehicle aimed 08:00)
    match_tolerant = client.get_matching_vehicle(
        line_name="73",
        scheduled_time="08:03",
    )
    assert match_tolerant is not None
    assert match_tolerant.vehicle_id == "LTZ1073"

    # 3. Match by line and destination reference
    match_dest = client.get_matching_vehicle(
        line_name="205",
        destination_ref="490000028B",
    )
    assert match_dest is not None
    assert match_dest.vehicle_id == "LTZ1205"

    # 4. Non-matching line -> None
    assert client.get_matching_vehicle(line_name="999") is None

    # 5. Empty line -> None
    assert client.get_matching_vehicle(line_name="") is None


@patch("app.datasources.bus_live.requests.get")
def test_validate_service_credentials_bus_live(mock_get: MagicMock) -> None:
    """Test validation dispatcher for 'bus_live' service."""
    mock_get.return_value = MagicMock(status_code=200, ok=True)
    valid, msg, extra = validate_service_credentials(
        "bus_live",
        {"bus_api_key": "test-bods-token"},
    )
    assert valid is True
    assert "verified successfully" in msg
    assert extra == {}

    # Validation HTTP 400 failure
    mock_get.return_value = MagicMock(status_code=400, ok=False)
    client = BodsLiveClient(api_key="bad-req")
    valid, msg = client.validate_tuple()
    assert valid is False
    assert "BODS validation failed (HTTP 400)" in msg

    # Unexpected exception in validate_tuple
    mock_get.side_effect = RuntimeError("Unexpected failure")
    valid, msg = client.validate_tuple()
    assert valid is False
    assert "Unexpected error" in msg


def test_bods_live_clean_tag_and_namespaceless_xml() -> None:
    """Test XML parsing when payload lacks standard SIRI XML namespace prefixes."""
    from app.datasources.bus_live import _clean_tag

    assert (
        _clean_tag("{http://www.siri.org.uk/siri}VehicleActivity") == "VehicleActivity"
    )
    assert _clean_tag("VehicleActivity") == "VehicleActivity"

    namespaceless_xml = b"""<Siri>
      <ServiceDelivery>
        <VehicleMonitoringDelivery>
          <VehicleActivity>
            <RecordedAtTime>2026-09-18T08:14:00+00:00</RecordedAtTime>
            <MonitoredVehicleJourney>
              <LineRef>30</LineRef>
              <OperatorRef>FGG</OperatorRef>
              <VehicleRef>BUS301</VehicleRef>
              <OriginRef>490000001A</OriginRef>
              <OriginName>Portman Square</OriginName>
              <DestinationRef>490000002B</DestinationRef>
              <DestinationName>Hackney Wick</DestinationName>
              <OriginAimedDepartureTime>08:10:00</OriginAimedDepartureTime>
              <Delay>PT1M</Delay>
              <Latitude>invalid_lat</Latitude>
              <Longitude>invalid_lon</Longitude>
              <Bearing>invalid_bearing</Bearing>
            </MonitoredVehicleJourney>
          </VehicleActivity>
        </VehicleMonitoringDelivery>
      </ServiceDelivery>
    </Siri>"""

    client = BodsLiveClient(api_key="test-key")
    now_ref = datetime.datetime(2026, 9, 18, 8, 15, 0, tzinfo=datetime.timezone.utc)
    vehicles = client._parse_siri_vm_xml(namespaceless_xml, now_utc=now_ref)

    assert len(vehicles) == 1
    v = vehicles[0]
    assert v.line_name == "30"
    assert v.vehicle_id == "BUS301"
    assert v.scheduled_dep_time == "08:10"
    assert v.latitude is None
    assert v.longitude is None
    assert v.bearing is None

    # Test malformed timestamp and activity missing MonitoredVehicleJourney
    edge_xml = b"""<Siri>
      <ServiceDelivery>
        <VehicleMonitoringDelivery>
          <VehicleActivity>
            <RecordedAtTime>NOT_A_DATE</RecordedAtTime>
          </VehicleActivity>
          <VehicleActivity>
            <RecordedAtTime>INVALID</RecordedAtTime>
            <MonitoredVehicleJourney>
              <LineRef>30</LineRef>
              <VehicleRef>BUS302</VehicleRef>
            </MonitoredVehicleJourney>
          </VehicleActivity>
        </VehicleMonitoringDelivery>
      </ServiceDelivery>
    </Siri>"""
    vehicles_edge = client._parse_siri_vm_xml(edge_xml, now_utc=now_ref)
    assert len(vehicles_edge) == 1
    assert vehicles_edge[0].recorded_at is None
    assert vehicles_edge[0].vehicle_id == "BUS302"


@patch("app.datasources.bus_live.requests.get")
def test_bods_live_get_matching_vehicle_origin_and_fallbacks(
    mock_get: MagicMock,
) -> None:
    """Test get_matching_vehicle with origin matching, first active fallback, and errors."""
    mock_resp = MagicMock(status_code=200, ok=True, content=SAMPLE_LONDON_SIRI_VM_XML)
    mock_get.return_value = mock_resp

    client = BodsLiveClient(api_key="test-key")

    # Match by origin_ref
    match_origin = client.get_matching_vehicle(
        line_name="73",
        origin_ref="490000077E",
    )
    assert match_origin is not None
    assert match_origin.vehicle_id == "LTZ1073"

    # Match fallback to first active vehicle when no time/origin/destination specified
    match_first = client.get_matching_vehicle(line_name="73")
    assert match_first is not None
    assert match_first.vehicle_id == "LTZ1073"

    # Exception during query -> returns None gracefully
    mock_get.side_effect = RuntimeError("Network crashed")
    assert client.get_matching_vehicle(line_name="73") is None
