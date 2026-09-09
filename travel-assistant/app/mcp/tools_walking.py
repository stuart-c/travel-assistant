"""MCP tools for inspecting, creating, and deleting walking connections and platform transfers."""

import logging
from typing import Any, Dict, List, Optional

from app.models.transfer import PlatformTransfer
from app.models.walking import Walking
from app.mcp.registry import register_tool
from app.sync.worker import request_sync

logger = logging.getLogger(__name__)


@register_tool(
    name="walking_list",
    domain="walking",
    description="List configured walking connections between places and transit stops.",
    is_mutating=False,
)
def walking_list(query: Optional[str] = None) -> List[Dict[str, Any]]:
    """List walking connections with optional text search."""
    items = Walking.search(query=query) if query else list(Walking.select())
    return [item.to_dict() for item in items]


@register_tool(
    name="walking_create",
    domain="walking",
    description="Create a walking connection between a location and transit stop.",
    is_mutating=True,
)
def walking_create(
    start_type: str,
    start_id: str,
    start_name: str,
    finish_type: str,
    finish_id: str,
    finish_name: str,
    time_needed_minutes: int = 5,
    bidirectional: bool = True,
) -> Dict[str, Any]:
    """Create a walking connection and queue route updates."""
    w = Walking.create(
        start_type=start_type.strip().lower(),
        start_id=start_id.strip(),
        start_name=start_name.strip(),
        finish_type=finish_type.strip().lower(),
        finish_id=finish_id.strip(),
        finish_name=finish_name.strip(),
        time_needed_minutes=max(1, int(time_needed_minutes)),
        bidirectional=bidirectional,
        auto_generated=False,
    )

    try:
        request_sync("journey_routes")
    except Exception:
        pass

    return {"success": True, "walking": w.to_dict()}


@register_tool(
    name="walking_delete",
    domain="walking",
    description="Delete a walking connection by ID.",
    is_mutating=True,
)
def walking_delete(walking_id: int) -> Dict[str, Any]:
    """Delete a walking connection by ID."""
    try:
        w = Walking.get_by_id(walking_id)
        w.delete_instance()
        try:
            request_sync("journey_routes")
        except Exception:
            pass
        return {"success": True, "deleted_id": walking_id}
    except Walking.DoesNotExist:
        return {"error": f"Walking connection with ID {walking_id} not found."}


@register_tool(
    name="transfer_list",
    domain="walking",
    description="List intra-station platform and stand transfer times with step-free accessibility.",
    is_mutating=False,
)
def transfer_list(location_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """List platform/stand transfers with optional station filtering."""
    query = PlatformTransfer.select()
    if location_id:
        query = query.where(PlatformTransfer.location_id == location_id.strip())
    return [item.to_dict() for item in query]
