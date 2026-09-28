"""Data models package for Travel Assistant.

Provides declarative Peewee models for application settings, transit entities,
timetables, interchange transfers, and synchronization metadata.
"""

from app.models.base import BaseModel, PydanticField
from app.models.journey import Journey, JourneyTimeSetting
from app.models.location import Location
from app.models.setting import Setting
from app.models.timetable import (
    Timetable,
    TimetableContent,
    TimetableStop,
    TimetableTrip,
    TripTiming,
)
from app.models.transfer import PlatformTransfer
from app.models.transit import (
    Stop,
    StopInterchange,
    SyncMetadata,
)
from app.models.mcp import MCPTool
from app.models.journey_route import JourneyRoute
from app.models.route_query_log import RouteQueryLog
from app.models.walking import Walking

ALL_MODELS = [
    Setting,
    Timetable,
    SyncMetadata,
    Stop,
    StopInterchange,
    PlatformTransfer,
    Location,
    Journey,
    JourneyRoute,
    RouteQueryLog,
    Walking,
    MCPTool,
]

__all__ = [
    "BaseModel",
    "PydanticField",
    "Setting",
    "Timetable",
    "TripTiming",
    "TimetableStop",
    "TimetableTrip",
    "TimetableContent",
    "Location",
    "Journey",
    "JourneyRoute",
    "RouteQueryLog",
    "JourneyTimeSetting",
    "Walking",
    "Stop",
    "StopInterchange",
    "SyncMetadata",
    "PlatformTransfer",
    "MCPTool",
    "ALL_MODELS",
]
