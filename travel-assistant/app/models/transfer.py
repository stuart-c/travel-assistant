"""Peewee models for interchange transfers between locations and platforms."""

from typing import List, Optional
from peewee import AutoField, BooleanField, CharField, IntegerField, TextField

from app.models.base import BaseModel


class LocationTransfer(BaseModel):
    """Inter-location transfer configuration between transit hubs."""

    id = AutoField()
    from_type = CharField()
    from_id = CharField()
    from_name = CharField()
    to_type = CharField()
    to_id = CharField()
    to_name = CharField()
    transfer_time_minutes = IntegerField(default=5)
    bidirectional = BooleanField(default=True)
    step_free = BooleanField(default=False)
    notes = TextField(null=True)

    class Meta:
        table_name = "location_transfers"
        indexes = (
            (("from_type", "from_id"), False),
            (("to_type", "to_id"), False),
        )

    @classmethod
    def search(
        cls,
        query: Optional[str] = None,
        from_type: Optional[str] = None,
        to_type: Optional[str] = None,
        step_free: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List["LocationTransfer"]:
        """Search and filter inter-location transfers."""
        stmt = cls.select()

        if query and query.strip():
            q = f"%{query.strip()}%"
            stmt = stmt.where(
                (cls.from_name**q)
                | (cls.to_name**q)
                | (cls.from_id**q)
                | (cls.to_id**q)
                | (cls.notes**q)
            )

        if from_type and from_type.strip():
            stmt = stmt.where(cls.from_type == from_type.strip())

        if to_type and to_type.strip():
            stmt = stmt.where(cls.to_type == to_type.strip())

        if step_free is not None:
            stmt = stmt.where(cls.step_free == step_free)

        return list(stmt.offset(offset).limit(limit))

    @classmethod
    def find_transfer(
        cls, from_type: str, from_id: str, to_type: str, to_id: str
    ) -> Optional["LocationTransfer"]:
        """Find transfer rule matching origin and destination (respecting bidirectional)."""
        f_type, f_id = from_type.strip(), from_id.strip()
        t_type, t_id = to_type.strip(), to_id.strip()

        # Direct match
        direct = (
            cls.select()
            .where(
                (cls.from_type == f_type)
                & (cls.from_id == f_id)
                & (cls.to_type == t_type)
                & (cls.to_id == t_id)
            )
            .first()
        )
        if direct:
            return direct

        # Reverse match if bidirectional
        reverse = (
            cls.select()
            .where(
                (cls.from_type == t_type)
                & (cls.from_id == t_id)
                & (cls.to_type == f_type)
                & (cls.to_id == f_id)
                & (cls.bidirectional == True)  # noqa: E712
            )
            .first()
        )
        return reverse


class PlatformTransfer(BaseModel):
    """Intra-station platform transfer configuration."""

    id = AutoField()
    location_type = CharField(default="station")
    location_id = CharField()
    location_name = CharField()
    from_platform = CharField()
    to_platform = CharField()
    transfer_time_minutes = IntegerField(default=2)
    bidirectional = BooleanField(default=True)
    step_free = BooleanField(default=False)
    notes = TextField(null=True)

    class Meta:
        table_name = "platform_transfers"
        indexes = ((("location_type", "location_id"), False),)

    @classmethod
    def search(
        cls,
        query: Optional[str] = None,
        location_id: Optional[str] = None,
        step_free: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List["PlatformTransfer"]:
        """Search and filter platform transfers."""
        stmt = cls.select()

        if query and query.strip():
            q = f"%{query.strip()}%"
            stmt = stmt.where(
                (cls.location_name**q)
                | (cls.location_id**q)
                | (cls.from_platform**q)
                | (cls.to_platform**q)
                | (cls.notes**q)
            )

        if location_id and location_id.strip():
            stmt = stmt.where(cls.location_id == location_id.strip())

        if step_free is not None:
            stmt = stmt.where(cls.step_free == step_free)

        return list(stmt.offset(offset).limit(limit))

    @classmethod
    def find_transfer(
        cls, location_id: str, from_platform: str, to_platform: str
    ) -> Optional["PlatformTransfer"]:
        """Find platform transfer matching platforms within a station."""
        loc = location_id.strip()
        f_plat = from_platform.strip()
        t_plat = to_platform.strip()

        # Direct match
        direct = (
            cls.select()
            .where(
                (cls.location_id == loc)
                & (cls.from_platform == f_plat)
                & (cls.to_platform == t_plat)
            )
            .first()
        )
        if direct:
            return direct

        # Reverse match if bidirectional
        reverse = (
            cls.select()
            .where(
                (cls.location_id == loc)
                & (cls.from_platform == t_plat)
                & (cls.to_platform == f_plat)
                & (cls.bidirectional == True)  # noqa: E712
            )
            .first()
        )
        return reverse
