"""Peewee models for public transit entities (routes, stops, stations, sync metadata)."""

import datetime
import logging
from typing import Any, Dict, List, Optional
from peewee import (
    AutoField,
    BooleanField,
    CharField,
    DateTimeField,
    FloatField,
    IntegerField,
    TextField,
)

from app.models.base import BaseModel

logger = logging.getLogger(__name__)


class BusRoute(BaseModel):
    """Bus route dataset representation."""

    id = AutoField()
    route_number = CharField(index=True)
    operator_name = CharField(null=True)
    operator_code = CharField(null=True)
    origin = CharField(null=True)
    destination = CharField(null=True)
    description = TextField(null=True)

    class Meta:
        table_name = "bus_routes"

    @classmethod
    def bulk_upsert(cls, routes: List[Dict[str, Any]], batch_size: int = 500) -> int:
        """Insert or replace a list of bus route records in batches."""
        if not routes:
            return 0

        now = datetime.datetime.utcnow()
        rows = [
            {
                "route_number": str(r.get("route_number", "")).strip(),
                "operator_name": r.get("operator_name"),
                "operator_code": r.get("operator_code"),
                "origin": r.get("origin"),
                "destination": r.get("destination"),
                "description": r.get("description"),
                "created_at": now,
                "updated_at": now,
            }
            for r in routes
            if r.get("route_number")
        ]

        if not rows:
            return 0

        total = 0
        with cls._meta.database.atomic():
            for i in range(0, len(rows), batch_size):
                batch = rows[i : i + batch_size]
                total += cls.insert_many(batch).execute()
        return total

    @classmethod
    def get_by_route_number(cls, route_number: str) -> List["BusRoute"]:
        """Retrieve bus routes matching route number."""
        return list(cls.select().where(cls.route_number == route_number.strip()))

    @classmethod
    def search(cls, query: str, limit: int = 50) -> List["BusRoute"]:
        """Search bus routes by route number, operator, or description."""
        q = f"%{query.strip()}%"
        return list(
            cls.select()
            .where(
                (cls.route_number**q) | (cls.operator_name**q) | (cls.description**q)
            )
            .limit(limit)
        )

    @classmethod
    def get_all(cls, limit: int = 100, offset: int = 0) -> List["BusRoute"]:
        """Retrieve paginated bus routes."""
        return list(cls.select().offset(offset).limit(limit))


class Stop(BaseModel):
    """Unified public transport access node representation (NaPTAN)."""

    id = AutoField()
    atco_code = CharField(unique=True, index=True)
    naptan_code = CharField(null=True, index=True)
    stop_type = CharField(index=True, default="bus")
    name = CharField(index=True)
    indicator = CharField(null=True)
    locality = CharField(null=True)
    latitude = FloatField(null=True)
    longitude = FloatField(null=True)

    class Meta:
        table_name = "stops"

    @classmethod
    def bulk_upsert(cls, stops: List[Dict[str, Any]], batch_size: int = 500) -> int:
        """Upsert a list of transit stops in chunked batches within an atomic transaction."""
        if not stops:
            return 0

        now = datetime.datetime.utcnow()
        rows = [
            {
                "atco_code": str(s.get("atco_code", "")).strip(),
                "naptan_code": str(s.get("naptan_code") or "").strip() or None,
                "stop_type": str(s.get("stop_type", "bus")).strip().lower() or "bus",
                "name": str(s.get("name", "")).strip(),
                "indicator": (
                    str(s.get("indicator")).strip()
                    if s.get("indicator") is not None
                    else None
                ),
                "locality": (
                    str(s.get("locality")).strip()
                    if s.get("locality") is not None
                    else None
                ),
                "latitude": s.get("latitude"),
                "longitude": s.get("longitude"),
                "created_at": now,
                "updated_at": now,
            }
            for s in stops
            if s.get("atco_code") and s.get("name")
        ]

        if not rows:
            return 0

        total = 0
        with cls._meta.database.atomic():
            for i in range(0, len(rows), batch_size):
                batch = rows[i : i + batch_size]
                total += (
                    cls.insert_many(batch)
                    .on_conflict(
                        conflict_target=[cls.atco_code],
                        preserve=[
                            cls.naptan_code,
                            cls.stop_type,
                            cls.name,
                            cls.indicator,
                            cls.locality,
                            cls.latitude,
                            cls.longitude,
                            cls.updated_at,
                        ],
                    )
                    .execute()
                )
        return total

    @classmethod
    def get_by_atco(cls, atco_code: str) -> Optional["Stop"]:
        """Retrieve a stop by unique ATCO code."""
        try:
            return cls.get(cls.atco_code == atco_code.strip())
        except cls.DoesNotExist:
            return None

    @classmethod
    def get_by_code(cls, code: str) -> Optional["Stop"]:
        """Retrieve a stop by ATCO code, NaPTAN code, or CRS code."""
        c = code.strip()
        try:
            return cls.get((cls.atco_code == c) | (cls.naptan_code == c))
        except cls.DoesNotExist:
            return None

    @classmethod
    def search(
        cls,
        query: str,
        stop_type: Optional[str] = None,
        limit: int = 50,
    ) -> List["Stop"]:
        """Search transit stops by name, ATCO code, NaPTAN code, or locality.

        Optionally filters by stop_type.
        """
        q = f"%{query.strip()}%"
        conditions = (
            (cls.name**q)
            | (cls.atco_code**q)
            | (cls.naptan_code**q)
            | (cls.locality**q)
        )
        if stop_type:
            st = stop_type.strip().lower()
            if st == "rail":
                conditions = conditions & (cls.stop_type.in_(["rail", "metro", "tram"]))
            elif st == "bus":
                conditions = conditions & (cls.stop_type == "bus")
            else:
                conditions = conditions & (cls.stop_type == st)
        return list(cls.select().where(conditions).limit(limit))

    @classmethod
    def get_all(cls, limit: int = 100, offset: int = 0) -> List["Stop"]:
        """Retrieve paginated transit stops."""
        return list(cls.select().offset(offset).limit(limit))


class SyncMetadata(BaseModel):
    """Synchronisation status and telemetry for transit tables."""

    table_name = CharField(primary_key=True)
    last_updated_at = DateTimeField(null=True)
    status = CharField(default="idle")
    error_message = TextField(null=True)
    records_count = IntegerField(default=0)
    duration_seconds = FloatField(default=0.0)
    sync_requested = BooleanField(default=False)

    class Meta:
        table_name = "sync_metadata"

    @classmethod
    def request_sync(cls, table_name: str) -> "SyncMetadata":
        """Mark a dataset table as requiring synchronisation.

        Sets the sync_requested flag and records a 'pending' status so callers can
        see the request has been queued before the background loop processes it.
        """
        now = datetime.datetime.utcnow()
        item, _ = cls.get_or_create(
            table_name=table_name,
            defaults={
                "status": "pending",
                "sync_requested": True,
                "created_at": now,
                "updated_at": now,
            },
        )
        item.sync_requested = True
        if item.status not in ("syncing",):
            item.status = "pending"
        item.updated_at = now
        item.save()
        return item

    @classmethod
    def clear_sync_requested(cls, table_name: str) -> None:
        """Atomically clear the sync_requested flag before executing a sync run."""
        cls.update(sync_requested=False).where(cls.table_name == table_name).execute()

    @classmethod
    def record_start(cls, table_name: str) -> "SyncMetadata":
        """Record the start of a synchronisation run."""
        now = datetime.datetime.utcnow()
        item, _ = cls.get_or_create(
            table_name=table_name,
            defaults={
                "status": "syncing",
                "last_updated_at": now,
                "created_at": now,
                "updated_at": now,
            },
        )
        item.status = "syncing"
        item.last_updated_at = now
        item.updated_at = now
        item.save()
        return item

    @classmethod
    def record_success(
        cls, table_name: str, records_count: int, duration_seconds: float
    ) -> "SyncMetadata":
        """Record a successful synchronisation completion."""
        now = datetime.datetime.utcnow()
        item, _ = cls.get_or_create(
            table_name=table_name,
            defaults={
                "status": "success",
                "last_updated_at": now,
                "records_count": records_count,
                "duration_seconds": duration_seconds,
                "error_message": None,
                "created_at": now,
                "updated_at": now,
            },
        )
        item.status = "success"
        item.records_count = records_count
        item.duration_seconds = duration_seconds
        item.error_message = None
        item.last_updated_at = now
        item.updated_at = now
        item.save()
        return item

    @classmethod
    def record_error(
        cls, table_name: str, error_message: str, duration_seconds: float
    ) -> "SyncMetadata":
        """Record a failed synchronisation run with error diagnostic."""
        logger.error(
            "Synchronisation error for '%s' (duration=%.2fs): %s",
            table_name,
            duration_seconds,
            error_message,
        )
        now = datetime.datetime.utcnow()
        item, _ = cls.get_or_create(
            table_name=table_name,
            defaults={
                "status": "error",
                "error_message": error_message,
                "duration_seconds": duration_seconds,
                "last_updated_at": now,
                "created_at": now,
                "updated_at": now,
            },
        )
        item.status = "error"
        item.error_message = error_message
        item.duration_seconds = duration_seconds
        item.updated_at = now
        item.save()
        return item

    @classmethod
    def record_skipped(cls, table_name: str, message: str) -> "SyncMetadata":
        """Record a skipped synchronisation run."""
        logger.warning(
            "Synchronisation skipped for '%s': %s",
            table_name,
            message,
        )
        now = datetime.datetime.utcnow()
        item, _ = cls.get_or_create(
            table_name=table_name,
            defaults={
                "status": "skipped",
                "error_message": message,
                "created_at": now,
                "updated_at": now,
            },
        )
        item.status = "skipped"
        item.error_message = message
        item.updated_at = now
        item.save()
        return item

    @classmethod
    def get_meta(cls, table_name: str) -> Optional["SyncMetadata"]:
        """Retrieve sync metadata for a specific table."""
        try:
            return cls.get(cls.table_name == table_name)
        except cls.DoesNotExist:
            return None

    @classmethod
    def cleanup_obsolete_entries(cls, valid_table_names: List[str]) -> int:
        """Delete sync metadata entries for tables not present in valid_table_names."""
        if not valid_table_names:
            return 0
        return cls.delete().where(cls.table_name.not_in(valid_table_names)).execute()

    @classmethod
    def is_due_for_update(cls, table_name: str, max_age_seconds: int = 86400) -> bool:
        """Determine if a dataset table is due for a synchronisation refresh."""
        meta = cls.get_meta(table_name)
        if not meta or not meta.last_updated_at:
            return True
        age = (datetime.datetime.utcnow() - meta.last_updated_at).total_seconds()
        return age > max_age_seconds
