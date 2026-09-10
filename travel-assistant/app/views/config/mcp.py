"""Model Context Protocol (MCP) configuration endpoints and permissions management."""

import logging
from typing import Any, Dict, List, Optional

from app.models.mcp import MCPTool
from app.views.config import config_bp
from app.views.config.common import (
    PageConfig,
    parse_optional_id,
    register_config_page,
)

logger = logging.getLogger(__name__)


def clean_mcp_tool_item(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate and sanitise an MCP tool status update from a changeset."""
    if not isinstance(entry, dict):
        return None

    item_id = parse_optional_id(entry.get("id"))
    if item_id is None:
        return None

    try:
        MCPTool.get_by_id(item_id)
    except MCPTool.DoesNotExist:
        return None

    raw_enabled = entry.get("enabled")
    if isinstance(raw_enabled, str):
        enabled = raw_enabled.strip().lower() in ("true", "1", "yes", "on", "enabled")
    else:
        enabled = bool(raw_enabled)

    return {
        "id": item_id,
        "enabled": enabled,
    }


def get_mcp_tools_data() -> List[Dict[str, Any]]:
    """Retrieve all configured tools formatted for Grid.js table loading."""
    tools = MCPTool.get_all_tools()
    results: List[Dict[str, Any]] = []
    for tool in tools:
        results.append(
            {
                "id": tool.id,
                "tool_name": tool.tool_name,
                "domain": tool.domain,
                "description": tool.description,
                "is_mutating": tool.is_mutating,
                "enabled": bool(tool.enabled),
                "updated_at": (
                    tool.updated_at.isoformat() if tool.updated_at else None
                ),
            }
        )
    return results


def on_mcp_tools_saved(stats: Dict[str, int], changeset: Dict[str, List[Any]]) -> None:
    """Invalidate in-memory MCP permission cache on successful changeset save."""
    from app.mcp.server import invalidate_permission_cache

    invalidate_permission_cache()
    logger.info("Invalidated MCP tool permission cache following configuration update.")


register_config_page(
    config_bp,
    PageConfig(
        route="/mcp",
        endpoint="mcp",
        template="config_mcp.html",
        model_class=MCPTool,
        clean_item_func=clean_mcp_tool_item,
        entity_label="MCP Tools",
        get_data_items=get_mcp_tools_data,
        post_save_hook=on_mcp_tools_saved,
    ),
)
