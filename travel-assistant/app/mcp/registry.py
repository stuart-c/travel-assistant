"""Tool registry and database synchronisation for the MCP service."""

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple
from peewee import SqliteDatabase

logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    """Metadata specification and implementation for an MCP tool."""

    name: str
    domain: str
    description: str
    is_mutating: bool
    func: Callable[..., Any]
    allowed_levels: Tuple[str, ...] = ()


REGISTERED_TOOLS: Dict[str, ToolDefinition] = {}


def register_tool(
    name: str,
    domain: str,
    description: str,
    is_mutating: bool = False,
    allowed_levels: Optional[Tuple[str, ...]] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator to register an MCP tool definition with domain metadata."""
    resolved_levels = (
        allowed_levels
        if allowed_levels is not None
        else (("disabled", "read_write") if is_mutating else ("disabled", "read"))
    )

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        tool_def = ToolDefinition(
            name=name,
            domain=domain,
            description=description,
            is_mutating=is_mutating,
            func=func,
            allowed_levels=resolved_levels,
        )
        REGISTERED_TOOLS[name] = tool_def
        return func

    return decorator


def sync_mcp_tools_with_db(database: Optional[SqliteDatabase] = None) -> Dict[str, int]:
    """Synchronise in-memory registered tools with the SQLite database table.

    Newly discovered tools default to 'disabled' (strict opt-in security),
    ensuring tools remain inaccessible until explicitly enabled in the Web UI.
    Existing user-configured access levels are preserved.
    """
    from app.models.mcp import MCPTool

    # Import all tool modules to populate REGISTERED_TOOLS if not already loaded
    _ensure_all_tools_imported()

    stats = {"added": 0, "updated": 0, "total": len(REGISTERED_TOOLS)}
    if not REGISTERED_TOOLS:
        return stats

    try:
        existing_tools = {tool.tool_name: tool for tool in MCPTool.select()}
    except Exception as err:
        logger.warning("Could not query mcp_tools table (may not exist yet): %s", err)
        return stats

    with MCPTool._meta.database.atomic():
        for name, tool_def in REGISTERED_TOOLS.items():
            if name not in existing_tools:
                # Insert newly discovered tool as disabled
                MCPTool.create(
                    tool_name=name,
                    domain=tool_def.domain,
                    description=tool_def.description,
                    is_mutating=tool_def.is_mutating,
                    access_level="disabled",
                )
                stats["added"] += 1
                logger.info("Registered new MCP tool '%s' (default: disabled).", name)
            else:
                existing = existing_tools[name]
                has_changed = False
                if existing.domain != tool_def.domain:
                    existing.domain = tool_def.domain
                    has_changed = True
                if existing.description != tool_def.description:
                    existing.description = tool_def.description
                    has_changed = True
                if existing.is_mutating != tool_def.is_mutating:
                    existing.is_mutating = tool_def.is_mutating
                    has_changed = True

                if has_changed:
                    existing.save()
                    stats["updated"] += 1

    logger.info(
        "Synchronised MCP tools table: %d added, %d metadata updated, %d total.",
        stats["added"],
        stats["updated"],
        stats["total"],
    )
    return stats


def _ensure_all_tools_imported() -> None:
    """Import all tool implementation submodules to ensure tool decorators fire."""
    import app.mcp.tools_journey  # noqa: F401
    import app.mcp.tools_timetable  # noqa: F401
    import app.mcp.tools_walking  # noqa: F401
    import app.mcp.tools_stops  # noqa: F401
    import app.mcp.tools_dispatcher  # noqa: F401
    import app.mcp.tools_sync  # noqa: F401
    import app.mcp.tools_database  # noqa: F401


__all__ = [
    "ToolDefinition",
    "REGISTERED_TOOLS",
    "register_tool",
    "sync_mcp_tools_with_db",
]
