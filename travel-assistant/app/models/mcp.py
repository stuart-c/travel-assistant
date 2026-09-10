"""Peewee model for MCP tool configuration and permission access control."""

from typing import List
from peewee import BooleanField, CharField

from app.models.base import BaseModel


class MCPTool(BaseModel):
    """Configuration and access permissions for an individual MCP tool."""

    tool_name = CharField(max_length=64, unique=True, index=True)
    domain = CharField(max_length=32, index=True)
    description = CharField(max_length=255)
    is_mutating = BooleanField(default=False)
    # Default is False (disabled - strict opt-in security)
    enabled = BooleanField(default=False, index=True)

    class Meta:
        table_name = "mcp_tools"

    @classmethod
    def get_all_tools(cls) -> List["MCPTool"]:
        """Retrieve all configured tools ordered by domain and tool name."""
        return list(cls.select().order_by(cls.domain, cls.tool_name))

    @classmethod
    def get_enabled_tools(cls) -> List["MCPTool"]:
        """Retrieve all enabled tools."""
        return list(cls.select().where(cls.enabled))

    @classmethod
    def is_tool_enabled(cls, tool_name: str) -> bool:
        """Check whether a specific tool is enabled."""
        try:
            tool = cls.get(cls.tool_name == tool_name)
            return bool(tool.enabled)
        except cls.DoesNotExist:
            return False


__all__ = ["MCPTool"]
