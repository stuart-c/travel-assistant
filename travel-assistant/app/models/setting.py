"""Peewee model for application configuration key-value settings."""

import datetime
from typing import Any, Dict, Optional
from peewee import CharField, TextField

from app.models.base import BaseModel


class Setting(BaseModel):
    """Key-value application settings storage model."""

    key = CharField(primary_key=True, max_length=100)
    value = TextField(default="")
    category = CharField(null=True, max_length=50)

    class Meta:
        table_name = "settings"

    @classmethod
    def get_val(cls, key: str, default: Optional[str] = "") -> Optional[str]:
        """Retrieve a configuration value by key."""
        try:
            item = cls.get(cls.key == key)
            return item.value if item.value is not None else default
        except cls.DoesNotExist:
            return default

    @classmethod
    def set_val(cls, key: str, value: Any, category: Optional[str] = None) -> "Setting":
        """Store or update a configuration setting value."""
        str_val = str(value) if value is not None else ""
        item, created = cls.get_or_create(
            key=key,
            defaults={
                "value": str_val,
                "category": category,
                "created_at": datetime.datetime.utcnow(),
                "updated_at": datetime.datetime.utcnow(),
            },
        )
        if not created:
            has_changed = False
            if item.value != str_val:
                item.value = str_val
                has_changed = True
            if category is not None and item.category != category:
                item.category = category
                has_changed = True
            if has_changed:
                item.updated_at = datetime.datetime.utcnow()
                item.save()
        return item

    @classmethod
    def get_all_dict(cls) -> Dict[str, str]:
        """Retrieve all configuration settings as a key-value dictionary."""
        query = cls.select(cls.key, cls.value)
        return {item.key: item.value for item in query}

    @classmethod
    def get_by_category(cls, category: str) -> Dict[str, str]:
        """Retrieve all settings under a specific category."""
        query = cls.select(cls.key, cls.value).where(cls.category == category)
        return {item.key: item.value for item in query}

    @classmethod
    def delete_key(cls, key: str) -> bool:
        """Delete a configuration setting by key."""
        count = cls.delete().where(cls.key == key).execute()
        return count > 0

    @classmethod
    def bulk_set(
        cls, settings_dict: Dict[str, Any], category: Optional[str] = None
    ) -> int:
        """Store or update multiple configuration key-value pairs atomically."""
        with cls._meta.database.atomic():
            count = 0
            for k, v in settings_dict.items():
                cls.set_val(k, v, category=category)
                count += 1
            return count
