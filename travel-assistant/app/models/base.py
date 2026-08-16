"""Base Peewee model class with timestamp tracking and JSON serialisation helpers."""

import datetime
import json
from typing import Any, Dict, Optional, Tuple
from peewee import DateTimeField, Model, TextField
from playhouse.shortcuts import model_to_dict

from app.db.core import db

# Canonical transport modes registry
TRANSPORT_MODES: Dict[str, Dict[str, str]] = {
    "rail": {
        "type": "rail",
        "label": "Train / Rail",
        "icon": "train",
        "indicator": "Rail",
        "description_label": "National Rail Station",
    },
    "bus": {
        "type": "bus",
        "label": "Bus",
        "icon": "directions_bus",
        "indicator": "Bus Stop",
        "description_label": "Bus Stop",
    },
    "tram": {
        "type": "tram",
        "label": "Tram",
        "icon": "tram",
        "indicator": "Tram",
        "description_label": "Tram Stop",
    },
    "metro": {
        "type": "metro",
        "label": "Metro / Underground",
        "icon": "subway",
        "indicator": "Metro",
        "description_label": "Metro Station",
    },
    "ferry": {
        "type": "ferry",
        "label": "Ferry",
        "icon": "directions_boat",
        "indicator": "Ferry",
        "description_label": "Ferry Terminal",
    },
    "air": {
        "type": "air",
        "label": "Flight / Air",
        "icon": "flight",
        "indicator": "Air",
        "description_label": "Airport Terminal",
    },
}

# Canonical location types for places and transfers
LOCATION_TYPES: Tuple[str, ...] = (
    "rail",
    "bus",
    "tram",
    "metro",
    "ferry",
    "air",
    "ha",
    "custom",
)


class JSONField(TextField):
    """Peewee TextField subclass with automatic JSON serialisation and deserialisation."""

    def __init__(self, default: Any = None, *args: Any, **kwargs: Any) -> None:
        self._json_default = default if default is not None else dict
        db_default = (
            json.dumps(
                self._json_default()
                if callable(self._json_default)
                else self._json_default
            )
            if default is not None
            else None
        )
        super().__init__(default=db_default, *args, **kwargs)

    def db_value(self, value: Any) -> Optional[str]:
        """Convert python dictionary or list to JSON string for database storage."""
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value)

    def python_value(self, value: Any) -> Any:
        """Convert database JSON string to Python dictionary or list."""
        if value is None or value == "":
            return (
                self._json_default()
                if callable(self._json_default)
                else self._json_default
            )
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return (
                self._json_default()
                if callable(self._json_default)
                else self._json_default
            )


class BaseModel(Model):
    """Base model class defining database binding, timestamps, and utility helpers."""

    created_at = DateTimeField(default=datetime.datetime.utcnow)
    updated_at = DateTimeField(default=datetime.datetime.utcnow)

    class Meta:
        database = db

    def save(self, *args: Any, **kwargs: Any) -> int:
        """Automatically refresh updated_at timestamp on model save."""
        self.updated_at = datetime.datetime.utcnow()
        return super().save(*args, **kwargs)

    def to_dict(self, recurse: bool = False, **kwargs: Any) -> Dict[str, Any]:
        """Convert model instance to a dictionary, formatting datetimes to ISO strings."""
        data = model_to_dict(self, recurse=recurse, **kwargs)
        for k, v in data.items():
            if isinstance(v, (datetime.datetime, datetime.date)):
                data[k] = v.isoformat()
        return data


__all__ = [
    "BaseModel",
    "JSONField",
    "TRANSPORT_MODES",
    "LOCATION_TYPES",
]
