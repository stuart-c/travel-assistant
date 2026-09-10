"""MCP server implementation with dynamic tool filtering and permission enforcement."""

import json
import logging
import time
from typing import Any, Dict, List, Optional
from starlette.routing import Route

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:  # pragma: no cover
    from mcp.server.fastmcp import FastMCP as MCPServer  # type: ignore[no-redef]

from mcp.types import CallToolResult, TextContent, Tool

try:
    from mcp.server.transport_security import TransportSecuritySettings
except ImportError:  # pragma: no cover
    TransportSecuritySettings = None  # type: ignore[assignment,misc]

from app.db import get_db_stats, get_sync_stats
from app.mcp.auth import BearerAuthMiddleware
from app.mcp.registry import (
    REGISTERED_TOOLS,
    _ensure_all_tools_imported,
    sync_mcp_tools_with_db,
)
from app.services.dispatcher.monitor import get_departure_monitor
from app.services.dispatcher.tracker import get_journey_live_tracking_data

logger = logging.getLogger(__name__)

_PERMISSION_CACHE: Dict[str, bool] = {}
_PERMISSION_CACHE_TIME: float = 0.0
_CACHE_TTL_SECONDS: float = 2.0


def get_cached_tool_permissions() -> Dict[str, bool]:
    """Retrieve tool permissions from the database with a short in-memory cache."""
    global _PERMISSION_CACHE, _PERMISSION_CACHE_TIME
    now = time.time()
    if now - _PERMISSION_CACHE_TIME < _CACHE_TTL_SECONDS and _PERMISSION_CACHE:
        return _PERMISSION_CACHE

    try:
        from app.models.mcp import MCPTool

        perms = {tool.tool_name: bool(tool.enabled) for tool in MCPTool.select()}
        _PERMISSION_CACHE = perms
        _PERMISSION_CACHE_TIME = now
        return perms
    except Exception as err:
        logger.warning("Could not query tool permissions: %s", err)
        return _PERMISSION_CACHE


def invalidate_permission_cache() -> None:
    """Explicitly invalidate the in-memory tool permission cache."""
    global _PERMISSION_CACHE_TIME
    _PERMISSION_CACHE_TIME = 0.0


class TravelAssistantMCPServer(MCPServer):
    """Specialised MCPServer with dynamic tool catalogue filtering and permission enforcement."""

    def __init__(self, name: str = "Travel Assistant", **kwargs: Any) -> None:
        super().__init__(name, **kwargs)
        _ensure_all_tools_imported()
        self._register_all_tools()
        self._register_resources()

    def _register_all_tools(self) -> None:
        """Register all discovered tools into the MCPServer tool manager."""
        for tool_name, tool_def in REGISTERED_TOOLS.items():
            self.add_tool(
                tool_def.func,
                name=tool_def.name,
                description=tool_def.description,
            )

    def _register_resources(self) -> None:
        """Register standard application diagnostic resources."""

        @self.resource(
            "travel://system/status",
            description="Real-time SQLite storage and sync metrics.",
        )
        def get_system_status() -> str:
            db_stats = get_db_stats()
            sync_stats = get_sync_stats()
            payload = {
                "file_size": db_stats.get("file_size_formatted"),
                "total_tables": db_stats.get("total_tables"),
                "total_rows": db_stats.get("total_rows"),
                "sync_datasets": [
                    {
                        "table": s.get("table_name"),
                        "status": s.get("status"),
                        "last_updated": s.get("last_updated_at"),
                    }
                    for s in sync_stats
                ],
            }
            return json.dumps(payload, indent=2)

        @self.resource(
            "travel://journey/live",
            description="Real-time journey tracking telemetry and stage status.",
        )
        def get_live_journey_telemetry() -> str:
            monitor = get_departure_monitor()
            active_journeys = monitor.active_journeys if monitor else None
            data = get_journey_live_tracking_data(active_journeys=active_journeys)
            return json.dumps(data or {"status": "inactive"}, indent=2)

    async def list_tools(self) -> List[Tool]:
        """Return available tools, dynamically omitting any tool marked as disabled."""
        all_tools = await super().list_tools()
        permissions = get_cached_tool_permissions()
        return [tool for tool in all_tools if permissions.get(tool.name, False)]

    async def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        context: Optional[Any] = None,
    ) -> Any:
        """Enforce granular permissions before delegating tool execution."""
        permissions = get_cached_tool_permissions()
        is_enabled = permissions.get(name, False)

        if not is_enabled:
            logger.warning("Rejected call to disabled MCP tool '%s'.", name)
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=f"Tool '{name}' is disabled in Travel Assistant settings.",
                    )
                ],
                is_error=True,
            )

        return await super().call_tool(name, arguments, context)


def create_mcp_app(
    api_token: str = "",
    host: str = "0.0.0.0",
    streamable_http_path: str = "/sse",
    transport_security: Optional[Any] = None,
    allowed_hosts: Optional[List[str]] = None,
) -> Any:
    """Application factory creating the Starlette ASGI application for MCP over Streamable HTTP.

    By default, disables strict DNS rebinding protection so that local area network
    (LAN) clients and Home Assistant reverse proxy requests with arbitrary Host headers
    (e.g. ``192.168.x.x``, ``homeassistant.local``) are permitted without triggering
    HTTP 421 Misdirected Request errors.
    """
    sync_mcp_tools_with_db()
    server = TravelAssistantMCPServer("Travel Assistant")

    kwargs: Dict[str, Any] = {
        "host": host,
        "streamable_http_path": streamable_http_path,
    }
    if transport_security is not None:
        kwargs["transport_security"] = transport_security
    elif allowed_hosts is not None:
        if TransportSecuritySettings is not None:
            kwargs["transport_security"] = TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=allowed_hosts,
            )
    else:
        if TransportSecuritySettings is not None:
            kwargs["transport_security"] = TransportSecuritySettings(
                enable_dns_rebinding_protection=False
            )

    app = server.streamable_http_app(**kwargs)

    # Alias common endpoint paths (/sse, /mcp, /) so clients work regardless of URL configuration
    if hasattr(app, "routes") and app.routes:
        main_endpoint = app.routes[0].endpoint
        existing_paths = {getattr(r, "path", "") for r in app.routes}
        for alt_path in ("/sse", "/mcp", "/"):
            if alt_path not in existing_paths:
                app.routes.append(Route(alt_path, endpoint=main_endpoint))

    if api_token:
        app.add_middleware(BearerAuthMiddleware, api_token=api_token)
    return app


__all__ = [
    "TravelAssistantMCPServer",
    "create_mcp_app",
    "get_cached_tool_permissions",
    "invalidate_permission_cache",
]
