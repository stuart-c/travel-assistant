"""Peewee model for configured geographic locations."""

from typing import Any, Dict, List, Optional
from peewee import AutoField, CharField, FloatField

from app.models.base import BaseModel


class Location(BaseModel):
    """Configured geographic location with name and coordinates."""

    id = AutoField()
    name = CharField()
    latitude = FloatField()
    longitude = FloatField()

    class Meta:
        table_name = "locations"

    @classmethod
    def search(
        cls,
        query: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List["Location"]:
        """Search locations by name."""
        stmt = cls.select()
        if query and query.strip():
            q = f"%{query.strip()}%"
            stmt = stmt.where(cls.name**q)

        return list(stmt.offset(offset).limit(limit))

    @classmethod
    def get_stats(cls) -> Dict[str, Any]:
        """Aggregate summary counts of configured locations."""
        total = cls.select().count()
        return {
            "total": total,
        }
