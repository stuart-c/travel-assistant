"""Unit tests for API usage MCP tools and configuration endpoints."""

from flask import Flask
from flask.testing import FlaskClient

from app.mcp.tools_api_usage import (
    api_cache_clear,
    api_quota_set,
    api_usage_get_summary,
    api_usage_list_recent,
)
from app.models.api_usage import ApiUsageLog
from app.models.setting import Setting
from app.services.api_tracker import global_api_cache, record_api_call


def test_mcp_api_usage_tools(app: Flask) -> None:
    """Test api_usage MCP tools execution."""
    with app.app_context():
        ApiUsageLog.delete().execute()
        global_api_cache.clear()

        # Seed data
        record_api_call("google_maps", "geocode", is_cached=False)
        record_api_call("google_maps", "geocode", is_cached=True)

        # 1. Summary
        summary = api_usage_get_summary(provider="google_maps")
        assert summary["calls_today"] == 1
        assert summary["cached_today"] == 1
        assert summary["cache_hit_rate_pct"] == 50.0

        # 2. Recent calls
        recent = api_usage_list_recent(limit=10, provider="google_maps")
        assert len(recent) == 2

        # 3. Quota set
        res = api_quota_set(provider="google_maps", daily_limit=250, monthly_limit=2500)
        assert res["success"] is True
        assert int(Setting.get_val("google_maps_daily_limit")) == 250
        assert int(Setting.get_val("google_maps_monthly_limit")) == 2500

        # 4. Cache clear
        global_api_cache.set("google_maps", "test", "data")
        clear_res = api_cache_clear(provider="google_maps")
        assert clear_res["success"] is True
        assert clear_res["cleared_entries"] >= 1


def test_credentials_api_endpoints(client: FlaskClient, app: Flask) -> None:
    """Test credentials page cache clear and JSON telemetry endpoints."""
    with app.app_context():
        global_api_cache.set("google_maps", "sample_key", "sample_val")

    # POST /config/credentials/clear_cache
    resp = client.post(
        "/config/credentials/clear_cache",
        data={"provider": "google_maps"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Successfully purged" in resp.data

    # GET /config/credentials/api_usage
    json_resp = client.get("/config/credentials/api_usage?provider=google_maps")
    assert json_resp.status_code == 200
    data = json_resp.get_json()
    assert "summary" in data
    assert "recent_calls" in data
    assert data["summary"]["provider"] == "google_maps"
