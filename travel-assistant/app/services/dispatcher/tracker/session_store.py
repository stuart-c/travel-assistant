"""Persistence of active journey sessions to database settings."""

import datetime
import json
import logging
from typing import Dict

from app.models.setting import Setting
from app.services.dispatcher.tracker.models import ActiveJourney, JourneyStepStatus

logger = logging.getLogger(__name__)


def save_active_journey_session(active: ActiveJourney) -> None:
    """Persist an active journey session into the database settings."""
    try:
        key = f"active_journey_session_{active.journey_id}"
        payload = json.dumps(active.model_dump(mode="json"))
        Setting.set_val(key, payload, category="session")
    except Exception as exc:
        logger.warning(
            "Failed to save active journey session %d: %s", active.journey_id, exc
        )


def clear_active_journey_session(journey_id: int) -> None:
    """Remove a persisted active journey session from the database settings."""
    try:
        key = f"active_journey_session_{journey_id}"
        Setting.delete().where(Setting.key == key).execute()
    except Exception as exc:
        logger.warning("Failed to clear active journey session %d: %s", journey_id, exc)


def load_active_journey_sessions() -> Dict[int, ActiveJourney]:
    """Load all unexpired active journey sessions from the database settings."""
    sessions: Dict[int, ActiveJourney] = {}
    try:
        records = Setting.select().where(
            (Setting.category == "session")
            & (Setting.key.startswith("active_journey_session_"))
        )
        now_dt = datetime.datetime.now()
        for rec in records:
            if not rec.value:
                continue
            try:
                data = json.loads(rec.value)
                active = ActiveJourney.model_validate(data)
                # Purge if session is already arrived, expired, or started >12h ago
                if active.current_status in (
                    JourneyStepStatus.ARRIVED,
                    JourneyStepStatus.EXPIRED,
                ):
                    clear_active_journey_session(active.journey_id)
                    continue
                if (
                    active.started_at
                    and (now_dt - active.started_at).total_seconds() > 12 * 3600
                ):
                    clear_active_journey_session(active.journey_id)
                    continue
                sessions[active.journey_id] = active
            except Exception as e:
                logger.warning(
                    "Failed to parse active journey session from setting %s: %s",
                    rec.key,
                    e,
                )
    except Exception as exc:
        logger.warning("Failed to load active journey sessions: %s", exc)
    return sessions


__all__ = [
    "clear_active_journey_session",
    "load_active_journey_sessions",
    "save_active_journey_session",
]
