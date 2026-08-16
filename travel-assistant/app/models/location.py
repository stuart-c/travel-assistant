"""Peewee model for configured geographic locations."""

import uuid
from typing import Any, Dict, List, Optional
from peewee import BooleanField, CharField, FloatField

from app.models.base import BaseModel


class Location(BaseModel):
    """Configured geographic location with name and coordinates."""

    id = CharField(primary_key=True, max_length=100)
    name = CharField()
    latitude = FloatField()
    longitude = FloatField()
    ha = BooleanField(default=False)

    class Meta:
        table_name = "locations"

    @staticmethod
    def generate_custom_id() -> str:
        """Generate a short unique identifier for custom locations."""
        return f"custom:{uuid.uuid4().hex[:8]}"

    def save(self, *args: Any, **kwargs: Any) -> int:
        """Ensure an ID is generated before saving if not already present."""
        if not self.id:
            self.id = self.generate_custom_id()
        return super().save(*args, **kwargs)

    @classmethod
    def search(
        cls,
        query: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List["Location"]:
        """Search locations by name or identifier."""
        stmt = cls.select()
        if query and query.strip():
            q = f"%{query.strip()}%"
            stmt = stmt.where((cls.name**q) | (cls.id**q))

        return list(stmt.offset(offset).limit(limit))

    @classmethod
    def get_stats(cls) -> Dict[str, Any]:
        """Aggregate summary counts of configured locations."""
        total = cls.select().count()
        ha_count = cls.select().where(cls.ha == True).count()  # noqa: E712
        return {
            "total": total,
            "ha_count": ha_count,
            "manual_count": total - ha_count,
        }
