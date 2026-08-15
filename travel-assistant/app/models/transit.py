"""Peewee models for public transit entities (routes, stops, stations, sync metadata)."""

import datetime
from typing import Any, Dict, List, Optional
from peewee import (
    AutoField,
    CharField,
    DateTimeField,
    FloatField,
    IntegerField,
    TextField,
)

from app.models.base import BaseModel


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
    def bulk_upsert(cls, routes: List[Dict[str, Any]], batch_size: int = 100) -> int:
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

        with cls._meta.database.atomic():
            return cls.insert_many(rows).execute()

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


class BusStop(BaseModel):
    """Bus stop / NaPTAN access node representation."""

    id = AutoField()
    atco_code = CharField(unique=True, index=True)
    naptan_code = CharField(null=True)
    name = CharField()
    indicator = CharField(null=True)
    locality = CharField(null=True)
    latitude = FloatField(null=True)
    longitude = FloatField(null=True)

    class Meta:
        table_name = "bus_stops"

    @classmethod
    def bulk_upsert(cls, stops: List[Dict[str, Any]], batch_size: int = 100) -> int:
        """Upsert a list of bus stops, updating name and coordinates on duplicate ATCO code."""
        if not stops:
            return 0

        now = datetime.datetime.utcnow()
        rows = [
            {
                "atco_code": str(s.get("atco_code", "")).strip(),
                "naptan_code": s.get("naptan_code"),
                "name": str(s.get("name", "")).strip(),
                "indicator": s.get("indicator"),
                "locality": s.get("locality"),
                "latitude": s.get("latitude"),
                "longitude": s.get("longitude"),
                "created_at": now,
                "updated_at": now,
            }
            for s in stops
            if s.get("atco_code") and s.get("name")
        ]

        with cls._meta.database.atomic():
            return (
                cls.insert_many(rows)
                .on_conflict(
                    conflict_target=[cls.atco_code],
                    preserve=[
                        cls.naptan_code,
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

    @classmethod
    def get_by_atco(cls, atco_code: str) -> Optional["BusStop"]:
        """Retrieve a bus stop by unique ATCO code."""
        try:
            return cls.get(cls.atco_code == atco_code.strip())
        except cls.DoesNotExist:
            return None

    @classmethod
    def search(cls, query: str, limit: int = 50) -> List["BusStop"]:
        """Search bus stops by name, ATCO code, or locality."""
        q = f"%{query.strip()}%"
        return list(
            cls.select()
            .where((cls.name**q) | (cls.atco_code**q) | (cls.locality**q))
            .limit(limit)
        )

    @classmethod
    def get_all(cls, limit: int = 100, offset: int = 0) -> List["BusStop"]:
        """Retrieve paginated bus stops."""
        return list(cls.select().offset(offset).limit(limit))


class Station(BaseModel):
    """National Rail passenger station representation."""

    id = AutoField()
    crs_code = CharField(unique=True, index=True, max_length=10)
    name = CharField()
    tiploc_code = CharField(null=True)
    latitude = FloatField(null=True)
    longitude = FloatField(null=True)
    operator = CharField(null=True)

    class Meta:
        table_name = "stations"

    @classmethod
    def bulk_upsert(cls, stations: List[Dict[str, Any]], batch_size: int = 100) -> int:
        """Upsert a list of rail stations, updating name and operator on duplicate CRS."""
        if not stations:
            return 0

        now = datetime.datetime.utcnow()
        rows = [
            {
                "crs_code": str(st.get("crs_code", "")).upper().strip(),
                "name": str(st.get("name", "")).strip(),
                "tiploc_code": st.get("tiploc_code"),
                "latitude": st.get("latitude"),
                "longitude": st.get("longitude"),
                "operator": st.get("operator"),
                "created_at": now,
                "updated_at": now,
            }
            for st in stations
            if st.get("crs_code") and st.get("name")
        ]

        with cls._meta.database.atomic():
            return (
                cls.insert_many(rows)
                .on_conflict(
                    conflict_target=[cls.crs_code],
                    preserve=[
                        cls.name,
                        cls.tiploc_code,
                        cls.latitude,
                        cls.longitude,
                        cls.operator,
                        cls.updated_at,
                    ],
                )
                .execute()
            )

    @classmethod
    def get_by_crs(cls, crs_code: str) -> Optional["Station"]:
        """Retrieve a station by 3-letter CRS code."""
        try:
            return cls.get(cls.crs_code == crs_code.upper().strip())
        except cls.DoesNotExist:
            return None

    @classmethod
    def search(cls, query: str, limit: int = 50) -> List["Station"]:
        """Search rail stations by name, CRS code, or TIPLOC code."""
        q = f"%{query.strip()}%"
        return list(
            cls.select()
            .where((cls.name**q) | (cls.crs_code**q) | (cls.tiploc_code**q))
            .limit(limit)
        )

    @classmethod
    def get_all(cls, limit: int = 100, offset: int = 0) -> List["Station"]:
        """Retrieve paginated rail stations."""
        return list(cls.select().offset(offset).limit(limit))


class SyncMetadata(BaseModel):
    """Synchronization status and telemetry for transit tables."""

    table_name = CharField(primary_key=True)
    last_updated_at = DateTimeField(null=True)
    status = CharField(default="idle")
    error_message = TextField(null=True)
    records_count = IntegerField(default=0)
    duration_seconds = FloatField(default=0.0)

    class Meta:
        table_name = "sync_metadata"

    @classmethod
    def record_start(cls, table_name: str) -> "SyncMetadata":
        """Record the start of a synchronization run."""
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
        """Record a successful synchronization completion."""
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
        """Record a failed synchronization run with error diagnostic."""
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
        """Record a skipped synchronization run."""
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
    def is_due_for_update(cls, table_name: str, max_age_seconds: int = 86400) -> bool:
        """Determine if a dataset table is due for a synchronization refresh."""
        meta = cls.get_meta(table_name)
        if not meta or not meta.last_updated_at:
            return True
        age = (datetime.datetime.utcnow() - meta.last_updated_at).total_seconds()
        return age > max_age_seconds
