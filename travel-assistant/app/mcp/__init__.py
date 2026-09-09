"""Model Context Protocol (MCP) server package for Travel Assistant."""

from app.mcp.registry import (
    REGISTERED_TOOLS,
    ToolDefinition,
    register_tool,
    sync_mcp_tools_with_db,
)
from app.mcp.server import (
    TravelAssistantMCPServer,
    create_mcp_app,
    get_cached_tool_permissions,
    invalidate_permission_cache,
)

from app.mcp.tools_database import db_get_table_info, db_query

__all__ = [
    "REGISTERED_TOOLS",
    "ToolDefinition",
    "TravelAssistantMCPServer",
    "create_mcp_app",
    "get_cached_tool_permissions",
    "invalidate_permission_cache",
    "register_tool",
    "sync_mcp_tools_with_db",
    "db_get_table_info",
    "db_query",
]
