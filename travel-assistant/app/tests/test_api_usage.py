"""Unit tests for API usage tracking, caching, cost calculation, and quota enforcement."""

import datetime
import time
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from app.datasources.exceptions import DataSourceRateLimitError
from app.datasources.google_maps import GoogleMapsClient
from app.models.api_usage import ApiUsageLog
from app.models.setting import Setting
from app.services.api_tracker import (
    ApiCache,
    calculate_cost,
    check_quota,
    get_quota_limits,
    get_recent_calls,
    get_usage_summary,
    global_api_cache,
    record_api_call,
)


def test_api_cache_basic_and_expiry() -> None:
    """Test ApiCache set, get, TTL expiration, and statistics."""
    cache = ApiCache()

    # Initial stats
    stats = cache.stats()
    assert stats["hits"] == 0
    assert stats["misses"] == 0
    assert stats["active_entries"] == 0

    # Set and get
    cache.set("google_maps", "key1", {"routes": [1, 2, 3]}, ttl_seconds=10)
    assert cache.get("google_maps", "key1") == {"routes": [1, 2, 3]}
    assert cache.get("google_maps", "nonexistent") is None

    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["hit_rate_pct"] == 50.0

    # Short TTL expiry
    cache.set("google_maps", "short_key", "temporary", ttl_seconds=1)
    time.sleep(1.05)
    assert cache.get("google_maps", "short_key") is None


def test_api_cache_clear() -> None:
    """Test clearing cache by provider and completely."""
    cache = ApiCache()
    cache.set("google_maps", "k1", "val1")
    cache.set("google_maps", "k2", "val2")
    cache.set("darwin", "k3", "val3")

    assert cache.stats()["active_entries"] == 3

    # Clear only google_maps
    cleared = cache.clear(provider="google_maps")
    assert cleared == 2
    assert cache.get("google_maps", "k1") is None
    assert cache.get("darwin", "k3") == "val3"

    # Clear all
    cleared_all = cache.clear()
    assert cleared_all == 1
    assert cache.stats()["active_entries"] == 0


def test_calculate_cost() -> None:
    """Test cost estimation for different providers and endpoints."""
    assert calculate_cost("google_maps", "compute_transit_routes") == 0.010
    assert calculate_cost("google_maps", "directions") == 0.005
    assert calculate_cost("google_maps", "geocode") == 0.005
    assert calculate_cost("darwin", "fastest_departures") == 0.0
    assert calculate_cost("bods", "siri_vm") == 0.0
    assert calculate_cost("unknown", "unknown") == 0.0


def test_record_api_call_and_model(app: Flask) -> None:
    """Test logging an external API call to the database."""
    with app.app_context():
        log_entry = record_api_call(
            provider="google_maps",
            endpoint="compute_transit_routes",
            caller="departure_monitor",
            query_summary="London Kings Cross -> Cambridge",
            status_code=200,
            duration_ms=45,
            is_cached=False,
        )
        assert log_entry is not None
        assert log_entry.id is not None
        assert log_entry.provider == "google_maps"
        assert log_entry.endpoint == "compute_transit_routes"
        assert log_entry.caller == "departure_monitor"
        assert log_entry.status_code == 200
        assert log_entry.duration_ms == 45
        assert log_entry.is_cached is False
        assert log_entry.estimated_cost_usd == 0.010

        # Cached entry has 0 duration and 0 cost
        cached_log = record_api_call(
            provider="google_maps",
            endpoint="compute_transit_routes",
            caller="departure_monitor",
            is_cached=True,
        )
        assert cached_log is not None
        assert cached_log.is_cached is True
        assert cached_log.estimated_cost_usd == 0.0

        data = log_entry.to_dict()
        assert "created_at_iso" in data
        assert data["provider"] == "google_maps"


def test_quota_limits_and_enforcement(app: Flask) -> None:
    """Test checking and enforcing daily and monthly quotas."""
    with app.app_context():
        # Clean state
        ApiUsageLog.delete().execute()
        Setting.set_val("google_maps_daily_limit", 3)
        Setting.set_val("google_maps_monthly_limit", 10)

        daily, monthly = get_quota_limits("google_maps")
        assert daily == 3
        assert monthly == 10

        # Initial check passes
        allowed, msg = check_quota("google_maps")
        assert allowed is True
        assert msg == ""

        # Record 2 uncached calls
        record_api_call("google_maps", "geocode", is_cached=False)
        record_api_call("google_maps", "geocode", is_cached=False)
        allowed, _ = check_quota("google_maps")
        assert allowed is True

        # Cached calls should not count towards quota
        record_api_call("google_maps", "geocode", is_cached=True)
        allowed, _ = check_quota("google_maps")
        assert allowed is True

        # 3rd uncached call reaches daily limit
        record_api_call("google_maps", "geocode", is_cached=False)
        allowed, msg = check_quota("google_maps")
        assert allowed is False
        assert "Daily safety limit of 3 calls reached" in msg

        # Unlimited when set to 0
        Setting.set_val("google_maps_daily_limit", 0)
        allowed, _ = check_quota("google_maps")
        assert allowed is True


def test_get_usage_summary_and_recent_calls(app: Flask) -> None:
    """Test aggregating usage metrics, costs, and cache hit ratios."""
    with app.app_context():
        ApiUsageLog.delete().execute()
        Setting.set_val("google_maps_daily_limit", 100)
        Setting.set_val("google_maps_monthly_limit", 500)

        # 4 uncached calls ($0.040), 6 cached calls
        for _ in range(4):
            record_api_call(
                provider="google_maps",
                endpoint="compute_transit_routes",
                is_cached=False,
            )
        for _ in range(6):
            record_api_call(
                provider="google_maps",
                endpoint="compute_transit_routes",
                is_cached=True,
            )

        summary = get_usage_summary("google_maps")
        assert summary["calls_today"] == 4
        assert summary["cached_today"] == 6
        assert summary["total_requests_today"] == 10
        assert summary["estimated_cost_today_usd"] == 0.040
        assert summary["cache_hit_rate_pct"] == 60.0
        assert summary["cache_savings_month_usd"] == 0.060
        assert summary["daily_limit"] == 100
        assert summary["daily_quota_pct"] == 4.0

        recent = get_recent_calls(limit=5, provider="google_maps")
        assert len(recent) == 5
        assert recent[0]["provider"] == "google_maps"


@patch("requests.post")
def test_google_maps_client_caching_and_quota_block(
    mock_post: MagicMock, app: Flask
) -> None:
    """Test GoogleMapsClient caches repeated compute_transit_routes and blocks on quota."""
    with app.app_context():
        ApiUsageLog.delete().execute()
        global_api_cache.clear()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"routes": [{"duration": "1800s"}]}
        mock_post.return_value = mock_resp

        client = GoogleMapsClient(api_key="test-key", enable_cache=True)

        dep_dt = datetime.datetime(2026, 11, 1, 9, 0, 0)
        # First call hits mock_post
        res1 = client.compute_transit_routes(
            origin=(51.53, -0.12),
            destination=(52.20, 0.13),
            departure_time=dep_dt,
        )
        assert "routes" in res1
        assert mock_post.call_count == 1

        # Second call with same parameters hits cache, does NOT call mock_post
        res2 = client.compute_transit_routes(
            origin=(51.53, -0.12),
            destination=(52.20, 0.13),
            departure_time=dep_dt,
        )
        assert res2 == res1
        assert mock_post.call_count == 1  # Unchanged!

        # Check logs: 1 live call and 1 cached call
        logs = list(ApiUsageLog.select().order_by(ApiUsageLog.created_at.asc()))
        assert len(logs) == 2
        assert logs[0].is_cached is False
        assert logs[1].is_cached is True

        # Now test quota blocking
        Setting.set_val("google_maps_daily_limit", 1)
        # 1 live call already exists, next uncached call must raise DataSourceRateLimitError
        with pytest.raises(DataSourceRateLimitError) as exc_info:
            client.compute_transit_routes(
                origin=(51.50, -0.10),
                destination=(52.10, 0.10),
                departure_time=dep_dt,
                bypass_cache=True,
            )
        assert "Daily safety limit of 1 calls reached" in str(exc_info.value)
