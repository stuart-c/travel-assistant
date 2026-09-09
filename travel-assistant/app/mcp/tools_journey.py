"""MCP tools for inspecting, creating, updating, and deleting journeys."""

import logging
from typing import Any, Dict, List, Optional

from app.models.journey import Journey, JourneyTimeSetting
from app.mcp.registry import register_tool
from app.sync.worker import request_sync

logger = logging.getLogger(__name__)


def _trigger_journey_syncs(from_type: str, to_type: str) -> None:
    """Queue targeted walking, timetable, and route synchronisation."""
    ft = str(from_type).strip().lower()
    tt = str(to_type).strip().lower()

    if ft in ("ha", "custom") or tt in ("ha", "custom"):
        try:
            request_sync("walking")
        except Exception:
            pass

    if ft == "bus" or tt == "bus":
        try:
            request_sync("bus_timetables")
        except Exception:
            pass

    try:
        request_sync("journey_routes")
    except Exception:
        pass


@register_tool(
    name="journey_list",
    domain="journey",
    description="List all configured multi-modal journeys, endpoints, and scheduled time windows.",
    is_mutating=False,
)
def journey_list() -> List[Dict[str, Any]]:
    """Retrieve all configured journeys with their IDs, names, and time windows."""
    journeys = Journey.select()
    results = []
    for j in journeys:
        data = j.to_dict()
        data["has_routes"] = bool(j.calculated_routes)
        results.append(data)
    return results


@register_tool(
    name="journey_get",
    domain="journey",
    description="Get detailed configuration and calculated route corridors for a specific journey by ID.",
    is_mutating=False,
)
def journey_get(journey_id: int) -> Dict[str, Any]:
    """Retrieve a specific journey by ID including its calculated routes."""
    try:
        j = Journey.get_by_id(journey_id)
        return j.to_dict()
    except Journey.DoesNotExist:
        return {"error": f"Journey with ID {journey_id} not found."}


@register_tool(
    name="journey_create",
    domain="journey",
    description="Create a new multi-modal journey, validate time settings, and queue route synchronisation.",
    is_mutating=True,
)
def journey_create(
    name: str,
    from_type: str,
    from_id: str,
    from_name: str,
    to_type: str,
    to_id: str,
    to_name: str,
    time_settings: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Create a new journey and queue route discovery."""
    clean_settings = []
    if time_settings:
        for tw in time_settings:
            if isinstance(tw, dict):
                try:
                    obj = JourneyTimeSetting.model_validate(tw)
                    clean_settings.append(obj.model_dump())
                except Exception as err:
                    logger.warning("Invalid time setting skipped: %s", err)

    journey = Journey.create(
        name=name.strip(),
        from_type=from_type.strip().lower(),
        from_id=from_id.strip(),
        from_name=from_name.strip(),
        to_type=to_type.strip().lower(),
        to_id=to_id.strip(),
        to_name=to_name.strip(),
        time_settings=clean_settings,
        calculated_routes=None,
    )

    _trigger_journey_syncs(journey.from_type, journey.to_type)
    return {"success": True, "journey": journey.to_dict()}


@register_tool(
    name="journey_update",
    domain="journey",
    description="Update an existing journey and queue route synchronisation.",
    is_mutating=True,
)
def journey_update(
    journey_id: int,
    name: Optional[str] = None,
    from_type: Optional[str] = None,
    from_id: Optional[str] = None,
    from_name: Optional[str] = None,
    to_type: Optional[str] = None,
    to_id: Optional[str] = None,
    to_name: Optional[str] = None,
    time_settings: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Update journey attributes by ID."""
    try:
        journey = Journey.get_by_id(journey_id)
    except Journey.DoesNotExist:
        return {"error": f"Journey with ID {journey_id} not found."}

    if name is not None:
        journey.name = name.strip()
    if from_type is not None:
        journey.from_type = from_type.strip().lower()
    if from_id is not None:
        journey.from_id = from_id.strip()
    if from_name is not None:
        journey.from_name = from_name.strip()
    if to_type is not None:
        journey.to_type = to_type.strip().lower()
    if to_id is not None:
        journey.to_id = to_id.strip()
    if to_name is not None:
        journey.to_name = to_name.strip()

    if time_settings is not None:
        clean_settings = []
        for tw in time_settings:
            if isinstance(tw, dict):
                try:
                    obj = JourneyTimeSetting.model_validate(tw)
                    clean_settings.append(obj.model_dump())
                except Exception as err:
                    logger.warning("Invalid time setting skipped: %s", err)
        journey.time_settings = clean_settings

    # Clear stale calculated routes when parameters change
    journey.calculated_routes = None
    journey.save()

    _trigger_journey_syncs(journey.from_type, journey.to_type)
    return {"success": True, "journey": journey.to_dict()}


@register_tool(
    name="journey_delete",
    domain="journey",
    description="Delete a configured journey by ID.",
    is_mutating=True,
)
def journey_delete(journey_id: int) -> Dict[str, Any]:
    """Delete a journey by ID."""
    try:
        journey = Journey.get_by_id(journey_id)
        journey.delete_instance()
        return {"success": True, "deleted_id": journey_id}
    except Journey.DoesNotExist:
        return {"error": f"Journey with ID {journey_id} not found."}
