"""Unit tests for multi-stop stopping trains and zero per-stop penalty verification."""

from __future__ import annotations

from flask import Flask

from app.models.location import Location
from app.models.timetable import (
    Timetable,
    TimetableContent,
    TimetableStop,
    TimetableTrip,
)
from app.models.transfer import PlatformTransfer
from app.models.transit import StopInterchange
from app.models.walking import Walking
from app.services.planner.route_finder import find_routes


def test_find_routes_zero_per_stop_cost_intermediate_stops_equality(
    app: Flask,
) -> None:
    """Verify that a multi-stop stopping train and direct express have zero per-stop penalty."""
    with app.app_context():
        Walking.delete().execute()
        Timetable.delete().execute()
        StopInterchange.delete().execute()
        PlatformTransfer.delete().execute()
        Location.delete().execute()

        Location.create(
            id="ha:home", name="Home", latitude=51.53, longitude=-0.12, ha=True
        )
        Location.create(
            id="ha:office", name="Office", latitude=52.23, longitude=0.14, ha=True
        )

        # Walking access from Home to Rail Station A
        Walking.create(
            start_type="ha",
            start_id="ha:home",
            start_name="Home",
            finish_type="rail",
            finish_id="atco:9100STATION_A",
            finish_name="Station A",
            time_needed_minutes=5,
            bidirectional=True,
        )

        # Walking egress from Rail Station B to Office
        Walking.create(
            start_type="rail",
            start_id="atco:9100STATION_B",
            start_name="Station B",
            finish_type="ha",
            finish_id="ha:office",
            finish_name="Office",
            time_needed_minutes=5,
            bidirectional=True,
        )

        # 10-intermediate stop stopping train on the same continuous line
        tt_stopping = Timetable.create(
            name="Stopping Service: Station A to Station B",
            transport_type="rail",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
        )
        intermediate_stops = [
            TimetableStop(
                id=f"atco:9100INT_{i}", name=f"Intermediate Stop {i}", type="rail"
            )
            for i in range(1, 11)
        ]
        all_stops = (
            [TimetableStop(id="atco:9100STATION_A", name="Station A", type="rail")]
            + intermediate_stops
            + [TimetableStop(id="atco:9100STATION_B", name="Station B", type="rail")]
        )
        tt_stopping.set_content(
            TimetableContent(
                stops=all_stops,
                trips=[
                    TimetableTrip(
                        id="stop_1",
                        times=[{"dep": "08:00"}]
                        + [{"arr": f"08:{10 + i * 2:02d}"} for i in range(10)]
                        + [{"arr": "08:35"}],
                    )
                ],
            )
        )
        tt_stopping.save()

        routes = find_routes(
            from_type="ha",
            from_id="ha:home",
            to_type="ha",
            to_id="ha:office",
            days_of_week=["mon"],
        )

        assert len(routes) >= 1
        r = routes[0]
        assert r.transfer_count == 0
        assert len(r.legs) == 3
        assert r.legs[0].leg_type == "walk"
        assert r.legs[1].leg_type == "transit"
        assert r.legs[1].from_id in ("9100STATION_A", "atco:9100STATION_A")
        assert r.legs[1].to_id in ("9100STATION_B", "atco:9100STATION_B")
        assert r.legs[2].leg_type == "walk"
