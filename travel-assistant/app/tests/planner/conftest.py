"""Pytest fixtures for journey planner test suites."""

from __future__ import annotations

import datetime

from flask import Flask
import pytest

from app.models.location import Location
from app.models.timetable import (
    Timetable,
    TimetableContent,
    TimetableStop,
    TimetableTrip,
)
from app.models.transfer import PlatformTransfer
from app.models.transit import Stop, StopInterchange
from app.models.walking import Walking
from app.services.planner.models import RouteLeg


@pytest.fixture
def seeded_planner(app: Flask):
    """Seed multi-modal testing data in app context."""
    with app.app_context():
        # 1. Locations
        Location.create(
            id="ha:home",
            name="Home Residence",
            latitude=51.5360,
            longitude=-0.1250,
            ha=True,
        )
        Location.create(
            id="ha:work",
            name="Tech Campus",
            latitude=52.2300,
            longitude=0.1500,
            ha=True,
        )
        Location.create(
            id="custom:parents_house",
            name="Parents' Residence",
            latitude=51.5600,
            longitude=-0.1000,
            ha=False,
        )
        Location.create(
            id="custom:isolated_spot",
            name="Isolated Island",
            latitude=50.0000,
            longitude=-5.0000,
            ha=False,
        )

        # 2. Transit Stops
        Stop.create(
            atco_code="490000077E",
            naptan_code="490000077E",
            name="King's Cross Station",
            stop_type="bus",
            indicator="Stop E",
        )
        Stop.create(
            atco_code="490000077C",
            naptan_code="490000077C",
            name="Euston Station",
            stop_type="bus",
            indicator="Stop C",
        )
        Stop.create(
            atco_code="9100KNGX",
            naptan_code="KGX",
            name="London King's Cross",
            stop_type="rail",
            indicator="Station",
        )
        Stop.create(
            atco_code="9100FPK",
            naptan_code="FPK",
            name="Finsbury Park Rail Station",
            stop_type="rail",
            indicator="Station",
        )
        Stop.create(
            atco_code="9100EUSTON",
            naptan_code="EUS",
            name="London Euston",
            stop_type="rail",
            indicator="Station",
        )
        Stop.create(
            atco_code="9100MNCR",
            naptan_code="MAN",
            name="Manchester Piccadilly",
            stop_type="rail",
            indicator="Station",
        )

        # 3. Walking Connections (Priority 1)
        Walking.create(
            start_type="ha",
            start_id="ha:home",
            start_name="Home Residence",
            finish_type="bus",
            finish_id="490000077E",
            finish_name="King's Cross Station",
            time_needed_minutes=4,
            bidirectional=True,
        )
        Walking.create(
            start_type="ha",
            start_id="ha:home",
            start_name="Home Residence",
            finish_type="custom",
            finish_id="custom:parents_house",
            finish_name="Parents' Residence",
            time_needed_minutes=12,
            bidirectional=True,
        )
        Walking.create(
            start_type="rail",
            start_id="9100FPK",
            start_name="Finsbury Park Rail Station",
            finish_type="ha",
            finish_id="ha:work",
            finish_name="Tech Campus",
            time_needed_minutes=6,
            bidirectional=True,
        )

        # 4. Nearby Stop Interchanges (Priority 2)
        StopInterchange.create(
            from_stop_atco="490000077C",
            from_stop_name="Euston Station",
            from_stop_type="bus",
            to_stop_atco="9100EUSTON",
            to_stop_name="London Euston",
            to_stop_type="rail",
            distance_metres=120,
            estimated_walk_minutes=2,
        )

        # 5. Station Platform Transfers (Priority 1 & Fallback)
        PlatformTransfer.create(
            location_type="rail",
            location_id="9100EUSTON",
            location_name="London Euston",
            from_platform="1",
            to_platform="4",
            transfer_time_minutes=3,
            bidirectional=True,
            step_free=True,
        )

        # 6. Timetables
        # Bus 73: King's Cross Station -> Euston Station
        tt_bus = Timetable.create(
            name="Bus 73",
            transport_type="bus",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
            saturday=False,
            sunday=False,
            bank_holiday=False,
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 12, 31),
        )
        tt_bus.set_content(
            TimetableContent(
                stops=[
                    TimetableStop(
                        id="490000077E", name="King's Cross Station", type="bus"
                    ),
                    TimetableStop(id="490000077C", name="Euston Station", type="bus"),
                ],
                trips=[
                    TimetableTrip(
                        id="bus73_01",
                        headsign="Euston Station",
                        operator="Arriva London",
                        times=[{"dep": "07:30"}, {"arr": "07:42"}],
                    ),
                    TimetableTrip(
                        id="bus73_02",
                        headsign="Euston Station",
                        operator="Arriva London",
                        times=[{"dep": "08:00"}, {"arr": "08:12"}],
                    ),
                ],
            )
        )
        tt_bus.save()

        # Train Thameslink: London Euston -> Finsbury Park
        tt_train = Timetable.create(
            name="Thameslink",
            transport_type="rail",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
            saturday=True,
            sunday=True,
            bank_holiday=True,
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 12, 31),
        )
        tt_train.set_content(
            TimetableContent(
                stops=[
                    TimetableStop(id="9100EUSTON", name="London Euston", type="rail"),
                    TimetableStop(
                        id="9100FPK",
                        name="Finsbury Park Rail Station",
                        type="rail",
                    ),
                ],
                trips=[
                    TimetableTrip(
                        id="tl_01",
                        headsign="Finsbury Park",
                        operator="Thameslink",
                        times=[
                            {"dep": "07:50"},
                            {"arr": "08:35"},
                        ],
                    ),
                    TimetableTrip(
                        id="tl_02",
                        headsign="Finsbury Park",
                        operator="Thameslink",
                        times=[
                            {"dep": "08:20"},
                            {"arr": "09:05"},
                        ],
                    ),
                ],
            )
        )
        tt_train.save()

        # Intercity Train: London Euston -> Manchester Piccadilly
        tt_intercity = Timetable.create(
            name="Avanti West Coast",
            transport_type="rail",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
            saturday=True,
            sunday=True,
            bank_holiday=True,
        )
        tt_intercity.set_content(
            TimetableContent(
                stops=[
                    TimetableStop(id="9100EUSTON", name="London Euston", type="rail"),
                    TimetableStop(
                        id="9100MNCR", name="Manchester Piccadilly", type="rail"
                    ),
                ],
                trips=[
                    TimetableTrip(
                        id="av_01",
                        headsign="Manchester",
                        operator="Avanti",
                        times=[{"dep": "09:00"}, {"arr": "11:06"}],
                    )
                ],
            )
        )
        tt_intercity.save()

        yield app


@pytest.fixture
def make_test_leg():
    """Fixture providing helper to construct lightweight RouteLeg instances for testing."""

    def _factory(
        leg_type: str = "transit",
        transport_mode: str = "bus",
        stage_index: int = 1,
        step_index: int = 1,
        from_id: str = "A",
        to_id: str = "B",
    ) -> RouteLeg:
        return RouteLeg(
            stage_index=stage_index,
            step_index=step_index,
            leg_type=leg_type,
            from_type="bus" if transport_mode == "bus" else "rail",
            from_id=from_id,
            from_name=f"Stop {from_id}",
            to_type="bus" if transport_mode == "bus" else "rail",
            to_id=to_id,
            to_name=f"Stop {to_id}",
            duration_minutes=5,
            transport_mode=transport_mode,
        )

    return _factory
