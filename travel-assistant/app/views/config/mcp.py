"""Model Context Protocol (MCP) configuration endpoints and permissions management."""

import logging
from typing import Any, Dict, List, Optional

from app.mcp.server import invalidate_permission_cache
from app.models.mcp import MCPTool, MCP_ACCESS_LEVELS
from app.views.config import config_bp
from app.views.config.common import (
    PageConfig,
    parse_optional_id,
    register_config_page,
    sanitise_choice,
)

logger = logging.getLogger(__name__)


def clean_mcp_tool_item(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate and sanitise an MCP tool permission update from a changeset."""
    if not isinstance(entry, dict):
        return None

    item_id = parse_optional_id(entry.get("id"))
    if item_id is None:
        return None

    try:
        tool = MCPTool.get_by_id(item_id)
    except MCPTool.DoesNotExist:
        return None

    raw_level = sanitise_choice(
        entry.get("access_level"),
        MCP_ACCESS_LEVELS,
        "disabled",
    )

    # UI constraint enforcement:
    # Read-only tools can only be 'read' or 'disabled'.
    # Mutating tools can only be 'read_write' or 'disabled'.
    if tool.is_mutating:
        access_level = "read_write" if raw_level == "read_write" else "disabled"
    else:
        access_level = "read" if raw_level in ("read", "read_write") else "disabled"

    return {
        "id": item_id,
        "access_level": access_level,
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
                "access_level": tool.access_level,
                "updated_at": (
                    tool.updated_at.isoformat() if tool.updated_at else None
                ),
            }
        )
    return results


def on_mcp_tools_saved(stats: Dict[str, int], changeset: Dict[str, List[Any]]) -> None:
    """Invalidate in-memory MCP permission cache on successful changeset save."""
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
