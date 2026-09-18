"""RAPTOR (Round-Based Public Transit Routing) trip scheduling engine (Mode 2)."""

from __future__ import annotations

from app.services.planner.raptor.connectivity import (
    _check_corridor_connectivity,
    _load_interchanges_for_stops,
)
from app.services.planner.raptor.engine import _run_raptor_forward
from app.services.planner.raptor.models import _ParsedTrip
from app.services.planner.raptor.planner import plan_journey
from app.services.planner.raptor.transfer_rules import _is_invalid_transfer
from app.services.planner.raptor.trips import (
    _TRIPS_CACHE,
    _TRIPS_CACHE_TTL_SECONDS,
    _build_stop_to_trips,
    _extract_parsed_trips,
    clear_raptor_cache,
)

__all__ = [
    "plan_journey",
    "clear_raptor_cache",
    "_TRIPS_CACHE",
    "_TRIPS_CACHE_TTL_SECONDS",
    "_ParsedTrip",
    "_is_invalid_transfer",
    "_load_interchanges_for_stops",
    "_check_corridor_connectivity",
    "_run_raptor_forward",
    "_extract_parsed_trips",
    "_build_stop_to_trips",
]
