"""Data models and internal trip representations for the RAPTOR engine."""

from __future__ import annotations

from typing import Dict, List, Optional


class _ParsedTrip:
    """Internal representation of a timetable trip for the RAPTOR solver."""

    def __init__(
        self,
        trip_id: str,
        timetable_id: int,
        line_name: str,
        transport_mode: str,
        operator: Optional[str],
        headsign: Optional[str],
        stops: List[str],
        arr_times: List[Optional[int]],
        dep_times: List[Optional[int]],
        stop_indices: Optional[Dict[str, int]] = None,
    ) -> None:
        self.trip_id = trip_id
        self.timetable_id = timetable_id
        self.line_name = line_name
        self.transport_mode = transport_mode
        self.operator = operator
        self.headsign = headsign
        self.stops = stops
        self.arr_times = arr_times
        self.dep_times = dep_times
        self.stop_indices = (
            stop_indices
            if stop_indices is not None
            else {s: i for i, s in enumerate(stops)}
        )
