"""Peewee model for configured transport timetables."""

from typing import Any, Dict, List, Optional
from peewee import AutoField, BooleanField, CharField, DateField

from app.models.base import BaseModel


class Timetable(BaseModel):
    """Configured public transit timetable metadata and operating schedules."""

    id = AutoField()
    name = CharField()
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

    class Meta:
        table_name = "timetables"

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
