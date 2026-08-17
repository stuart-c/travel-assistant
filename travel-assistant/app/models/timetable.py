"""Peewee model for configured transport timetables."""

from typing import Any, Dict, List, Optional
from peewee import AutoField, BooleanField, CharField, DateField

from app.models.base import BaseModel, JSONField


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
    content = JSONField(default=lambda: {"stops": [], "trips": []})

    class Meta:
        table_name = "timetables"

    def get_content(self) -> Dict[str, Any]:
        """Deserialise and return configured timetable stops and trips."""
        val = self.content
        if isinstance(val, dict):
            return {
                "stops": val.get("stops", []),
                "trips": val.get("trips", []),
            }
        return {"stops": [], "trips": []}

    def set_content(self, content_data: Dict[str, Any]) -> None:
        """Serialise and store timetable grid contents."""
        self.content = {
            "stops": (
                content_data.get("stops", []) if isinstance(content_data, dict) else []
            ),
            "trips": (
                content_data.get("trips", []) if isinstance(content_data, dict) else []
            ),
        }

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
