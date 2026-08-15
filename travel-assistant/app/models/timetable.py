"""Peewee model for configured transport timetables."""

from typing import Any, Dict, List, Optional
from peewee import AutoField, CharField, fn

from app.models.base import BaseModel


class Timetable(BaseModel):
    """Configured public transit timetable metadata."""

    id = AutoField()
    transport_type = CharField(max_length=50)
    name = CharField()
    identifier = CharField()
    status = CharField(default="active")

    class Meta:
        table_name = "timetables"

    @classmethod
    def search(
        cls,
        query: Optional[str] = None,
        transport_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List["Timetable"]:
        """Search and filter timetables by query text, transport mode, or active status."""
        stmt = cls.select()

        if query and query.strip():
            q = f"%{query.strip()}%"
            stmt = stmt.where((cls.name**q) | (cls.identifier**q))

        if transport_type and transport_type.strip():
            stmt = stmt.where(cls.transport_type == transport_type.strip())

        if status and status.strip():
            stmt = stmt.where(cls.status == status.strip())

        return list(stmt.offset(offset).limit(limit))

    @classmethod
    def get_stats(cls) -> Dict[str, Any]:
        """Aggregate summary counts of timetables grouped by mode and status."""
        total = cls.select().count()
        active = cls.select().where(cls.status == "active").count()
        inactive = cls.select().where(cls.status != "active").count()

        by_type_query = cls.select(
            cls.transport_type, fn.COUNT(cls.id).alias("count")
        ).group_by(cls.transport_type)
        by_type = {row.transport_type: row.count for row in by_type_query}

        return {
            "total": total,
            "active": active,
            "inactive": inactive,
            "by_type": by_type,
        }
