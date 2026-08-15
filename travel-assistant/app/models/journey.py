"""Peewee model for configured journeys and multi-time-window schedules."""

import json
from typing import Any, Dict, List, Optional
from peewee import AutoField, CharField, TextField

from app.models.base import BaseModel


class Journey(BaseModel):
    """Configured travel journey between two locations with optional time settings."""

    id = AutoField()
    name = CharField()
    from_type = CharField()
    from_id = CharField()
    from_name = CharField()
    to_type = CharField()
    to_id = CharField()
    to_name = CharField()
    time_settings = TextField(default="[]")

    class Meta:
        table_name = "journeys"
        indexes = (
            (("from_type", "from_id"), False),
            (("to_type", "to_id"), False),
        )

    def get_time_settings(self) -> List[Dict[str, Any]]:
        """Deserialise and return configured time settings list."""
        if not self.time_settings:
            return []
        try:
            parsed = json.loads(self.time_settings)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
        return []

    def set_time_settings(self, settings_list: List[Dict[str, Any]]) -> None:
        """Serialise and store time settings list as JSON."""
        self.time_settings = json.dumps(settings_list or [])

    def to_dict(self, recurse: bool = False, **kwargs: Any) -> Dict[str, Any]:
        """Convert journey model to dictionary with parsed time settings."""
        data = super().to_dict(recurse=recurse, **kwargs)
        data["time_settings"] = self.get_time_settings()
        return data

    @classmethod
    def search(
        cls,
        query: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List["Journey"]:
        """Search and filter configured journeys."""
        stmt = cls.select()

        if query and query.strip():
            q = f"%{query.strip()}%"
            stmt = stmt.where(
                (cls.name**q)
                | (cls.from_name**q)
                | (cls.to_name**q)
                | (cls.from_id**q)
                | (cls.to_id**q)
            )

        return list(stmt.offset(offset).limit(limit))

    @classmethod
    def get_stats(cls) -> Dict[str, Any]:
        """Aggregate summary counts of configured journeys."""
        total = cls.select().count()
        return {
            "total": total,
        }
