"""MCP tools for background transit dataset synchronisation and metrics."""

import logging
from typing import Any, Dict, List

from app.db import get_sync_stats
from app.mcp.registry import register_tool
from app.sync import request_sync

logger = logging.getLogger(__name__)

VALID_DATASETS = (
    "bus_routes",
    "stops",
    "interchanges",
    "ha_locations",
    "darwin",
    "walking",
    "bods",
    "journey_routes",
)


@register_tool(
    name="sync_get_status",
    domain="sync",
    description="Inspect transit dataset background synchronisation metrics, freshness, and error status.",
    is_mutating=False,
)
def sync_get_status() -> List[Dict[str, Any]]:
    """Retrieve synchronisation status for all cached transit datasets."""
    return get_sync_stats()


@register_tool(
    name="sync_trigger",
    domain="sync",
    description="Queue an asynchronous background synchronisation for a transit dataset.",
    is_mutating=True,
)
def sync_trigger(dataset: str) -> Dict[str, Any]:
    """Trigger background synchronisation for a specific dataset."""
    norm = dataset.strip().lower()
    if norm not in VALID_DATASETS:
        return {
            "error": f"Invalid dataset '{dataset}'. Valid options are: {', '.join(VALID_DATASETS)}."
        }

    request_sync(norm)
    return {
        "success": True,
        "dataset": norm,
        "status": "queued",
        "message": f"Background synchronisation for '{norm}' has been queued.",
    }
