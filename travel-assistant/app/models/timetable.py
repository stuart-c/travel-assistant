"""Peewee model for configured transport timetables."""

from typing import Any, Dict, List, Optional, Union
from peewee import AutoField, BooleanField, CharField, DateField
from pydantic import BaseModel as PydanticBaseModel, ConfigDict, Field

from app.models.base import BaseModel, PydanticField


class TripTiming(PydanticBaseModel):
    """Arrival and departure timings for a timetable stop."""

    model_config = ConfigDict(extra="ignore")

    arr: Optional[str] = ""
    dep: Optional[str] = ""


class TimetableStop(PydanticBaseModel):
    """Configured stop entry within a timetable grid."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    type: str = "bus"
    indicator: Optional[str] = "Stop"
    icon: Optional[str] = "place"


class TimetableTrip(PydanticBaseModel):
    """Configured trip column with stop timings and operator metadata."""

    model_config = ConfigDict(extra="ignore")

    id: str
    headsign: str = ""
    times: List[Union[str, TripTiming, Dict[str, Any]]] = Field(default_factory=list)
    toc: Optional[str] = None
    operator: Optional[str] = None


class TimetableContent(PydanticBaseModel):
    """Complete timetable matrix content with stop rows and trip columns."""

    model_config = ConfigDict(extra="ignore")

    stops: List[TimetableStop] = Field(default_factory=list)
    trips: List[TimetableTrip] = Field(default_factory=list)


class Timetable(BaseModel):
    """Configured public transit timetable metadata, operating schedules, and grid contents."""

    id = AutoField()
    name = CharField()
    transport_type = CharField(default="bus")
    start_date = DateField(null=True)
    end_date = DateField(null=True)
    monday = BooleanField(default=True)
    tuesday = BooleanField(default=True)
    wednesday = BooleanField(default=True)
    thursday = BooleanField(default=True)
    friday = BooleanField(default=True)
    saturday = BooleanField(default=True)
    sunday = BooleanField(default=True)
    bank_holiday = BooleanField(default=True)
    auto_added = BooleanField(default=False)
    content = PydanticField(model_type=TimetableContent, default=TimetableContent)

    class Meta:
        table_name = "timetables"

    def get_content(self) -> Dict[str, Any]:
        """Deserialise and return configured timetable stops and trips."""
        val = self.content
        if isinstance(val, TimetableContent):
            return val.model_dump()
        if isinstance(val, dict):
            return {
                "stops": val.get("stops", []),
                "trips": val.get("trips", []),
            }
        return {"stops": [], "trips": []}

    def set_content(
        self, content_data: Union[TimetableContent, Dict[str, Any]]
    ) -> None:
        """Serialise and store timetable grid contents."""
        if isinstance(content_data, TimetableContent):
            self.content = content_data
        elif isinstance(content_data, dict):
            try:
                self.content = TimetableContent.model_validate(content_data)
            except Exception:
                self.content = TimetableContent()
        else:
            self.content = TimetableContent()

    def to_dict(self, recurse: bool = False, **kwargs: Any) -> Dict[str, Any]:
        """Convert timetable model to dictionary with parsed grid contents."""
        data = super().to_dict(recurse=recurse, **kwargs)
        data["transport_type"] = self.transport_type or "bus"
        data["auto_added"] = bool(self.auto_added)
        data["content"] = self.get_content()
        return data

    @classmethod
    def search(
        cls,
        query: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List["Timetable"]:
        """Search and filter timetables by name."""
        stmt = cls.select()

        if query and query.strip():
            q = f"%{query.strip()}%"
            stmt = stmt.where(cls.name**q)

        return list(stmt.offset(offset).limit(limit))

    @classmethod
    def get_stats(cls) -> Dict[str, Any]:
        """Aggregate summary counts of configured timetables."""
        total = cls.select().count()
        auto_count = cls.select().where(cls.auto_added == True).count()  # noqa: E712

        return {
            "total": total,
            "auto_count": auto_count,
            "custom_count": total - auto_count,
        }


__all__ = [
    "TripTiming",
    "TimetableStop",
    "TimetableTrip",
    "TimetableContent",
    "Timetable",
]
