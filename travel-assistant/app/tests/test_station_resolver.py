"""Unit tests for UK rail station code and TIPLOC to CRS resolution."""

from app.models.transit import Stop
from app.services.dispatcher.station_resolver import resolve_station_crs


def test_resolve_station_crs_none_or_empty() -> None:
    """Test resolving None or empty station codes returns None."""
    assert resolve_station_crs(None) is None
    assert resolve_station_crs("") is None
    assert resolve_station_crs("   ") is None


def test_resolve_station_crs_standard_3_letter() -> None:
    """Test standard 3-letter CRS codes resolve to uppercase."""
    assert resolve_station_crs("KGX") == "KGX"
    assert resolve_station_crs("kgx") == "KGX"
    assert resolve_station_crs("PAD") == "PAD"
    assert resolve_station_crs("eus") == "EUS"


def test_resolve_station_crs_namespaced_codes() -> None:
    """Test transit namespaced identifiers resolve properly."""
    assert resolve_station_crs("naptan:KGX") == "KGX"
    assert resolve_station_crs("atco:PAD") == "PAD"
    assert resolve_station_crs("tiploc:EUS") == "EUS"
    assert resolve_station_crs("atco:9100KNGX") == "KGX"
    assert resolve_station_crs("atco:9100PADTON") == "PAD"
    assert resolve_station_crs("tiploc:EUSTON") == "EUS"


def test_resolve_station_crs_atco_and_tiploc() -> None:
    """Test ATCO codes (9100 prefix) and bare TIPLOC codes for London rail terminals."""
    # King's Cross (TIPLOC: KNGX, CRS: KGX)
    assert resolve_station_crs("9100KNGX") == "KGX"
    assert resolve_station_crs("KNGX") == "KGX"

    # Paddington (TIPLOC: PADTON, CRS: PAD)
    assert resolve_station_crs("9100PADTON") == "PAD"
    assert resolve_station_crs("PADTON") == "PAD"

    # Euston (TIPLOC: EUSTON, CRS: EUS)
    assert resolve_station_crs("9100EUSTON") == "EUS"
    assert resolve_station_crs("EUSTON") == "EUS"

    # St Pancras International (TIPLOC: STPX, CRS: STP)
    assert resolve_station_crs("9100STPX") == "STP"
    assert resolve_station_crs("STPX") == "STP"

    # Direct 3-letter suffix on ATCO code
    assert resolve_station_crs("9100KGX") == "KGX"


def test_resolve_station_crs_db_lookup(app) -> None:
    """Test resolving station code via database Stop table lookup."""
    with app.app_context():
        # Create a test station stop in DB
        Stop.create(
            atco_code="9100TESTSTN",
            naptan_code="TST",
            name="London Test Station",
            stop_type="rail_station",
            latitude=51.5000,
            longitude=-0.1000,
        )

        assert resolve_station_crs("9100TESTSTN") == "TST"
        assert resolve_station_crs("TESTSTN") == "TST"
        assert resolve_station_crs("atco:9100TESTSTN") == "TST"


def test_resolve_station_crs_unresolvable() -> None:
    """Test non-rail stops or invalid strings safely return None."""
    # Bus stop ATCO code
    assert resolve_station_crs("490000077E") is None
    assert resolve_station_crs("atco:490000077E") is None

    # Completely invalid codes
    assert resolve_station_crs("NONEXISTENT_STATION_CODE") is None
    assert resolve_station_crs("12345") is None
