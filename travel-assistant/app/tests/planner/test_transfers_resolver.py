"""Unit tests for transfer hierarchy resolution, endpoint names, and time utilities."""

from __future__ import annotations

from flask import Flask
import pytest

from app.services.planner.exceptions import NoCorridorPathError
from app.services.planner.route_finder import find_routes
from app.services.planner.transfers import (
    format_minutes_to_time,
    parse_time_to_minutes,
    resolve_endpoint_name,
    resolve_transfer_duration,
)


def test_time_parsing_helpers() -> None:
    """Verify time parsing and formatting utility functions."""
    assert parse_time_to_minutes("08:30") == 510
    assert parse_time_to_minutes("00:00") == 0
    assert parse_time_to_minutes("23:59") == 1439
    assert parse_time_to_minutes("invalid") is None
    assert parse_time_to_minutes("") is None

    assert format_minutes_to_time(510) == "08:30"
    assert format_minutes_to_time(0) == "00:00"
    assert format_minutes_to_time(1439) == "23:59"


def test_resolve_endpoint_name(seeded_planner: Flask) -> None:
    """Verify human-readable name resolution for locations and transit stops."""
    with seeded_planner.app_context():
        assert resolve_endpoint_name("ha", "ha:home") == "Home Residence"
        assert (
            resolve_endpoint_name("custom", "custom:parents_house")
            == "Parents' Residence"
        )
        assert (
            resolve_endpoint_name("bus", "490000077E")
            == "King's Cross Station (Stop E)"
        )
        assert (
            resolve_endpoint_name("rail", "9100KNGX") == "London King's Cross (Station)"
        )
        assert resolve_endpoint_name("custom", "nonexistent") == "nonexistent"


def test_transfer_resolution_hierarchy(seeded_planner: Flask) -> None:
    """Verify 3-tier transfer hierarchy: walking/platform_transfers -> stop_interchanges -> default 5 min."""
    with seeded_planner.app_context():
        # Priority 1: Exact match in walking table
        walk_res = resolve_transfer_duration("ha", "ha:home", "bus", "490000077E")
        assert walk_res is not None
        assert walk_res[0] == 4
        assert walk_res[1] == "walk"

        # Priority 1: Exact match in platform_transfers table
        plat_res = resolve_transfer_duration(
            "rail",
            "9100EUSTON",
            "rail",
            "9100EUSTON",
            from_platform="1",
            to_platform="4",
        )
        assert plat_res is not None
        assert plat_res[0] == 3
        assert plat_res[1] == "platform_transfer"

        # Priority 2: Nearby stop interchange in stop_interchanges table
        interchange_res = resolve_transfer_duration(
            "bus", "490000077C", "rail", "9100EUSTON"
        )
        assert interchange_res is not None
        assert interchange_res[0] == 2
        assert interchange_res[1] == "interchange"
        assert interchange_res[2] == 120

        # Priority 3 Fallback: Default 5 min for unconfigured platform interchange
        fallback_plat = resolve_transfer_duration("rail", "9100FPK", "rail", "9100FPK")
        assert fallback_plat is not None
        assert fallback_plat[0] == 5
        assert fallback_plat[1] == "platform_transfer"

        # Unconnected endpoints return None
        assert (
            resolve_transfer_duration("ha", "ha:home", "custom", "custom:isolated_spot")
            is None
        )


def test_date_and_day_resolution_edge_cases(seeded_planner: Flask) -> None:
    """Verify target_date strings, weekday names, and date validity filtering."""
    with seeded_planner.app_context():
        # Valid date string
        routes = find_routes(
            "rail",
            "9100EUSTON",
            "rail",
            "9100MNCR",
            target_date="2026-08-24",  # A Monday
        )
        assert len(routes) == 1

        # Full day name "monday"
        routes_day = find_routes(
            "rail", "9100EUSTON", "rail", "9100MNCR", days_of_week=["monday"]
        )
        assert len(routes_day) == 1

        # Invalid date string falls back gracefully
        routes_inv = find_routes(
            "rail", "9100EUSTON", "rail", "9100MNCR", target_date="not-a-date"
        )
        assert len(routes_inv) == 1

        # Date out of validity range (start_date=2026-01-01, end_date=2026-12-31)
        with pytest.raises(NoCorridorPathError):
            find_routes(
                "bus",
                "490000077E",
                "bus",
                "490000077C",
                target_date="2025-05-01",  # Before start_date
                days_of_week=["mon"],
            )
