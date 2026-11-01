"""Peewee model for external API usage logging and cost telemetry."""

from typing import Any, Dict
from peewee import (
    AutoField,
    BooleanField,
    CharField,
    FloatField,
    IntegerField,
    TextField,
)

from app.models.base import BaseModel


class ApiUsageLog(BaseModel):
    """Audit log entry for an outbound external API call."""

    id = AutoField()
    provider = CharField(max_length=64, index=True)
    endpoint = CharField(max_length=128, index=True)
    caller = CharField(max_length=128, default="system")
    query_summary = TextField(default="")
    status_code = IntegerField(default=200)
    duration_ms = IntegerField(default=0)
    is_cached = BooleanField(default=False)
    estimated_cost_usd = FloatField(default=0.0)
    error_message = TextField(null=True)

    class Meta:
        table_name = "api_usage_logs"
        indexes = (
            (("provider", "created_at"), False),
            (("created_at",), False),
        )

    def to_dict(self, recurse: bool = False, **kwargs: Any) -> Dict[str, Any]:
        """Convert log entry to dictionary with formatted timestamp."""
        data = super().to_dict(recurse=recurse, **kwargs)
        data["created_at_iso"] = (
            self.created_at.isoformat() if getattr(self, "created_at", None) else ""
        )
        return data


__all__ = ["ApiUsageLog"]
