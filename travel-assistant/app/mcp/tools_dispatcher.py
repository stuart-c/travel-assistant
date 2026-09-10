"""MCP tools for live journey departure monitoring, telemetry, and alert dispatch."""

import datetime
import logging
from typing import Any, Dict, Optional

from app.datasources.homeassistant import HomeAssistantClient
from app.datasources.train_live import TrainLiveClient
from app.models.journey import Journey
from app.services.dispatcher.evaluator import (
    evaluate_journey_notification,
    format_departure_notification,
)
from app.services.dispatcher.monitor import get_departure_monitor
from app.services.dispatcher.tracker import get_journey_live_tracking_data
from app.mcp.registry import register_tool

logger = logging.getLogger(__name__)


@register_tool(
    name="dispatcher_get_status",
    domain="dispatcher",
    description="Inspect current live journey tracking session, telemetry, stages, and delay status.",
    is_mutating=False,
)
def dispatcher_get_status() -> Dict[str, Any]:
    """Retrieve active journey tracking session data."""
    monitor = get_departure_monitor()
    active_journeys = monitor.active_journeys if monitor else None
    tracking_data = get_journey_live_tracking_data(active_journeys=active_journeys)

    active_count = len(monitor.active_journeys) if monitor else 0
    active_summary = []
    if monitor and monitor.active_journeys:
        for j_id, active in monitor.active_journeys.items():
            active_summary.append(
                {
                    "journey_id": j_id,
                    "journey_name": active.journey.name if active.journey else None,
                    "status": (
                        active.current_status.value
                        if active.current_status
                        else "unknown"
                    ),
                    "started_at": (
                        active.started_at.isoformat() if active.started_at else None
                    ),
                    "expected_arrival": active.expected_arrival_time,
                    "last_message": active.last_notification_message,
                }
            )

    return {
        "monitor_running": monitor.is_running() if monitor else False,
        "active_journeys_count": active_count,
        "active_journeys": active_summary,
        "telemetry": tracking_data,
    }


@register_tool(
    name="dispatcher_evaluate",
    domain="dispatcher",
    description="Force immediate departure evaluation for a configured journey using live Darwin/BODS feeds.",
    is_mutating=False,
)
def dispatcher_evaluate(journey_id: int) -> Dict[str, Any]:
    """Evaluate upcoming transit departures for a journey."""
    try:
        journey = Journey.get_by_id(journey_id)
    except Journey.DoesNotExist:
        return {"error": f"Journey with ID {journey_id} not found."}

    now = datetime.datetime.now()
    live_client = TrainLiveClient()
    monitor = get_departure_monitor()
    sent_keys = monitor.sent_keys if monitor else set()

    candidate = evaluate_journey_notification(
        journey=journey,
        dt=now,
        sent_keys=sent_keys,
        live_client=live_client,
    )

    if not candidate:
        return {
            "journey_id": journey_id,
            "journey_name": journey.name,
            "evaluated_at": now.isoformat(),
            "candidate": None,
            "message": "No upcoming departure candidate found within evaluation window.",
        }

    title, message, data = format_departure_notification(candidate)
    return {
        "journey_id": journey_id,
        "journey_name": journey.name,
        "evaluated_at": now.isoformat(),
        "candidate": {
            "service_key": candidate.service_key,
            "leave_time": (
                candidate.leave_time.isoformat() if candidate.leave_time else None
            ),
            "departure_time": candidate.departure_time,
            "arrival_time": candidate.arrival_time,
            "transport_type": candidate.transport_type,
            "line_name": candidate.line_name,
            "platform": candidate.platform,
            "delay_minutes": candidate.delay_minutes,
            "preview_title": title,
            "preview_message": message,
        },
    }


@register_tool(
    name="dispatcher_test_notification",
    domain="dispatcher",
    description="Dispatch a test departure alert for a journey directly to Stuart's mobile device.",
    is_mutating=True,
)
def dispatcher_test_notification(journey_id: int) -> Dict[str, Any]:
    """Evaluate journey and dispatch a test alert to Stuart's phone."""
    try:
        journey = Journey.get_by_id(journey_id)
    except Journey.DoesNotExist:
        return {"error": f"Journey with ID {journey_id} not found."}

    now = datetime.datetime.now()
    live_client = TrainLiveClient()
    candidate = evaluate_journey_notification(
        journey=journey,
        dt=now,
        sent_keys=set(),
        live_client=live_client,
    )

    if not candidate:
        title = f"Test Alert: {journey.name}"
        message = f"Simulated departure alert for {journey.name} from {journey.from_name} to {journey.to_name}."
        data = {"tag": f"journey_{journey_id}"}
    else:
        title, message, data = format_departure_notification(candidate)

    client = HomeAssistantClient()
    target_service = "mobile_app_stuart_mobile"
    sent = client.send_mobile_notification(
        title=f"[TEST] {title}",
        message=message,
        service_name=target_service,
        data=data,
    )

    return {
        "success": sent,
        "journey_id": journey_id,
        "target_service": target_service,
        "title": f"[TEST] {title}",
        "message": message,
    }


@register_tool(
    name="dispatcher_reset_session",
    domain="dispatcher",
    description="Cancel or clear active journey tracking sessions in the departure monitor.",
    is_mutating=True,
)
def dispatcher_reset_session(journey_id: Optional[int] = None) -> Dict[str, Any]:
    """Reset active tracking session for a specific journey or all journeys."""
    monitor = get_departure_monitor()
    if not monitor:
        return {"error": "Departure monitor is not running."}

    if journey_id is not None:
        removed = monitor.active_journeys.pop(journey_id, None)
        return {
            "success": True,
            "reset_journey_id": journey_id,
            "was_active": removed is not None,
        }

    cleared_count = len(monitor.active_journeys)
    monitor.active_journeys.clear()
    return {"success": True, "cleared_count": cleared_count}
