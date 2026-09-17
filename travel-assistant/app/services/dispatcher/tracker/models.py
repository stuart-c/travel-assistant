"""Data models and lifecycle states for journey tracking."""

import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.planner.models import (
    ItineraryEndpoint,
    ItineraryLeg,
    ScheduledItinerary,
)

FOOT_MODES: Set[str] = {"walk", "walking", "foot", "interchange", "platform_transfer"}


class JourneyStepStatus(str, Enum):
    """Lifecycle status of Stuart's progression through a journey."""

    PRE_DEPARTURE = "pre_departure"
    EN_ROUTE_TO_STOP = "en_route_to_stop"
    AT_DEPARTURE_STOP = "at_departure_stop"
    ON_TRANSIT = "on_transit"
    AT_INTERCHANGE = "at_interchange"
    EN_ROUTE_TO_DESTINATION = "en_route_to_destination"
    ARRIVED = "arrived"
    EXPIRED = "expired"


class LiveRailStatus(BaseModel):
    """Real-time platform, departure timing, and service disruption status."""

    model_config = ConfigDict(extra="ignore")

    platform: Optional[str] = None
    std: Optional[str] = None
    etd: Optional[str] = None
    delay_minutes: int = 0
    delay_reason: Optional[str] = None
    is_cancelled: bool = False
    cancel_reason: Optional[str] = None


class ActiveJourney(BaseModel):
    """State of an in-progress journey being tracked for Stuart."""

    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)

    journey_id: int
    journey_name: str = ""
    from_type: str = ""
    from_id: str = ""
    from_name: str = ""
    to_type: str = ""
    to_id: str = ""
    to_name: str = ""
    itinerary: Optional[ScheduledItinerary] = None
    legs: List[ItineraryLeg] = Field(default_factory=list)
    current_leg_index: int = 0
    current_status: JourneyStepStatus = JourneyStepStatus.PRE_DEPARTURE
    started_at: datetime.datetime = Field(default_factory=datetime.datetime.now)
    expected_arrival_time: str = ""
    last_notification_message: Optional[str] = None
    last_notification_time: Optional[datetime.datetime] = None
    last_notified_status: Optional[JourneyStepStatus] = None
    last_notified_platform: Optional[str] = None
    last_notified_delay_minutes: int = 0
    platform: Optional[str] = None
    live_status: Optional[str] = None
    delay_minutes: int = 0
    delay_reason: Optional[str] = None

    @field_validator("itinerary", mode="before")
    @classmethod
    def _validate_itinerary(cls, value: Any) -> Optional[ScheduledItinerary]:
        if not value:
            return None
        if isinstance(value, ScheduledItinerary):
            return value
        if isinstance(value, dict):
            if not value.get("departure_time"):
                return None
            return ScheduledItinerary.model_validate(value)
        return None

    @field_validator("current_status", mode="before")
    @classmethod
    def _validate_current_status(cls, value: Any) -> JourneyStepStatus:
        if isinstance(value, JourneyStepStatus):
            return value
        try:
            return JourneyStepStatus(str(value))
        except (ValueError, KeyError):
            return JourneyStepStatus.PRE_DEPARTURE

    @field_validator("last_notified_status", mode="before")
    @classmethod
    def _validate_last_notified_status(cls, value: Any) -> Optional[JourneyStepStatus]:
        if not value:
            return None
        if isinstance(value, JourneyStepStatus):
            return value
        try:
            return JourneyStepStatus(str(value))
        except (ValueError, KeyError):
            return None

    @model_validator(mode="after")
    def _populate_defaults(self) -> "ActiveJourney":
        if not self.legs and self.itinerary and self.itinerary.legs:
            self.legs = list(self.itinerary.legs)
        if not self.expected_arrival_time and self.itinerary:
            self.expected_arrival_time = self.itinerary.arrival_time
        return self

    def to_dict(self) -> Dict[str, Any]:
        """Convert ActiveJourney instance to a JSON-serialisable dictionary."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActiveJourney":
        """Reconstruct ActiveJourney instance from a dictionary."""
        return cls.model_validate(data)


__all__ = [
    "FOOT_MODES",
    "ActiveJourney",
    "ItineraryEndpoint",
    "ItineraryLeg",
    "JourneyStepStatus",
    "LiveRailStatus",
    "ScheduledItinerary",
]
