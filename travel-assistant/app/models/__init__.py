"""Data models package for Travel Assistant.

Provides declarative Peewee models for application settings, transit entities,
timetables, interchange transfers, and synchronization metadata.
"""

from app.models.base import BaseModel
from app.models.journey import Journey
from app.models.location import Location
from app.models.setting import Setting
from app.models.timetable import Timetable
from app.models.transfer import LocationTransfer, PlatformTransfer
from app.models.transit import (
    BusRoute,
    Stop,
    SyncMetadata,
)
from app.models.walking import Walking

ALL_MODELS = [
    Setting,
    Timetable,
    SyncMetadata,
    BusRoute,
    Stop,
    LocationTransfer,
    PlatformTransfer,
    Location,
    Journey,
    Walking,
]

__all__ = [
    "BaseModel",
    "Setting",
    "Timetable",
    "Location",
    "Journey",
    "Walking",
    "BusRoute",
    "Stop",
    "SyncMetadata",
    "LocationTransfer",
    "PlatformTransfer",
    "ALL_MODELS",
]
