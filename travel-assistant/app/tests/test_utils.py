"""Unit tests for shared app.utils (geo and transit_time)."""

import datetime
from flask import Flask

from app.models.location import Location
from app.models.transit import Stop
from app.utils.geo import haversine_distance_m, resolve_endpoint_coordinates
from app.utils.transit_time import (
    CODE_TO_TIMETABLE_ATTR,
    DAY_NAME_TO_CODE,
    VALID_DAYS,
    format_minutes_to_time,
    format_seconds_to_hh_mm,
    get_day_code,
    parse_iso_duration_seconds,
    parse_time_str_to_seconds,
    parse_time_to_minutes,
)


def test_haversine_distance_m() -> None:
    """Test haversine distance calculation in metres."""
    # Zero distance for identical points
    assert haversine_distance_m(51.5308, -0.1238, 51.5308, -0.1238) == 0.0

    # Distance between King's Cross and Euston (~700m)
    dist = haversine_distance_m(51.5308, -0.1238, 51.5284, -0.1331)
    assert 600.0 < dist < 800.0


def test_resolve_endpoint_coordinates(app: Flask) -> None:
    """Test resolving coordinates for locations and transit stops."""
    with app.app_context():
        Location.delete().execute()
        Stop.delete().execute()

        Location.create(
            id="ha:home",
            name="Home",
            latitude=51.5000,
            longitude=-0.1000,
            ha=True,
        )
        Location.create(
            id="custom:office",
            name="Office",
            latitude=51.5200,
            longitude=-0.0800,
            ha=False,
        )
        Stop.create(
            atco_code="490000077E",
            naptan_code="490000077E",
            name="Kings Cross Station",
            stop_type="bus",
            latitude=51.5308,
            longitude=-0.1238,
        )

        # 1. HA zone
        lat, lon, name = resolve_endpoint_coordinates("ha", "ha:home")
        assert lat == 51.5000
        assert lon == -0.1000
        assert name == "Home"

        # 2. Custom location
        lat, lon, name = resolve_endpoint_coordinates("custom", "custom:office")
        assert lat == 51.5200
        assert lon == -0.0800
        assert name == "Office"

        # 3. Stop
        lat, lon, name = resolve_endpoint_coordinates("bus", "atco:490000077E")
        assert lat == 51.5308
        assert lon == -0.1238
        assert name == "Kings Cross Station"

        # 4. Stop by name lookup
        lat, lon, name = resolve_endpoint_coordinates("bus", "Kings Cross Station")
        assert lat == 51.5308
        assert lon == -0.1238

        # 5. Case-insensitive and general Location fallback
        lat, lon, name = resolve_endpoint_coordinates("walk", "home")
        assert lat == 51.5000
        assert lon == -0.1000
        assert name == "Home"

        lat, lon, name = resolve_endpoint_coordinates("ha", "HOME")
        assert lat == 51.5000
        assert lon == -0.1000

        lat, lon, name = resolve_endpoint_coordinates("custom", "OFFICE")
        assert lat == 51.5200
        assert lon == -0.0800

        # 6. Non-existent and empty
        lat, lon, name = resolve_endpoint_coordinates("unknown", "unknown:999")
        assert lat is None and lon is None and name is None

        lat, lon, name = resolve_endpoint_coordinates("", "")
        assert lat is None and lon is None and name is None


def test_get_day_code() -> None:
    """Test day code resolution from dates."""
    monday = datetime.date(2026, 9, 14)  # Monday
    assert get_day_code(monday) == "mon"

    sunday = datetime.datetime(2026, 9, 20, 15, 30)  # Sunday
    assert get_day_code(sunday) == "sun"


def test_time_to_minutes_and_format() -> None:
    """Test minutes conversion and formatting."""
    assert parse_time_to_minutes("00:00") == 0
    assert parse_time_to_minutes("08:30") == 510
    assert parse_time_to_minutes("23:59") == 1439
    assert parse_time_to_minutes("08:30:45") == 510
    assert parse_time_to_minutes("") is None
    assert parse_time_to_minutes(None) is None
    assert parse_time_to_minutes("invalid") is None

    assert format_minutes_to_time(0) == "00:00"
    assert format_minutes_to_time(510) == "08:30"
    assert format_minutes_to_time(1440) == "00:00"


def test_iso_duration_parsing() -> None:
    """Test ISO 8601 duration string parsing to seconds."""
    assert parse_iso_duration_seconds("PT10M") == 600
    assert parse_iso_duration_seconds("PT1H30M") == 5400
    assert parse_iso_duration_seconds("PT45S") == 45
    assert parse_iso_duration_seconds("PT1M30S") == 90
    assert parse_iso_duration_seconds("P1D") == 86400
    assert parse_iso_duration_seconds("") == 0
    assert parse_iso_duration_seconds(None) == 0
    assert parse_iso_duration_seconds("not_an_iso_string") == 0


def test_seconds_conversions() -> None:
    """Test seconds parsing and formatting."""
    assert parse_time_str_to_seconds("01:30:15") == 5415
    assert parse_time_str_to_seconds("01:30") == 5400
    assert parse_time_str_to_seconds(None) is None
    assert parse_time_str_to_seconds("invalid") is None

    assert format_seconds_to_hh_mm(5400) == "01:30"
    assert format_seconds_to_hh_mm(0) == "00:00"


def test_constants() -> None:
    """Verify standard transport day constants."""
    assert "mon" in VALID_DAYS
    assert DAY_NAME_TO_CODE["monday"] == "mon"
    assert CODE_TO_TIMETABLE_ATTR["mon"] == "monday"
