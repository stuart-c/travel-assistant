"""MCP tools for inspecting, creating, updating, and deleting timetables."""

import datetime
import logging
from typing import Any, Dict, List, Optional

from app.models.timetable import Timetable, TimetableContent
from app.mcp.registry import register_tool
from app.sync.worker import request_sync

logger = logging.getLogger(__name__)


@register_tool(
    name="timetable_list",
    domain="timetable",
    description="List public transit timetables with optional transport type filtering ('bus' or 'rail').",
    is_mutating=False,
)
def timetable_list(transport_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """List timetables with basic metadata and row/trip counts."""
    query = Timetable.select()
    if transport_type:
        query = query.where(Timetable.transport_type == transport_type.strip().lower())

    results = []
    for t in query:
        content = t.get_content()
        results.append(
            {
                "id": t.id,
                "name": t.name,
                "transport_type": t.transport_type,
                "start_date": t.start_date.isoformat() if t.start_date else None,
                "end_date": t.end_date.isoformat() if t.end_date else None,
                "auto_added": t.auto_added,
                "stop_count": len(content.get("stops", [])),
                "trip_count": len(content.get("trips", [])),
            }
        )
    return results


@register_tool(
    name="timetable_get",
    domain="timetable",
    description="Get full timetable details including calling stop sequence and trip matrices by ID.",
    is_mutating=False,
)
def timetable_get(timetable_id: int) -> Dict[str, Any]:
    """Retrieve full timetable details by ID."""
    try:
        t = Timetable.get_by_id(timetable_id)
        return t.to_dict()
    except Timetable.DoesNotExist:
        return {"error": f"Timetable with ID {timetable_id} not found."}


@register_tool(
    name="timetable_create",
    domain="timetable",
    description="Create a manual timetable schedule with calling stops and trip timings.",
    is_mutating=True,
)
def timetable_create(
    name: str,
    transport_type: str = "bus",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    content: Optional[Dict[str, Any]] = None,
    monday: bool = True,
    tuesday: bool = True,
    wednesday: bool = True,
    thursday: bool = True,
    friday: bool = True,
    saturday: bool = True,
    sunday: bool = True,
    bank_holiday: bool = True,
) -> Dict[str, Any]:
    """Create a manual timetable schedule."""
    parsed_start = None
    if start_date:
        try:
            parsed_start = datetime.date.fromisoformat(start_date.strip())
        except ValueError:
            pass

    parsed_end = None
    if end_date:
        try:
            parsed_end = datetime.date.fromisoformat(end_date.strip())
        except ValueError:
            pass

    timetable_content = TimetableContent()
    if content and isinstance(content, dict):
        try:
            timetable_content = TimetableContent.model_validate(content)
        except Exception as err:
            logger.warning("Could not validate timetable content: %s", err)

    t = Timetable.create(
        name=name.strip(),
        transport_type=transport_type.strip().lower(),
        start_date=parsed_start,
        end_date=parsed_end,
        monday=monday,
        tuesday=tuesday,
        wednesday=wednesday,
        thursday=thursday,
        friday=friday,
        saturday=saturday,
        sunday=sunday,
        bank_holiday=bank_holiday,
        auto_added=False,
        content=timetable_content,
    )

    try:
        request_sync("journey_routes")
    except Exception:
        pass

    return {"success": True, "timetable": t.to_dict()}


@register_tool(
    name="timetable_update",
    domain="timetable",
    description="Update an existing manual timetable schedule by ID.",
    is_mutating=True,
)
def timetable_update(
    timetable_id: int,
    name: Optional[str] = None,
    transport_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    content: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Update timetable metadata or matrix contents."""
    try:
        t = Timetable.get_by_id(timetable_id)
    except Timetable.DoesNotExist:
        return {"error": f"Timetable with ID {timetable_id} not found."}

    if name is not None:
        t.name = name.strip()
    if transport_type is not None:
        t.transport_type = transport_type.strip().lower()
    if start_date is not None:
        try:
            t.start_date = datetime.date.fromisoformat(start_date.strip())
        except ValueError:
            pass
    if end_date is not None:
        try:
            t.end_date = datetime.date.fromisoformat(end_date.strip())
        except ValueError:
            pass
    if content is not None and isinstance(content, dict):
        t.set_content(content)

    t.save()

    try:
        request_sync("journey_routes")
    except Exception:
        pass

    return {"success": True, "timetable": t.to_dict()}


@register_tool(
    name="timetable_delete",
    domain="timetable",
    description="Delete a timetable by ID (protected against deleting auto-synced Darwin/BODS feeds unless forced).",
    is_mutating=True,
)
def timetable_delete(timetable_id: int, force: bool = False) -> Dict[str, Any]:
    """Delete a timetable by ID."""
    try:
        t = Timetable.get_by_id(timetable_id)
        if t.auto_added and not force:
            return {
                "error": (
                    f"Timetable '{t.name}' was automatically ingested from National Rail Darwin or BODS. "
                    "Pass force=True if you really intend to remove it."
                )
            }
        t.delete_instance()
        return {"success": True, "deleted_id": timetable_id}
    except Timetable.DoesNotExist:
        return {"error": f"Timetable with ID {timetable_id} not found."}
