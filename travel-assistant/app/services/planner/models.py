"""Pydantic data models for Journey Planning outputs."""

from typing import List, Optional
from pydantic import BaseModel as PydanticBaseModel, ConfigDict, Field


class RouteLeg(PydanticBaseModel):
    """A single leg or transit step within a topological RouteTemplate."""

    model_config = ConfigDict(extra="ignore")

    stage_index: int
    step_index: int
    leg_type: str  # "walk", "transit", "interchange", "platform_transfer"
    from_type: str
    from_id: str
    from_name: str
    to_type: str
    to_id: str
    to_name: str
    duration_minutes: int
    distance_m: Optional[int] = None
    transport_mode: Optional[str] = (
        None  # "bus", "rail", "metro", "tram", "ferry", "walk"
    )
    line_name: Optional[str] = None
    operator_name: Optional[str] = None
    stops_count: Optional[int] = None
    timetable_id: Optional[int] = None


class RouteTemplate(PydanticBaseModel):
    """Topological route corridor template discovered connecting origin to destination."""

    model_config = ConfigDict(extra="ignore")

    corridor_id: str
    name: str
    summary_text: str
    primary_mode: str = "bus"
    total_duration_est_minutes: int = 0
    transfer_count: int = 0
    stages_count: int = 1
    active_days: List[str] = Field(default_factory=list)
    legs: List[RouteLeg] = Field(default_factory=list)


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
    "RouteLeg",
    "RouteTemplate",
    "ItineraryEndpoint",
    "ItineraryLeg",
    "ScheduledItinerary",
]
