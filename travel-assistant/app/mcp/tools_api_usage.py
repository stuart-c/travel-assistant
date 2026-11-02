"""MCP tools for external API usage monitoring, cost auditing, caching, and quotas."""

import logging
from typing import Any, Dict, List, Optional

from app.mcp.registry import register_tool
from app.models.setting import Setting
from app.services.api_tracker import (
    get_recent_calls,
    get_usage_summary,
    global_api_cache,
)

logger = logging.getLogger(__name__)


@register_tool(
    name="api_usage_get_summary",
    domain="api_usage",
    description="Inspect external API request metrics, estimated monthly spend, cache hit rates, and quota caps.",
    is_mutating=False,
)
def api_usage_get_summary(
    provider: Optional[str] = "google_maps",
) -> Dict[str, Any]:
    """Retrieve aggregated API usage and cost summary for a provider or all providers."""
    return get_usage_summary(provider=provider)


@register_tool(
    name="api_usage_list_recent",
    domain="api_usage",
    description="Retrieve recent external API audit records including endpoints, callers, latency, cache status, and estimated costs.",
    is_mutating=False,
)
def api_usage_list_recent(
    limit: int = 50,
    provider: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve recent external API call audit logs."""
    return get_recent_calls(limit=limit, provider=provider)


@register_tool(
    name="api_cache_clear",
    domain="api_usage",
    description="Clear in-memory cached API responses for a provider (e.g. 'google_maps') or all providers.",
    is_mutating=True,
)
def api_cache_clear(
    provider: Optional[str] = None,
) -> Dict[str, Any]:
    """Purge in-memory API response cache."""
    cleared = global_api_cache.clear(provider=provider)
    return {
        "success": True,
        "provider": provider or "all",
        "cleared_entries": cleared,
        "message": f"Purged {cleared} cached API entries.",
    }


@register_tool(
    name="api_quota_set",
    domain="api_usage",
    description="Configure daily and monthly safety call caps for an external API provider.",
    is_mutating=True,
)
def api_quota_set(
    provider: str = "google_maps",
    daily_limit: Optional[int] = None,
    monthly_limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Update safety call limits for an API provider."""
    prov = (provider or "google_maps").strip().lower()
    updated: Dict[str, Any] = {}

    if daily_limit is not None:
        Setting.set_val(f"{prov}_daily_limit", int(daily_limit))
        updated["daily_limit"] = int(daily_limit)

    if monthly_limit is not None:
        Setting.set_val(f"{prov}_monthly_limit", int(monthly_limit))
        updated["monthly_limit"] = int(monthly_limit)

    return {
        "success": True,
        "provider": prov,
        "updated_limits": updated,
        "message": f"Successfully updated quota limits for '{prov}'.",
    }
