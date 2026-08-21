"""Unit tests for RailReferencesClient."""

from unittest.mock import MagicMock, patch

import pytest
import requests
from flask import Flask

from app.datasources.exceptions import (
    DataSourceConnectionError,
    DataSourceError,
)
from app.datasources.naptan import (
    DEFAULT_RAIL_REFERENCES_URL,
    RailReferencesClient,
)
from app.models.setting import Setting


def test_rail_references_client_from_settings_defaults(app: Flask) -> None:
    """Test RailReferencesClient.from_settings uses the default NaPTAN URL."""
    with app.app_context():
        client = RailReferencesClient.from_settings()
        assert client.endpoint == DEFAULT_RAIL_REFERENCES_URL
        assert client.provider_name == "naptan_rail_references"


def test_rail_references_client_from_settings_custom_url(app: Flask) -> None:
    """Test RailReferencesClient.from_settings picks up a custom URL from settings."""
    with app.app_context():
        Setting.set_val(
            "naptan_rail_references_url",
            "https://custom.naptan.api/RailReferences.csv",
        )
        client = RailReferencesClient.from_settings()
        assert client.endpoint == "https://custom.naptan.api/RailReferences.csv"


def test_rail_references_validate_credentials() -> None:
    """Test validate_credentials returns valid=True (public open data)."""
    client = RailReferencesClient()
    result = client.validate_credentials()
    assert result["valid"] is True
    assert "public" in result["message"].lower()


@patch("app.datasources.naptan.requests.get")
def test_fetch_rail_references_success(mock_get: MagicMock) -> None:
    """Test fetch_rail_references parses standard CSV columns correctly."""
    csv_data = (
        "TiplocCode,AtcoCode,CrsCode,StationName\n"
        "PADTON,9100PADTON,PAD,London Paddington\n"
        "OXFD,9100OXFD,OXF,Oxford\n"
        "DIDCOT,9100DID,DID,Didcot Parkway\n"
    )
    mock_get.return_value = MagicMock(status_code=200, text=csv_data)

    client = RailReferencesClient()
    refs = client.fetch_rail_references()

    assert len(refs) == 3

    assert refs[0]["tiploc"] == "PADTON"
    assert refs[0]["atco_code"] == "9100PADTON"
    assert refs[0]["crs_code"] == "PAD"

    assert refs[1]["tiploc"] == "OXFD"
    assert refs[1]["atco_code"] == "9100OXFD"
    assert refs[1]["crs_code"] == "OXF"

    assert refs[2]["tiploc"] == "DIDCOT"
    assert refs[2]["crs_code"] == "DID"


@patch("app.datasources.naptan.requests.get")
def test_fetch_rail_references_tiploc_uppercased(mock_get: MagicMock) -> None:
    """Test TIPLOC and CRS values are normalised to uppercase."""
    csv_data = "TiplocCode,AtcoCode,CrsCode\n" "padton,9100PADTON,pad\n"
    mock_get.return_value = MagicMock(status_code=200, text=csv_data)

    client = RailReferencesClient()
    refs = client.fetch_rail_references()

    assert refs[0]["tiploc"] == "PADTON"
    assert refs[0]["crs_code"] == "PAD"


@patch("app.datasources.naptan.requests.get")
def test_fetch_rail_references_skips_rows_without_tiploc(mock_get: MagicMock) -> None:
    """Test rows with an empty or missing TiplocCode are silently skipped."""
    csv_data = (
        "TiplocCode,AtcoCode,CrsCode\n"
        "PADTON,9100PADTON,PAD\n"
        ",9100EMPTY,XXX\n"
        "OXFD,9100OXFD,OXF\n"
    )
    mock_get.return_value = MagicMock(status_code=200, text=csv_data)

    client = RailReferencesClient()
    refs = client.fetch_rail_references()

    assert len(refs) == 2
    assert refs[0]["tiploc"] == "PADTON"
    assert refs[1]["tiploc"] == "OXFD"


@patch("app.datasources.naptan.requests.get")
def test_fetch_rail_references_nullable_fields(mock_get: MagicMock) -> None:
    """Test rows with empty AtcoCode or CrsCode yield None for those fields."""
    csv_data = "TiplocCode,AtcoCode,CrsCode\n" "SOMEJN,,\n"
    mock_get.return_value = MagicMock(status_code=200, text=csv_data)

    client = RailReferencesClient()
    refs = client.fetch_rail_references()

    assert len(refs) == 1
    assert refs[0]["tiploc"] == "SOMEJN"
    assert refs[0]["atco_code"] is None
    assert refs[0]["crs_code"] is None


@patch("app.datasources.naptan.requests.get")
def test_fetch_rail_references_limit(mock_get: MagicMock) -> None:
    """Test fetch_rail_references respects the limit argument."""
    csv_data = (
        "TiplocCode,AtcoCode,CrsCode\n"
        "PADTON,9100PADTON,PAD\n"
        "OXFD,9100OXFD,OXF\n"
        "DIDCOT,9100DID,DID\n"
    )
    mock_get.return_value = MagicMock(status_code=200, text=csv_data)

    client = RailReferencesClient()
    refs = client.fetch_rail_references(limit=2)

    assert len(refs) == 2


@patch("app.datasources.naptan.requests.get")
def test_fetch_rail_references_timeout(mock_get: MagicMock) -> None:
    """Test fetch_rail_references raises DataSourceConnectionError on timeout."""
    mock_get.side_effect = requests.exceptions.Timeout("timed out")
    client = RailReferencesClient()
    with pytest.raises(DataSourceConnectionError, match="timed out"):
        client.fetch_rail_references()


@patch("app.datasources.naptan.requests.get")
def test_fetch_rail_references_connection_error(mock_get: MagicMock) -> None:
    """Test fetch_rail_references raises DataSourceConnectionError on network failure."""
    mock_get.side_effect = requests.exceptions.ConnectionError("refused")
    client = RailReferencesClient()
    with pytest.raises(DataSourceConnectionError):
        client.fetch_rail_references()


@patch("app.datasources.naptan.requests.get")
def test_fetch_rail_references_generic_error(mock_get: MagicMock) -> None:
    """Test fetch_rail_references raises DataSourceError on unexpected exceptions."""
    mock_get.side_effect = RuntimeError("unexpected crash")
    client = RailReferencesClient()
    with pytest.raises(DataSourceError):
        client.fetch_rail_references()
