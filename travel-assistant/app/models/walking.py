"""Peewee model for configured walking connections between locations."""

from typing import Any, Dict, List, Optional
from peewee import AutoField, BooleanField, CharField, IntegerField

from app.models.base import BaseModel


class Walking(BaseModel):
    """Configured walking connection between two locations or transit stops."""

    id = AutoField()
    start_type = CharField(default="custom")
    start_id = CharField()
    start_name = CharField()
    finish_type = CharField(default="custom")
    finish_id = CharField()
    finish_name = CharField()
    time_needed_minutes = IntegerField(default=5)
    bidirectional = BooleanField(default=True)

    class Meta:
        table_name = "walking"
        indexes = (
            (("start_type", "start_id"), False),
            (("finish_type", "finish_id"), False),
        )

    @classmethod
    def search(
        cls,
        query: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List["Walking"]:
        """Search and filter configured walking connections."""
        stmt = cls.select()

        if query and query.strip():
            q = f"%{query.strip()}%"
            stmt = stmt.where(
                (cls.start_name**q)
                | (cls.finish_name**q)
                | (cls.start_id**q)
                | (cls.finish_id**q)
            )

        return list(stmt.offset(offset).limit(limit))

    @classmethod
    def find_walking_route(
        cls,
        start_type: str,
        start_id: str,
        finish_type: str,
        finish_id: str,
    ) -> Optional["Walking"]:
        """Find walking route matching origin and destination (respecting bidirectional)."""
        s_type, s_id = start_type.strip(), start_id.strip()
        f_type, f_id = finish_type.strip(), finish_id.strip()

        # Direct match
        direct = (
            cls.select()
            .where(
                (cls.start_type == s_type)
                & (cls.start_id == s_id)
                & (cls.finish_type == f_type)
                & (cls.finish_id == f_id)
            )
            .first()
        )
        if direct:
            return direct

        # Reverse match if bidirectional
        reverse = (
            cls.select()
            .where(
                (cls.start_type == f_type)
                & (cls.start_id == f_id)
                & (cls.finish_type == s_type)
                & (cls.finish_id == s_id)
                & (cls.bidirectional == True)  # noqa: E712
            )
            .first()
        )
        return reverse

    @classmethod
    def get_stats(cls) -> Dict[str, Any]:
        """Aggregate summary counts of configured walking connections."""
        total = cls.select().count()
        return {
            "total": total,
        }
