"""Peewee model for configured journeys and multi-time-window schedules."""

from typing import Any, Dict, List, Optional, Union
from peewee import AutoField, CharField
from pydantic import BaseModel as PydanticBaseModel, ConfigDict, Field, field_validator

from app.models.base import BaseModel, PydanticField

VALID_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun", "bank_holiday")


class JourneyTimeSetting(PydanticBaseModel):
    """Configured multi-time-window schedule for a journey."""

    model_config = ConfigDict(extra="ignore")

    days: List[str] = Field(default_factory=list)
    mode: str = "depart"
    start_time: str = ""
    end_time: str = ""

    @field_validator("days", mode="before")
    @classmethod
    def validate_days(cls, v: Any) -> List[str]:
        """Validate and filter days to standard canonical days list."""
        if not isinstance(v, list):
            return []
        return [
            str(d).lower().strip() for d in v if str(d).lower().strip() in VALID_DAYS
        ]

    @field_validator("mode", mode="before")
    @classmethod
    def validate_mode(cls, v: Any) -> str:
        """Validate timing mode (depart or arrive)."""
        s = str(v).lower().strip() if v is not None else "depart"
        return s if s in ("depart", "arrive") else "depart"


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
    time_settings = PydanticField(model_type=List[JourneyTimeSetting], default=list)
    calculated_routes = PydanticField(
        model_type=Optional[Union[List[Any], Dict[str, Any], Any]],
        default=None,
        null=True,
    )

    class Meta:
        table_name = "journeys"
        indexes = (
            (("from_type", "from_id"), False),
            (("to_type", "to_id"), False),
        )

    def get_time_settings(self) -> List[Dict[str, Any]]:
        """Deserialise and return configured time settings list."""
        val = self.time_settings
        if isinstance(val, list):
            return [
                item.model_dump() if isinstance(item, PydanticBaseModel) else item
                for item in val
            ]
        return []

    def set_time_settings(
        self, settings_list: Union[List[JourneyTimeSetting], List[Dict[str, Any]]]
    ) -> None:
        """Serialise and store time settings list."""
        if not settings_list:
            self.time_settings = []
            return
        parsed: List[JourneyTimeSetting] = []
        for item in settings_list:
            if isinstance(item, JourneyTimeSetting):
                parsed.append(item)
            elif isinstance(item, dict):
                try:
                    parsed.append(JourneyTimeSetting.model_validate(item))
                except Exception:
                    continue
        self.time_settings = parsed

    def get_calculated_routes(self) -> Optional[Union[List[Any], Dict[str, Any], Any]]:
        """Deserialise and return calculated routes data."""
        val = self.calculated_routes
        if isinstance(val, (dict, list)):
            return val
        if isinstance(val, str):
            try:
                import json

                return json.loads(val)
            except Exception:
                return val
        return val

    def set_calculated_routes(
        self, routes: Optional[Union[List[Any], Dict[str, Any], str]]
    ) -> None:
        """Serialise and store calculated routes data."""
        if routes is None:
            self.calculated_routes = None
            return
        if isinstance(routes, str):
            try:
                import json

                self.calculated_routes = json.loads(routes)
            except Exception:
                self.calculated_routes = routes
            return
        self.calculated_routes = routes

    def to_dict(self, recurse: bool = False, **kwargs: Any) -> Dict[str, Any]:
        """Convert journey model to dictionary with parsed time settings and calculated routes."""
        data = super().to_dict(recurse=recurse, **kwargs)
        data["time_settings"] = self.get_time_settings()
        data["calculated_routes"] = self.get_calculated_routes()
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


__all__ = [
    "VALID_DAYS",
    "JourneyTimeSetting",
    "Journey",
]
