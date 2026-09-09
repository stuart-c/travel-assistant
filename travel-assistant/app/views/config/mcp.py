"""Model Context Protocol (MCP) configuration endpoints and permissions management."""

import logging
from typing import Any, Dict, List, Optional

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

    # UI constraint enforcement based on tool definition allowed levels:
    from app.mcp.registry import REGISTERED_TOOLS

    tool_def = REGISTERED_TOOLS.get(tool.tool_name)
    if tool_def and tool_def.allowed_levels:
        allowed = tool_def.allowed_levels
    elif tool.is_mutating:
        allowed = ("disabled", "read_write")
    else:
        allowed = ("disabled", "read")

    if raw_level in allowed:
        access_level = raw_level
    elif "read" in allowed and raw_level == "read_write":
        access_level = "read"
    else:
        access_level = "disabled"

    return {
        "id": item_id,
        "access_level": access_level,
    }


def get_mcp_tools_data() -> List[Dict[str, Any]]:
    """Retrieve all configured tools formatted for Grid.js table loading."""
    from app.mcp.registry import REGISTERED_TOOLS

    tools = MCPTool.get_all_tools()
    results: List[Dict[str, Any]] = []
    for tool in tools:
        tool_def = REGISTERED_TOOLS.get(tool.tool_name)
        if tool_def and tool_def.allowed_levels:
            allowed = list(tool_def.allowed_levels)
        elif tool.is_mutating:
            allowed = ["disabled", "read_write"]
        else:
            allowed = ["disabled", "read"]

        results.append(
            {
                "id": tool.id,
                "tool_name": tool.tool_name,
                "domain": tool.domain,
                "description": tool.description,
                "is_mutating": tool.is_mutating,
                "access_level": tool.access_level,
                "allowed_levels": allowed,
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
