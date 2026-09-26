"""Peewee model for discovered and configured journey route templates."""

from typing import Any, Dict, List
from peewee import AutoField, BooleanField, CharField, IntegerField, TextField

from app.models.base import BaseModel, PydanticField


class JourneyRoute(BaseModel):
    """Discovered or custom route template for a configured Journey."""

    id = AutoField()
    journey_id = IntegerField(index=True)
    name = CharField()
    is_preferred = BooleanField(default=False)
    is_enabled = BooleanField(default=True)
    auto_generated = BooleanField(default=True)
    total_duration_est_minutes = IntegerField(default=0)
    transfer_count = IntegerField(default=0)
    stages_count = IntegerField(default=1)
    primary_mode = CharField(default="bus")
    legs = PydanticField(model_type=List[Dict[str, Any]], default=list)
    active_days = PydanticField(model_type=List[str], default=list)
    summary_text = TextField(null=True)

    class Meta:
        table_name = "journey_routes"
        indexes = ((("journey_id", "is_enabled"), False),)


__all__ = ["JourneyRoute"]
