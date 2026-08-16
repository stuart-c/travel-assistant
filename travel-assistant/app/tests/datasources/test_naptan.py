"""Unit tests for NaptanClient."""

from unittest.mock import MagicMock, patch
import pytest
import requests
from flask import Flask

from app.datasources.naptan import NaptanClient, classify_stop_type
from app.datasources.exceptions import (
    DataSourceConnectionError,
    DataSourceError,
)
from app.models.setting import Setting


def test_classify_stop_type() -> None:
    """Test classification of NaPTAN StopTypes into canonical categories."""
    assert classify_stop_type("BCT") == "bus"
    assert classify_stop_type("BCS") == "bus"
    assert classify_stop_type("BCP") == "bus"
    assert classify_stop_type("BST") == "bus"
    assert classify_stop_type("RLY") == "rail"
    assert classify_stop_type("RPL") == "rail"
    assert classify_stop_type("RSE") == "rail"
    assert classify_stop_type("MET") == "metro"
    assert classify_stop_type("PLT") == "metro"
    assert classify_stop_type("TMU") == "tram"
    assert classify_stop_type("FTD") == "ferry"
    assert classify_stop_type("FER") == "ferry"
    assert classify_stop_type("AIR") == "air"
    assert classify_stop_type("GAT") == "air"
    assert classify_stop_type("TXR") == "other"
    assert classify_stop_type("") == "bus"


def test_naptan_from_settings(app: Flask) -> None:
    """Test NaptanClient initialisation from settings."""
    with app.app_context():
        client = NaptanClient.from_settings()
        assert client.provider_name == "naptan"
        assert client.validate_credentials()["valid"] is True

        Setting.set_val("naptan_stops_url", "https://custom.naptan.api/stops.csv")
        custom_client = NaptanClient.from_settings()
        assert custom_client.endpoint == "https://custom.naptan.api/stops.csv"


@patch("app.datasources.naptan.requests.get")
def test_naptan_fetch_stops_success(mock_get: MagicMock) -> None:
    """Test fetch_stops parses CSV content correctly."""
    csv_data = """ATCOCode,NaptanCode,StopType,CommonName,Indicator,LocalityName,Latitude,Longitude
0100BRP90310,bstpwat,BCT,Broad Quay,Stop C3,Bristol,51.452,-2.597
9100PADTON,PAD,RLY,London Paddington,Platforms,London,51.517,-0.177
0100BRP90311,,BCT,Anchor Road,,Bristol,invalid_lat,invalid_lon
,,Empty Row,,,,
"""
    mock_get.return_value = MagicMock(status_code=200, text=csv_data)

    client = NaptanClient()
    stops = client.fetch_stops()
    assert len(stops) == 3
    assert stops[0]["atco_code"] == "0100BRP90310"
    assert stops[0]["naptan_code"] == "bstpwat"
    assert stops[0]["stop_type"] == "bus"
    assert stops[0]["name"] == "Broad Quay"
    assert stops[0]["indicator"] == "Stop C3"
    assert stops[0]["latitude"] == 51.452
    assert stops[0]["longitude"] == -2.597

    # Rail station
    assert stops[1]["atco_code"] == "9100PADTON"
    assert stops[1]["naptan_code"] == "PAD"
    assert stops[1]["stop_type"] == "rail"
    assert stops[1]["name"] == "London Paddington"

    # Stop 3 has invalid lat/lon
    assert stops[2]["atco_code"] == "0100BRP90311"
    assert stops[2]["naptan_code"] is None
    assert stops[2]["latitude"] is None
    assert stops[2]["longitude"] is None


@patch("app.datasources.naptan.requests.get")
def test_naptan_fetch_stops_limit(mock_get: MagicMock) -> None:
    """Test fetch_stops respects the limit argument."""
    csv_data = """ATCOCode,CommonName
0100A,Stop A
0100B,Stop B
0100C,Stop C
"""
    mock_get.return_value = MagicMock(status_code=200, text=csv_data)
    client = NaptanClient()
    stops = client.fetch_stops(limit=2)
    assert len(stops) == 2


@patch("app.datasources.naptan.requests.get")
def test_naptan_fetch_stops_errors(mock_get: MagicMock) -> None:
    """Test fetch_stops error handling."""
    client = NaptanClient()

    # Timeout
    mock_get.side_effect = requests.exceptions.Timeout("Timeout")
    with pytest.raises(DataSourceConnectionError):
        client.fetch_stops()

    # RequestException
    mock_get.side_effect = requests.exceptions.ConnectionError("Refused")
    with pytest.raises(DataSourceConnectionError):
        client.fetch_stops()

    # Generic Exception
    mock_get.side_effect = RuntimeError("Crash")
    with pytest.raises(DataSourceError):
        client.fetch_stops()


@patch("app.datasources.naptan.requests.get")
def test_naptan_fetch_rail_stations_success(mock_get: MagicMock) -> None:
    """Test fetch_rail_stations parses rail station CSV content correctly."""
    csv_data = """ATCOCode,CrsRef,CommonName,TiplocRef,Latitude,Longitude,StopType,Operator
9100OXFD,OXF,Oxford Rail Station,OXFD,51.753,-1.270,RLY,Great Western Railway
9100DID,DID,Didcot Parkway,DIDCOT,51.610,-1.240,RLY,Great Western Railway
9100PAD,PAD,London Paddington,PADTON,51.517,-0.178,RLY,Network Rail
0100BRP90310,,Broad Quay,,51.452,-2.597,BCT,First Bus
,,Empty Station,,,,RLY,
"""
    mock_get.return_value = MagicMock(status_code=200, text=csv_data)

    client = NaptanClient()
    stations = client.fetch_rail_stations()
    assert len(stations) == 3
    assert stations[0]["crs_code"] == "OXF"
    assert stations[0]["name"] == "Oxford Rail Station"
    assert stations[0]["tiploc_code"] == "OXFD"
    assert stations[0]["latitude"] == 51.753
    assert stations[0]["longitude"] == -1.270
    assert stations[0]["operator"] == "Great Western Railway"

    assert stations[1]["crs_code"] == "DID"
    assert stations[2]["crs_code"] == "PAD"


@patch("app.datasources.naptan.requests.get")
def test_naptan_fetch_rail_stations_limit_and_errors(mock_get: MagicMock) -> None:
    """Test fetch_rail_stations limit and error branches."""
    csv_data = """ATCOCode,CrsRef,CommonName,StopType
9100A,AAA,Station A,RLY
9100B,BBB,Station B,RLY
9100C,CCC,Station C,RLY
"""
    mock_get.return_value = MagicMock(status_code=200, text=csv_data)
    client = NaptanClient()
    stations = client.fetch_rail_stations(limit=2)
    assert len(stations) == 2

    # Timeout
    mock_get.side_effect = requests.exceptions.Timeout("Timeout")
    with pytest.raises(DataSourceConnectionError):
        client.fetch_rail_stations()

    # RequestException
    mock_get.side_effect = requests.exceptions.ConnectionError("Refused")
    with pytest.raises(DataSourceConnectionError):
        client.fetch_rail_stations()

    # Generic Exception
    mock_get.side_effect = RuntimeError("Crash")
    with pytest.raises(DataSourceError):
        client.fetch_rail_stations()
