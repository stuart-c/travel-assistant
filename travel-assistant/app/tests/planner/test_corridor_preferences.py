"""Unit tests for train continuity, transfer preference, and direct drop-off routing."""

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
from app.services.planner.raptor import plan_journey
from app.services.planner.route_finder import find_routes


def test_find_routes_direct_train_continuity(app: Flask) -> None:
    """Test find_routes maintains single direct train across intermediate stations."""
    with app.app_context():
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

        Walking.create(
            start_type="ha",
            start_id="ha:home",
            start_name="Home",
            finish_type="rail",
            finish_id="atco:9100STEVNGE",
            finish_name="Stevenage Station",
            time_needed_minutes=5,
            bidirectional=True,
        )
        Walking.create(
            start_type="rail",
            start_id="atco:9100CAMBDGE",
            start_name="Cambridge Station",
            finish_type="ha",
            finish_id="ha:office",
            finish_name="Office",
            time_needed_minutes=5,
            bidirectional=True,
        )

        # 1. Shorter train: Stevenage to Hitchin
        tt_short = Timetable.create(
            name="Short Train: Stevenage to Hitchin",
            transport_type="rail",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
        )
        tt_short.set_content(
            TimetableContent(
                stops=[
                    TimetableStop(id="atco:9100STEVNGE", name="Stevenage", type="rail"),
                    TimetableStop(id="atco:9100HITCHIN", name="Hitchin", type="rail"),
                ],
                trips=[
                    TimetableTrip(id="st_1", times=[{"dep": "08:00"}, {"arr": "08:08"}])
                ],
            )
        )
        tt_short.save()

        # 2. Long direct train: Stevenage -> Hitchin -> Cambridge
        tt_direct = Timetable.create(
            name="Direct Train: Stevenage to Cambridge",
            transport_type="rail",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
        )
        tt_direct.set_content(
            TimetableContent(
                stops=[
                    TimetableStop(id="atco:9100STEVNGE", name="Stevenage", type="rail"),
                    TimetableStop(id="atco:9100HITCHIN", name="Hitchin", type="rail"),
                    TimetableStop(id="atco:9100CAMBDGE", name="Cambridge", type="rail"),
                ],
                trips=[
                    TimetableTrip(
                        id="dt_1",
                        times=[{"dep": "08:00"}, {"arr": "08:08"}, {"arr": "08:45"}],
                    )
                ],
            )
        )
        tt_direct.save()

        routes = find_routes(
            from_type="ha",
            from_id="ha:home",
            to_type="ha",
            to_id="ha:office",
            days_of_week=["mon"],
        )

        assert len(routes) >= 1
        r = routes[0]
        # Should be: Walk -> Single Direct Train -> Walk (3 legs total)
        transit_legs = [leg for leg in r.legs if leg.leg_type == "transit"]
        assert len(transit_legs) == 1
        assert transit_legs[0].from_name == "Stevenage"
        assert transit_legs[0].to_name == "Cambridge"
        assert transit_legs[0].timetable_id == tt_direct.id


def test_find_routes_transfer_preference_and_direct_dropoff(app: Flask) -> None:
    """Test route finder prioritises routes with fewer changes and supports direct drop-off."""
    with app.app_context():
        Walking.delete().execute()
        Timetable.delete().execute()
        StopInterchange.delete().execute()
        Location.delete().execute()
        PlatformTransfer.delete().execute()

        Location.create(
            id="ha:home", name="Home", latitude=51.53, longitude=-0.12, ha=True
        )
        Location.create(
            id="ha:office", name="Office", latitude=52.23, longitude=0.14, ha=True
        )

        # Walking access to Stop A (Sweyns Mead) and Stop B (Emperor's Head)
        Walking.create(
            start_type="ha",
            start_id="ha:home",
            start_name="Home",
            finish_type="bus",
            finish_id="2100A",
            finish_name="Sweyns Mead",
            time_needed_minutes=3,
            bidirectional=True,
        )
        Walking.create(
            start_type="ha",
            start_id="ha:home",
            start_name="Home",
            finish_type="bus",
            finish_id="2100B",
            finish_name="Emperor's Head",
            time_needed_minutes=4,
            bidirectional=True,
        )

        # Bus from Stop A to Stevenage
        tt_bus_a = Timetable.create(
            name="Bus SB1: Sweyns Mead to Station",
            transport_type="bus",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
        )
        tt_bus_a.set_content(
            TimetableContent(
                stops=[
                    TimetableStop(id="2100A", name="Sweyns Mead", type="bus"),
                    TimetableStop(
                        id="2100STV_BUS", name="Stevenage Bus Station", type="bus"
                    ),
                ],
                trips=[
                    TimetableTrip(id="b1", times=[{"dep": "08:00"}, {"arr": "08:15"}])
                ],
            )
        )
        tt_bus_a.save()

        # Bus from Stop B to Stevenage
        tt_bus_b = Timetable.create(
            name="Bus 38: Emperor's Head to Station",
            transport_type="bus",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
        )
        tt_bus_b.set_content(
            TimetableContent(
                stops=[
                    TimetableStop(id="2100B", name="Emperor's Head", type="bus"),
                    TimetableStop(
                        id="2100STV_BUS", name="Stevenage Bus Station", type="bus"
                    ),
                ],
                trips=[
                    TimetableTrip(id="b2", times=[{"dep": "08:00"}, {"arr": "08:14"}])
                ],
            )
        )
        tt_bus_b.save()

        # Interchange walk at Stevenage
        StopInterchange.create(
            from_stop_atco="2100STV_BUS",
            from_stop_name="Stevenage Bus Station",
            from_stop_type="bus",
            to_stop_atco="9100STEVNGE",
            to_stop_name="Stevenage Rail Station",
            to_stop_type="rail",
            distance_metres=100,
            estimated_walk_minutes=2,
        )

        # 1-Change Rail Option: Stevenage -> Cambridge, then Cambridge -> Cambridge North
        tt_train_1 = Timetable.create(
            name="Rail: Stevenage to Cambridge",
            transport_type="rail",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
        )
        tt_train_1.set_content(
            TimetableContent(
                stops=[
                    TimetableStop(
                        id="9100STEVNGE", name="Stevenage Rail Station", type="rail"
                    ),
                    TimetableStop(
                        id="9100HITCHIN", name="Hitchin Rail Station", type="rail"
                    ),
                    TimetableStop(
                        id="9100ROYSTON", name="Royston Rail Station", type="rail"
                    ),
                    TimetableStop(
                        id="9100CAMBDGE", name="Cambridge Rail Station", type="rail"
                    ),
                ],
                trips=[
                    TimetableTrip(
                        id="r1",
                        times=[
                            {"dep": "08:20"},
                            {"arr": "08:26"},
                            {"arr": "08:40"},
                            {"arr": "08:55"},
                        ],
                    )
                ],
            )
        )
        tt_train_1.save()

        # Platform transfer at Cambridge
        PlatformTransfer.create(
            location_type="rail",
            location_id="9100CAMBDGE",
            location_name="Cambridge Rail Station",
            from_platform="1",
            to_platform="2",
            transfer_time_minutes=4,
        )

        tt_train_2 = Timetable.create(
            name="Rail: Cambridge to Cambridge North",
            transport_type="rail",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
        )
        tt_train_2.set_content(
            TimetableContent(
                stops=[
                    TimetableStop(
                        id="9100CAMBDGE", name="Cambridge Rail Station", type="rail"
                    ),
                    TimetableStop(
                        id="9100CAMBNTH",
                        name="Cambridge North Rail Station",
                        type="rail",
                    ),
                ],
                trips=[
                    TimetableTrip(id="r2", times=[{"dep": "09:00"}, {"arr": "09:05"}])
                ],
            )
        )
        tt_train_2.save()

        # Shuttle Bus from Cambridge North dropping off directly at ha:office (no walk)
        tt_shuttle = Timetable.create(
            name="Shuttle Bus (Morning)",
            transport_type="bus",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
        )
        tt_shuttle.set_content(
            TimetableContent(
                stops=[
                    TimetableStop(
                        id="9100CAMBNTH",
                        name="Cambridge North Rail Station",
                        type="rail",
                    ),
                    TimetableStop(id="ha:office", name="Office", type="ha"),
                ],
                trips=[
                    TimetableTrip(id="s1", times=[{"dep": "09:10"}, {"arr": "09:20"}])
                ],
            )
        )
        tt_shuttle.save()

        routes = find_routes(
            from_type="ha",
            from_id="ha:home",
            to_type="ha",
            to_id="ha:office",
            days_of_week=["mon"],
        )

        assert len(routes) >= 2
        # Verify routes from both Sweyns Mead and Emperor's Head are returned
        summaries = [r.summary_text for r in routes]
        assert any("Sweyns Mead" in s or "SB1" in s for s in summaries)
        assert any("Emperor's Head" in s or "38" in s for s in summaries)

        # Verify final leg terminates at Office without an artificial walk leg
        for r in routes:
            final_leg = r.legs[-1]
            assert final_leg.to_name == "Office"
            assert final_leg.to_id in ("office", "ha:office")
            assert final_leg.leg_type == "transit"
            assert final_leg.transport_mode == "bus"

        # Verify RAPTOR Mode 2 scheduled itinerary planning with direct drop-off
        plans = plan_journey(
            from_type="ha",
            from_id="ha:home",
            to_type="ha",
            to_id="ha:office",
            timing_mode="depart",
            time_str="07:50",
            days_of_week=["mon"],
        )
        assert len(plans) >= 1
        plan = plans[0]
        assert plan.arrival_time == "09:20"
        final_plan_leg = plan.legs[-1]
        assert final_plan_leg.destination.name == "Office"
        assert final_plan_leg.destination.id in ("office", "ha:office")
        assert final_plan_leg.mode == "bus"
