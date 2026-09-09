"""Peewee model for MCP tool configuration and permission access control."""

from typing import List, Optional
from peewee import BooleanField, CharField

from app.models.base import BaseModel

MCP_ACCESS_LEVELS = ("disabled", "read", "read_write")


class MCPTool(BaseModel):
    """Configuration and access level permissions for an individual MCP tool."""

    tool_name = CharField(max_length=64, unique=True, index=True)
    domain = CharField(max_length=32, index=True)
    description = CharField(max_length=255)
    is_mutating = BooleanField(default=False)
    # Default is 'disabled' (strict opt-in security)
    access_level = CharField(max_length=16, default="disabled")

    class Meta:
        table_name = "mcp_tools"

    @classmethod
    def get_all_tools(cls) -> List["MCPTool"]:
        """Retrieve all configured tools ordered by domain and tool name."""
        return list(cls.select().order_by(cls.domain, cls.tool_name))

    @classmethod
    def get_enabled_tools(cls) -> List["MCPTool"]:
        """Retrieve all tools with active access ('read' or 'read_write')."""
        return list(cls.select().where(cls.access_level.in_(("read", "read_write"))))

    @classmethod
    def get_tool_permission(cls, tool_name: str) -> Optional[str]:
        """Retrieve the configured access level for a specific tool."""
        try:
            tool = cls.get(cls.tool_name == tool_name)
            return tool.access_level
        except cls.DoesNotExist:
            return None


__all__ = ["MCPTool", "MCP_ACCESS_LEVELS"]
