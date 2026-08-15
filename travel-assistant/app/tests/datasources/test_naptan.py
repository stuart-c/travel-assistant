"""Unit tests for NaptanClient."""

from unittest.mock import MagicMock, patch
import pytest
import requests
from flask import Flask

from app.datasources.naptan import NaptanClient
from app.datasources.exceptions import (
    DataSourceConnectionError,
    DataSourceError,
)
from app.db.settings import SettingsRepository


def test_naptan_from_settings(app: Flask) -> None:
    """Test NaptanClient initialisation from SettingsRepository."""
    with app.app_context():
        repo = SettingsRepository()
        client = NaptanClient.from_settings(repo)
        assert client.provider_name == "naptan"
        assert client.validate_credentials()["valid"] is True


@patch("requests.get")
def test_naptan_fetch_stops_success(mock_get: MagicMock) -> None:
    """Test fetch_stops parses CSV content correctly."""
    csv_data = """ATCOCode,NaptanCode,CommonName,Indicator,LocalityName,Latitude,Longitude
0100BRP90310,bstpwat,Broad Quay,Stop C3,Bristol,51.452,-2.597
0100BRP90311,,Anchor Road,,Bristol,invalid_lat,invalid_lon
,,Empty Row,,,,
"""
    mock_get.return_value = MagicMock(status_code=200, text=csv_data)

    client = NaptanClient()
    stops = client.fetch_stops()
    assert len(stops) == 2
    assert stops[0]["atco_code"] == "0100BRP90310"
    assert stops[0]["naptan_code"] == "bstpwat"
    assert stops[0]["name"] == "Broad Quay"
    assert stops[0]["indicator"] == "Stop C3"
    assert stops[0]["latitude"] == 51.452
    assert stops[0]["longitude"] == -2.597

    # Stop 2 has invalid lat/lon
    assert stops[1]["atco_code"] == "0100BRP90311"
    assert stops[1]["naptan_code"] is None
    assert stops[1]["latitude"] is None
    assert stops[1]["longitude"] is None


@patch("requests.get")
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


@patch("requests.get")
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
