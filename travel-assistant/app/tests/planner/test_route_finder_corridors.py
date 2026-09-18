"""Unit tests for multi-modal corridor discovery, direct walks, and intermediate stop compression."""

from __future__ import annotations

import datetime

from flask import Flask

from app.models.timetable import (
    Timetable,
    TimetableContent,
    TimetableStop,
    TimetableTrip,
)
from app.models.transit import Stop
from app.services.planner.models import RouteTemplate
from app.services.planner.route_finder import find_routes


def test_find_routes_direct_walk(seeded_planner: Flask) -> None:
    """Verify Mode 1 topological route discovery for a pure walking route."""
    with seeded_planner.app_context():
        routes = find_routes("ha", "ha:home", "custom", "custom:parents_house")
        assert len(routes) >= 1
        r = routes[0]
        assert isinstance(r, RouteTemplate)
        assert r.primary_mode == "walk"
        assert r.total_duration_est_minutes == 12
        assert r.transfer_count == 0
        assert len(r.legs) == 1
        assert r.legs[0].leg_type == "walk"
        assert r.legs[0].duration_minutes == 12


def test_find_routes_multi_modal(seeded_planner: Flask) -> None:
    """Verify Mode 1 topological route discovery for multi-modal chained corridor."""
    with seeded_planner.app_context():
        routes = find_routes(
            from_type="ha",
            from_id="ha:home",
            to_type="ha",
            to_id="ha:work",
            days_of_week=["mon"],
        )
        assert len(routes) >= 1
        r = routes[0]
        assert r.primary_mode in ("bus", "rail")
        assert len(r.legs) >= 3

        # Check legs structure: Walk -> Bus -> Interchange -> Rail -> Walk
        leg_types = [leg.leg_type for leg in r.legs]
        assert "walk" in leg_types
        assert "transit" in leg_types
        assert r.transfer_count >= 1

        # Verify JSON serialisation schema matching docs
        dumped = r.model_dump()
        assert "corridor_id" in dumped
        assert "legs" in dumped
        assert len(dumped["legs"]) == len(r.legs)


def test_find_routes_intercity_rail(seeded_planner: Flask) -> None:
    """Verify Mode 1 topological discovery for direct single-line rail."""
    with seeded_planner.app_context():
        routes = find_routes(
            "rail", "9100EUSTON", "rail", "9100MNCR", days_of_week=["mon"]
        )
        assert len(routes) == 1
        r = routes[0]
        assert r.primary_mode == "rail"
        assert r.transfer_count == 0
        assert any(leg.line_name == "Avanti West Coast" for leg in r.legs)


def test_find_routes_preserves_interchange_between_distinct_rail_services(
    seeded_planner: Flask,
) -> None:
    """Verify Mode 1 preserves intermediate stations and creates distinct legs across different services."""
    with seeded_planner.app_context():
        Stop.get_or_create(
            atco_code="9100CBG",
            defaults={
                "naptan_code": "CBG",
                "name": "Cambridge",
                "stop_type": "rail",
                "indicator": "Station",
            },
        )
        Stop.get_or_create(
            atco_code="9100CMB",
            defaults={
                "naptan_code": "CMB",
                "name": "Cambridge North",
                "stop_type": "rail",
                "indicator": "Station",
            },
        )

        # Service 1: King's Cross to Cambridge
        tt1 = Timetable.create(
            name="Great Northern (London to Cambridge)",
            transport_type="rail",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 12, 31),
        )
        tt1.set_content(
            TimetableContent(
                stops=[
                    TimetableStop(
                        id="9100KNGX", name="London King's Cross", type="rail"
                    ),
                    TimetableStop(id="9100CBG", name="Cambridge", type="rail"),
                ],
                trips=[
                    TimetableTrip(
                        id="gn_cbg_01",
                        headsign="Cambridge",
                        operator="Great Northern",
                        times=[{"dep": "08:00"}, {"arr": "08:50"}],
                    )
                ],
            )
        )
        tt1.save()

        # Service 2: Cambridge to Cambridge North
        tt2 = Timetable.create(
            name="Greater Anglia (Cambridge to Norwich)",
            transport_type="rail",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 12, 31),
        )
        tt2.set_content(
            TimetableContent(
                stops=[
                    TimetableStop(id="9100CBG", name="Cambridge", type="rail"),
                    TimetableStop(id="9100CMB", name="Cambridge North", type="rail"),
                ],
                trips=[
                    TimetableTrip(
                        id="ga_nor_01",
                        headsign="Norwich",
                        operator="Greater Anglia",
                        times=[{"dep": "08:55"}, {"arr": "09:00"}],
                    )
                ],
            )
        )
        tt2.save()

        routes = find_routes(
            "rail", "9100KNGX", "rail", "9100CMB", days_of_week=["mon"]
        )
        assert len(routes) >= 1
        r = routes[0]
        assert r.primary_mode == "rail"
        assert r.transfer_count == 1

        transit_legs = [leg for leg in r.legs if leg.leg_type == "transit"]
        assert len(transit_legs) == 2

        # Leg 1: London King's Cross -> Cambridge
        assert transit_legs[0].from_id == "9100KNGX"
        assert transit_legs[0].to_id == "9100CBG"
        assert transit_legs[0].line_name == "Great Northern (London to Cambridge)"

        # Leg 2: Cambridge -> Cambridge North
        assert transit_legs[1].from_id == "9100CBG"
        assert transit_legs[1].to_id == "9100CMB"
        assert transit_legs[1].line_name == "Greater Anglia (Cambridge to Norwich)"


def test_find_routes_compresses_intermediate_stops_within_same_service(
    seeded_planner: Flask,
) -> None:
    """Verify Mode 1 compresses intermediate calling points within a single continuous direct service."""
    with seeded_planner.app_context():
        Stop.get_or_create(
            atco_code="9100CBG",
            defaults={
                "naptan_code": "CBG",
                "name": "Cambridge",
                "stop_type": "rail",
                "indicator": "Station",
            },
        )
        Stop.get_or_create(
            atco_code="9100CMB",
            defaults={
                "naptan_code": "CMB",
                "name": "Cambridge North",
                "stop_type": "rail",
                "indicator": "Station",
            },
        )

        # Direct Service: King's Cross -> Cambridge -> Cambridge North
        tt_direct = Timetable.create(
            name="Great Northern Express (London to Kings Lynn)",
            transport_type="rail",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 12, 31),
        )
        tt_direct.set_content(
            TimetableContent(
                stops=[
                    TimetableStop(
                        id="9100KNGX", name="London King's Cross", type="rail"
                    ),
                    TimetableStop(id="9100CBG", name="Cambridge", type="rail"),
                    TimetableStop(id="9100CMB", name="Cambridge North", type="rail"),
                ],
                trips=[
                    TimetableTrip(
                        id="gn_direct_01",
                        headsign="Kings Lynn",
                        operator="Great Northern",
                        times=[
                            {"dep": "08:00"},
                            {"arr": "08:50", "dep": "08:52"},
                            {"arr": "08:57"},
                        ],
                    )
                ],
            )
        )
        tt_direct.save()

        routes = find_routes(
            "rail", "9100KNGX", "rail", "9100CMB", days_of_week=["mon"]
        )
        assert len(routes) >= 1

        direct_routes = [
            r
            for r in routes
            if len([leg for leg in r.legs if leg.leg_type == "transit"]) == 1
        ]
        assert len(direct_routes) >= 1
        r = direct_routes[0]
        assert r.transfer_count == 0

        transit_legs = [leg for leg in r.legs if leg.leg_type == "transit"]
        assert len(transit_legs) == 1
        assert transit_legs[0].from_id == "9100KNGX"
        assert transit_legs[0].to_id == "9100CMB"
        assert (
            transit_legs[0].line_name == "Great Northern Express (London to Kings Lynn)"
        )


def test_find_routes_with_time_window_filtering(seeded_planner: None) -> None:
    """Test that find_routes filters out timetables operating outside the journey window."""
    # Create two timetables: an early morning anomalous train and a regular commute train
    tt_early = Timetable.create(
        name="Rail King's Cross to Tech Campus (Night)",
        transport_type="rail",
        auto_added=False,
        monday=True,
        tuesday=True,
        wednesday=True,
        thursday=True,
        friday=True,
        stops_count=2,
        trips_count=1,
        content=TimetableContent(
            stops=[
                TimetableStop(id="9100KNGX", name="London King's Cross", type="rail"),
                TimetableStop(id="9100FPK", name="Finsbury Park", type="rail"),
            ],
            trips=[
                TimetableTrip(
                    id="night_trip",
                    times=[
                        {"dep": "05:15", "arr": "05:15"},
                        {"dep": "05:25", "arr": "05:25"},
                    ],
                )
            ],
        ),
    )

    tt_commute = Timetable.create(
        name="Rail King's Cross to Tech Campus (Commute)",
        transport_type="rail",
        auto_added=False,
        monday=True,
        tuesday=True,
        wednesday=True,
        thursday=True,
        friday=True,
        stops_count=2,
        trips_count=1,
        content=TimetableContent(
            stops=[
                TimetableStop(id="9100KNGX", name="London King's Cross", type="rail"),
                TimetableStop(id="9100FPK", name="Finsbury Park", type="rail"),
            ],
            trips=[
                TimetableTrip(
                    id="commute_trip",
                    times=[
                        {"dep": "08:30", "arr": "08:30"},
                        {"dep": "08:40", "arr": "08:40"},
                    ],
                )
            ],
        ),
    )

    # Search routes for commute window 08:00 to 09:30
    routes = find_routes(
        from_type="rail",
        from_id="9100KNGX",
        to_type="rail",
        to_id="9100FPK",
        days_of_week=["mon"],
        start_time="08:00",
        end_time="09:30",
        timing_mode="depart",
    )

    assert len(routes) >= 1
    # Transit leg should match the commute timetable ID, not the night service
    transit_legs = [leg for leg in routes[0].legs if leg.leg_type == "transit"]
    assert len(transit_legs) >= 1
    assert transit_legs[0].timetable_id == tt_commute.id
    assert transit_legs[0].timetable_id != tt_early.id
