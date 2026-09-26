"""Peewee model for routing API query audit logs and evaluation."""

from typing import Any, Dict, List
from peewee import AutoField, CharField, FloatField, IntegerField, TextField

from app.models.base import BaseModel, PydanticField


class RouteQueryLog(BaseModel):
    """Audit log of routing API queries and responses."""

    id = AutoField()
    journey_id = IntegerField(index=True)
    query_type = CharField(default="initial_discovery")
    trigger_reason = TextField(default="")
    origin_lat = FloatField()
    origin_lng = FloatField()
    dest_lat = FloatField()
    dest_lng = FloatField()
    departure_time = CharField(null=True)
    raw_response = PydanticField(model_type=Dict[str, Any], default=dict)
    parsed_summary = PydanticField(model_type=List[Dict[str, Any]], default=list)
    selected_route_id = IntegerField(null=True)

    class Meta:
        table_name = "journey_route_queries"
        indexes = ((("journey_id", "created_at"), False),)


__all__ = ["RouteQueryLog"]
