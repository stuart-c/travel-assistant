"""Base Peewee model class with timestamp tracking and JSON serialisation helpers."""

import datetime
from typing import Any, Dict
from peewee import DateTimeField, Model
from playhouse.shortcuts import model_to_dict

from app.db.core import db


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
