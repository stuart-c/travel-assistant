"""Pydantic data models for Journey Planning outputs."""

from typing import List, Optional
from pydantic import BaseModel as PydanticBaseModel, ConfigDict, Field


class ItineraryEndpoint(PydanticBaseModel):
    """Origin or destination node within a scheduled itinerary leg."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    platform: Optional[str] = None


class ItineraryLeg(PydanticBaseModel):
    """A concrete timed leg within a ScheduledItinerary."""

    model_config = ConfigDict(extra="ignore")

    leg_index: int
    mode: str  # "walk", "bus", "rail", "interchange", "platform_transfer", "shuttle"
    origin: ItineraryEndpoint
    destination: ItineraryEndpoint
    dep_time: str
    arr_time: str
    duration_minutes: int
    line: Optional[str] = None
    operator: Optional[str] = None
    headsign: Optional[str] = None
    stops_count: Optional[int] = None
    timetable_id: Optional[int] = None


class ScheduledItinerary(PydanticBaseModel):
    """A concrete scheduled travel plan matching time and day constraints."""

    model_config = ConfigDict(extra="ignore")

    departure_time: str
    arrival_time: str
    total_duration_minutes: int
    transfers_count: int
    robustness_score: str
    legs: List[ItineraryLeg] = Field(default_factory=list)


__all__ = [
    "ItineraryEndpoint",
    "ItineraryLeg",
    "ScheduledItinerary",
]
