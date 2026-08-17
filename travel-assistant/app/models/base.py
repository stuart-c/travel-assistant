"""Base Peewee model class with timestamp tracking and Pydantic serialisation helpers."""

import datetime
import json
import logging
from typing import Any, Dict, Optional, Tuple
from peewee import DateTimeField, Field, Model
from playhouse.shortcuts import model_to_dict
from pydantic import BaseModel as PydanticBaseModel, TypeAdapter

from app.db.core import db

logger = logging.getLogger(__name__)

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


def _dump_pydantic_structure(val: Any) -> Any:
    """Recursively convert Pydantic models and datetimes to serialisable python primitives."""
    if isinstance(val, PydanticBaseModel):
        return val.model_dump()
    if isinstance(val, list):
        return [_dump_pydantic_structure(x) for x in val]
    if isinstance(val, dict):
        return {k: _dump_pydantic_structure(v) for k, v in val.items()}
    if isinstance(val, (datetime.datetime, datetime.date)):
        return val.isoformat()
    return val


class PydanticField(Field):
    """Peewee Field subclass with automatic Pydantic model validation and JSON serialisation."""

    field_type = "TEXT"

    def __init__(
        self, model_type: Any, default: Any = None, *args: Any, **kwargs: Any
    ) -> None:
        self.model_type = model_type
        self._type_adapter = TypeAdapter(model_type)
        self._pydantic_default = default
        super().__init__(default=default, *args, **kwargs)

    def db_value(self, value: Any) -> Optional[str]:
        """Convert Pydantic model, dictionary, or list to JSON string for database storage."""
        if value is None:
            return None
        if isinstance(value, str):
            return value
        try:
            if isinstance(value, (dict, list)) and not isinstance(
                value, PydanticBaseModel
            ):
                value = self._type_adapter.validate_python(value)
            dumped = self._type_adapter.dump_json(value)
            return dumped.decode("utf-8") if isinstance(dumped, bytes) else dumped
        except Exception:
            if hasattr(value, "model_dump"):
                return json.dumps(value.model_dump())
            return json.dumps(value)

    def python_value(self, value: Any) -> Any:
        """Convert database JSON string or python object to Pydantic model instance."""
        if value is None or value == "":
            return (
                self._pydantic_default()
                if callable(self._pydantic_default)
                else self._pydantic_default
            )
        if isinstance(value, str):
            try:
                return self._type_adapter.validate_json(value)
            except Exception as err:
                logger.warning("Failed to deserialise JSON in PydanticField: %s", err)
                return (
                    self._pydantic_default()
                    if callable(self._pydantic_default)
                    else self._pydantic_default
                )
        try:
            return self._type_adapter.validate_python(value)
        except Exception as err:
            logger.warning("Failed to validate object in PydanticField: %s", err)
            return (
                self._pydantic_default()
                if callable(self._pydantic_default)
                else self._pydantic_default
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
        """Convert model instance to a dictionary, formatting datetimes and Pydantic models."""
        data = model_to_dict(self, recurse=recurse, **kwargs)
        for k, v in data.items():
            data[k] = _dump_pydantic_structure(v)
        return data


__all__ = [
    "BaseModel",
    "PydanticField",
    "TRANSPORT_MODES",
    "LOCATION_TYPES",
]
