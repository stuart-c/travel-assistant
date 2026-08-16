"""Peewee model for configured transport timetables."""

import json
from typing import Any, Dict, List, Optional
from peewee import AutoField, BooleanField, CharField, DateField, TextField

from app.models.base import BaseModel


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
    content = TextField(default='{"stops":[], "trips":[]}')

    class Meta:
        table_name = "timetables"

    def get_content(self) -> Dict[str, Any]:
        """Deserialise and return configured timetable stops and trips."""
        if not self.content:
            return {"stops": [], "trips": []}
        try:
            parsed = json.loads(self.content)
            if isinstance(parsed, dict):
                return {
                    "stops": parsed.get("stops", []),
                    "trips": parsed.get("trips", []),
                }
        except (json.JSONDecodeError, TypeError):
            pass
        return {"stops": [], "trips": []}

    def set_content(self, content_data: Dict[str, Any]) -> None:
        """Serialise and store timetable grid contents as JSON."""
        clean_content = {
            "stops": (
                content_data.get("stops", []) if isinstance(content_data, dict) else []
            ),
            "trips": (
                content_data.get("trips", []) if isinstance(content_data, dict) else []
            ),
        }
        self.content = json.dumps(clean_content)

    def to_dict(self, recurse: bool = False, **kwargs: Any) -> Dict[str, Any]:
        """Convert timetable model to dictionary with parsed grid contents."""
        data = super().to_dict(recurse=recurse, **kwargs)
        data["transport_type"] = self.transport_type or "bus"
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

        return {
            "total": total,
        }
