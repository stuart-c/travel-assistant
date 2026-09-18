"""Unit tests for complex corridor scenarios: prefixed stop interchanges and diverse access stops."""

from __future__ import annotations

from flask import Flask

from app.models.location import Location
from app.models.timetable import (
    Timetable,
    TimetableContent,
    TimetableStop,
    TimetableTrip,
)
from app.models.transit import Stop, StopInterchange
from app.models.walking import Walking
from app.services.planner.route_finder import find_routes


def test_find_routes_with_prefixed_stop_interchanges(app: Flask) -> None:
    """Test that stop interchanges correctly connect prefixed Darwin rail stops with unprefixed bus stops."""
    with app.app_context():
        # Clean existing test data
        Walking.delete().execute()
        StopInterchange.delete().execute()
        Timetable.delete().execute()
        Stop.delete().execute()
        Location.delete().execute()

        # Endpoints
        Location.create(
            id="ha:home", name="Home", latitude=51.5, longitude=-0.1, ha=True
        )
        Location.create(
            id="ha:work", name="Work", latitude=51.6, longitude=-0.2, ha=True
        )

        # Stops
        Stop.create(atco_code="490000001A", name="Bus Origin", stop_type="bus")
        Stop.create(atco_code="490000001B", name="Bus Interchange", stop_type="bus")
        Stop.create(atco_code="9100RAIL1", name="Rail Station 1", stop_type="rail")
        Stop.create(atco_code="9100RAIL2", name="Rail Station 2", stop_type="rail")

        # Access & Egress
        Walking.create(
            start_type="ha",
            start_id="ha:home",
            start_name="Home",
            finish_type="bus",
            finish_id="490000001A",
            finish_name="Bus Origin",
            time_needed_minutes=5,
            bidirectional=True,
        )
        Walking.create(
            start_type="ha",
            start_id="ha:work",
            start_name="Work",
            finish_type="rail",
            finish_id="atco:9100RAIL2",
            finish_name="Rail Station 2",
            time_needed_minutes=4,
            bidirectional=True,
        )

        # Bus timetable
        tt_bus = Timetable.create(
            name="Bus Route 1",
            transport_type="bus",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
        )
        tt_bus.set_content(
            TimetableContent(
                stops=[
                    TimetableStop(id="490000001A", name="Bus Origin", type="bus"),
                    TimetableStop(id="490000001B", name="Bus Interchange", type="bus"),
                ],
                trips=[
                    TimetableTrip(
                        id="b1",
                        times=[{"dep": "08:00"}, {"arr": "08:15"}],
                    )
                ],
            )
        )
        tt_bus.save()

        # Rail timetable with atco: prefix
        tt_rail = Timetable.create(
            name="Train Line 1",
            transport_type="rail",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
        )
        tt_rail.set_content(
            TimetableContent(
                stops=[
                    TimetableStop(
                        id="atco:9100RAIL1", name="Rail Station 1", type="rail"
                    ),
                    TimetableStop(
                        id="atco:9100RAIL2", name="Rail Station 2", type="rail"
                    ),
                ],
                trips=[
                    TimetableTrip(
                        id="r1",
                        times=[{"dep": "08:25"}, {"arr": "08:50"}],
                    )
                ],
            )
        )
        tt_rail.save()

        # Stop interchange with raw ATCO codes (no atco: prefix)
        StopInterchange.create(
            from_stop_type="bus",
            from_stop_atco="490000001B",
            from_stop_name="Bus Interchange",
            to_stop_type="rail",
            to_stop_atco="9100RAIL1",
            to_stop_name="Rail Station 1",
            estimated_walk_minutes=3,
            distance_metres=150,
        )

        routes = find_routes(
            from_type="ha",
            from_id="ha:home",
            to_type="ha",
            to_id="ha:work",
            days_of_week=["mon"],
        )
        assert len(routes) >= 1
        r = routes[0]
        assert len(r.legs) == 5
        assert r.legs[0].leg_type == "walk"
        assert r.legs[1].leg_type == "transit"
        assert r.legs[2].leg_type == "interchange"
        assert r.legs[3].leg_type == "transit"
        assert r.legs[4].leg_type == "walk"


def test_find_routes_multiple_corridor_options(app: Flask) -> None:
    """Test find_routes returns multiple diverse route options via different access stops."""
    with app.app_context():
        # Clear previous data
        Walking.delete().execute()
        Timetable.delete().execute()
        StopInterchange.delete().execute()
        Location.delete().execute()

        Location.create(
            id="ha:home", name="Home", latitude=51.53, longitude=-0.12, ha=True
        )
        Location.create(
            id="ha:office", name="Office", latitude=52.23, longitude=0.14, ha=True
        )

        # Walking to Stop A (Sweyns Mead) and Stop B (Emperor's Head)
        Walking.create(
            start_type="ha",
            start_id="ha:home",
            start_name="Home",
            finish_type="bus",
            finish_id="atco:STOP_SWEYNS",
            finish_name="Sweyns Mead",
            time_needed_minutes=3,
            bidirectional=True,
        )
        Walking.create(
            start_type="ha",
            start_id="ha:home",
            start_name="Home",
            finish_type="bus",
            finish_id="atco:STOP_EMPEROR",
            finish_name="Emperor's Head",
            time_needed_minutes=4,
            bidirectional=True,
        )
        # Egress walking from Station North to Office
        Walking.create(
            start_type="rail",
            start_id="atco:9100CAMBNTH",
            start_name="Cambridge North",
            finish_type="ha",
            finish_id="ha:office",
            finish_name="Office",
            time_needed_minutes=5,
            bidirectional=True,
        )

        # Bus Line SB1 from Sweyns Mead to Station
        tt_sb1 = Timetable.create(
            name="Bus SB1: Woodcock Road to Bus Station",
            transport_type="bus",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
        )
        tt_sb1.set_content(
            TimetableContent(
                stops=[
                    TimetableStop(
                        id="atco:STOP_SWEYNS", name="Sweyns Mead", type="bus"
                    ),
                    TimetableStop(
                        id="atco:9100STEVNGE",
                        name="Stevenage Rail Station",
                        type="rail",
                    ),
                ],
                trips=[
                    TimetableTrip(
                        id="sb1_1", times=[{"dep": "07:30"}, {"arr": "07:45"}]
                    )
                ],
            )
        )
        tt_sb1.save()

        # Bus Line 38 from Emperor's Head to Station
        tt_38 = Timetable.create(
            name="Bus 38: Emperor's Head to Bus Station",
            transport_type="bus",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
        )
        tt_38.set_content(
            TimetableContent(
                stops=[
                    TimetableStop(
                        id="atco:STOP_EMPEROR", name="Emperor's Head", type="bus"
                    ),
                    TimetableStop(
                        id="atco:9100STEVNGE",
                        name="Stevenage Rail Station",
                        type="rail",
                    ),
                ],
                trips=[
                    TimetableTrip(
                        id="b38_1", times=[{"dep": "07:32"}, {"arr": "07:48"}]
                    )
                ],
            )
        )
        tt_38.save()

        # Train Line from Stevenage to Cambridge North
        tt_train = Timetable.create(
            name="Great Northern: Stevenage to Cambridge North",
            transport_type="rail",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
        )
        tt_train.set_content(
            TimetableContent(
                stops=[
                    TimetableStop(
                        id="atco:9100STEVNGE",
                        name="Stevenage Rail Station",
                        type="rail",
                    ),
                    TimetableStop(
                        id="atco:9100CAMBNTH", name="Cambridge North", type="rail"
                    ),
                ],
                trips=[
                    TimetableTrip(id="gn_1", times=[{"dep": "08:00"}, {"arr": "08:40"}])
                ],
            )
        )
        tt_train.save()

        routes = find_routes(
            from_type="ha",
            from_id="ha:home",
            to_type="ha",
            to_id="ha:office",
            days_of_week=["mon", "tue", "wed", "thu", "fri"],
        )

        assert len(routes) >= 2
        route_names = [r.name for r in routes]
        assert any("SB1" in n for n in route_names)
        assert any("38" in n for n in route_names)
