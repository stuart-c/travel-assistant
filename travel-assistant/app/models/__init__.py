"""Data models package for Travel Assistant.

Provides declarative Peewee models for application settings, transit entities,
timetables, interchange transfers, and synchronization metadata.
"""

from app.models.base import BaseModel
from app.models.location import Location
from app.models.setting import Setting
from app.models.timetable import Timetable
from app.models.transfer import LocationTransfer, PlatformTransfer
from app.models.transit import BusRoute, BusStop, Station, SyncMetadata

ALL_MODELS = [
    Setting,
    Timetable,
    SyncMetadata,
    BusRoute,
    BusStop,
    Station,
    LocationTransfer,
    PlatformTransfer,
    Location,
]

__all__ = [
    "BaseModel",
    "Setting",
    "Timetable",
    "Location",
    "BusRoute",
    "BusStop",
    "Station",
    "SyncMetadata",
    "LocationTransfer",
    "PlatformTransfer",
    "ALL_MODELS",
]
