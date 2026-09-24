"""Peewee models for intra-station platform and stand transfers."""

from typing import List, Optional
from peewee import AutoField, BooleanField, CharField, IntegerField, TextField

from app.models.base import BaseModel


class PlatformTransfer(BaseModel):
    """Intra-station platform transfer configuration."""

    id = AutoField()
    location_type = CharField(default="rail")
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
        loc = (location_id or "").strip()
        f_plat = (from_platform or "").strip()
        t_plat = (to_platform or "").strip()

        # Normalise platform strings (e.g. "Platform 7" -> "7")
        f_clean = f_plat.lower().replace("platform", "").strip()
        t_clean = t_plat.lower().replace("platform", "").strip()

        # Handle same platform face (0 minute transfer)
        if f_clean and t_clean and f_clean == t_clean:
            return cls(
                location_type="rail",
                location_id=loc,
                location_name="",
                from_platform=f_plat,
                to_platform=t_plat,
                transfer_time_minutes=0,
                bidirectional=True,
                step_free=True,
                notes="Same platform face; no walking required.",
            )

        loc_candidates = {loc, loc.upper(), loc.lower()}
        if loc.startswith("9100"):
            bare = loc[4:]
            loc_candidates.update({bare, bare.upper()})
        else:
            loc_candidates.update({f"9100{loc}", f"9100{loc}".upper()})

        try:
            from app.services.dispatcher.station_resolver import resolve_station_crs

            crs = resolve_station_crs(loc)
            if crs:
                loc_candidates.update({crs, crs.upper()})
        except Exception:
            pass

        plat_from_candidates = [f_plat, f_clean]
        plat_to_candidates = [t_plat, t_clean]

        # Direct match
        direct = (
            cls.select()
            .where(
                (cls.location_id.in_(list(loc_candidates)))
                & (cls.from_platform.in_(plat_from_candidates))
                & (cls.to_platform.in_(plat_to_candidates))
            )
            .first()
        )
        if direct:
            return direct

        # Reverse match if bidirectional
        reverse = (
            cls.select()
            .where(
                (cls.location_id.in_(list(loc_candidates)))
                & (cls.from_platform.in_(plat_to_candidates))
                & (cls.to_platform.in_(plat_from_candidates))
                & (cls.bidirectional == True)  # noqa: E712
            )
            .first()
        )
        return reverse
