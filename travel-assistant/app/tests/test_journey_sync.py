"""Unit tests for the background journey routes synchronisation job and update triggers."""

import datetime
from unittest.mock import patch
from flask import Flask
from flask.testing import FlaskClient
import pytest

from app.models import (
    Journey,
    Location,
    Stop,
    StopInterchange,
    SyncMetadata,
    Timetable,
    TimetableContent,
    TimetableStop,
    TimetableTrip,
    Walking,
)
from app.sync import (
    SYNC_REGISTRY,
    sync_journey_routes,
    sync_table,
)
from app.sync.journey_sync import calculate_routes_for_journey


@pytest.fixture
def seeded_transit_network(app: Flask):
    """Seed multi-modal test transit network with locations, stops, walking links, and timetables."""
    with app.app_context():
        # 1. Locations
        Location.create(
            id="ha:home",
            name="Home Residence",
            latitude=51.9000,
            longitude=-0.2000,
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
            latitude=51.9050,
            longitude=-0.2050,
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
            atco_code="210021204507",
            naptan_code="hrtdwjag",
            name="Sweyns Mead",
            stop_type="bus",
            indicator="Stop A",
            easting=524100,
            northing=225300,
        )
        Stop.create(
            atco_code="210021200011",
            naptan_code="hrtdgata",
            name="Stevenage Bus Station",
            stop_type="bus",
            indicator="Stop G",
            easting=524200,
            northing=225400,
        )
        Stop.create(
            atco_code="9100STEVNGE",
            naptan_code="SVG",
            name="Stevenage Rail Station",
            stop_type="rail",
            indicator="Station",
            easting=524300,
            northing=225500,
        )
        Stop.create(
            atco_code="9100CAMBNTH",
            naptan_code="CMB",
            name="Cambridge North Rail Station",
            stop_type="rail",
            indicator="Station",
            easting=547500,
            northing=261000,
        )

        # 3. Walking Connections
        Walking.create(
            start_type="ha",
            start_id="ha:home",
            start_name="Home Residence",
            finish_type="bus",
            finish_id="210021204507",
            finish_name="Sweyns Mead",
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
            start_id="9100CAMBNTH",
            start_name="Cambridge North Rail Station",
            finish_type="ha",
            finish_id="ha:work",
            finish_name="Tech Campus",
            time_needed_minutes=6,
            bidirectional=True,
        )

        # 4. Stop Interchanges
        StopInterchange.create(
            from_stop_atco="210021200011",
            from_stop_name="Stevenage Bus Station",
            from_stop_type="bus",
            to_stop_atco="9100STEVNGE",
            to_stop_name="Stevenage Rail Station",
            to_stop_type="rail",
            distance_metres=120,
            estimated_walk_minutes=2,
        )

        # 5. Timetables
        tt_bus = Timetable.create(
            name="Bus SB1",
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
                    TimetableStop(id="210021204507", name="Sweyns Mead", type="bus"),
                    TimetableStop(
                        id="210021200011", name="Stevenage Bus Station", type="bus"
                    ),
                ],
                trips=[
                    TimetableTrip(
                        id="sb1_01",
                        headsign="Bus Station",
                        operator="Arriva",
                        times=[{"dep": "07:30"}, {"arr": "07:42"}],
                    ),
                ],
            )
        )
        tt_bus.save()

        tt_train = Timetable.create(
            name="Great Northern",
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
                    TimetableStop(
                        id="9100STEVNGE", name="Stevenage Rail Station", type="rail"
                    ),
                    TimetableStop(
                        id="9100CAMBNTH",
                        name="Cambridge North Rail Station",
                        type="rail",
                    ),
                ],
                trips=[
                    TimetableTrip(
                        id="gn_01",
                        headsign="Cambridge North",
                        operator="Great Northern",
                        times=[{"dep": "07:50"}, {"arr": "08:25"}],
                    ),
                ],
            )
        )
        tt_train.save()


def test_sync_registry_contains_journey_routes() -> None:
    """Verify journey_routes is registered in SYNC_REGISTRY with 1 hour max age."""
    entry = next((e for e in SYNC_REGISTRY if e.table_name == "journey_routes"), None)
    assert entry is not None
    assert entry.max_age_seconds == 3600
    assert entry.sync_fn == sync_journey_routes


def test_calculate_routes_for_journey_direct_walk(
    seeded_transit_network: None, app: Flask
) -> None:
    """Test calculate_routes_for_journey finds direct walking route."""
    with app.app_context():
        journey = Journey.create(
            name="Walk to Parents",
            from_type="ha",
            from_id="ha:home",
            from_name="Home",
            to_type="custom",
            to_id="custom:parents_house",
            to_name="Parents",
            time_settings=[],
            calculated_routes=None,
        )

        routes = calculate_routes_for_journey(journey)
        assert routes is not None
        assert len(routes) >= 1
        assert routes[0].primary_mode == "walk"
        assert routes[0].total_duration_est_minutes == 12


def test_calculate_routes_for_journey_multi_modal_with_windows(
    seeded_transit_network: None, app: Flask
) -> None:
    """Test calculate_routes_for_journey with multiple configured time settings."""
    with app.app_context():
        journey = Journey.create(
            name="Commute to Work",
            from_type="ha",
            from_id="ha:home",
            from_name="Home",
            to_type="ha",
            to_id="ha:work",
            to_name="Work",
            time_settings=[
                {
                    "days": ["mon", "tue", "wed"],
                    "mode": "depart",
                    "start_time": "07:00",
                    "end_time": "09:00",
                },
                {
                    "days": ["sat", "sun"],
                    "mode": "depart",
                    "start_time": "10:00",
                    "end_time": "12:00",
                },
            ],
            calculated_routes=None,
        )

        routes = calculate_routes_for_journey(journey)
        assert routes is not None
        assert len(routes) >= 1
        corridor = routes[0]
        assert corridor.transfer_count >= 1
        assert len(corridor.legs) >= 3


def test_calculate_routes_for_journey_unreachable(
    seeded_transit_network: None, app: Flask
) -> None:
    """Test calculate_routes_for_journey returns None for unreachable endpoints."""
    with app.app_context():
        journey = Journey.create(
            name="Trip to Island",
            from_type="ha",
            from_id="ha:home",
            from_name="Home",
            to_type="custom",
            to_id="custom:isolated_spot",
            to_name="Isolated Island",
            time_settings=[],
            calculated_routes=None,
        )

        routes = calculate_routes_for_journey(journey)
        assert routes is None


def test_sync_journey_routes_end_to_end(
    seeded_transit_network: None, app: Flask
) -> None:
    """Test sync_journey_routes processes pending journeys and updates metadata."""
    with app.app_context():
        # Create 2 reachable journeys without routes
        j1 = Journey.create(
            name="Walk Trip",
            from_type="ha",
            from_id="ha:home",
            from_name="Home",
            to_type="custom",
            to_id="custom:parents_house",
            to_name="Parents",
            time_settings=[],
            calculated_routes=None,
        )
        j2 = Journey.create(
            name="Commute Trip",
            from_type="ha",
            from_id="ha:home",
            from_name="Home",
            to_type="ha",
            to_id="ha:work",
            to_name="Work",
            time_settings=[],
            calculated_routes=None,
        )
        # Create 1 unreachable journey without routes
        j3 = Journey.create(
            name="Unreachable Trip",
            from_type="ha",
            from_id="ha:home",
            from_name="Home",
            to_type="custom",
            to_id="custom:isolated_spot",
            to_name="Isolated",
            time_settings=[],
            calculated_routes=None,
        )
        # Create 1 journey that already has routes
        Journey.create(
            name="Already Calculated",
            from_type="ha",
            from_id="ha:home",
            from_name="Home",
            to_type="custom",
            to_id="custom:parents_house",
            to_name="Parents",
            time_settings=[],
            calculated_routes=[{"corridor_id": "existing"}],
        )

        result = sync_journey_routes(app=app)
        assert result["status"] == "success"
        assert result["records"] == 2
        assert result["table"] == "journey_routes"

        # Verify sync metadata
        meta = SyncMetadata.get_meta("journey_routes")
        assert meta is not None
        assert meta.status == "success"
        assert meta.records_count == 2

        # Verify models
        j1_fresh = Journey.get_by_id(j1.id)
        assert j1_fresh.calculated_routes is not None
        assert isinstance(j1_fresh.get_calculated_routes(), list)
        assert len(j1_fresh.get_calculated_routes()) >= 1

        j2_fresh = Journey.get_by_id(j2.id)
        assert j2_fresh.calculated_routes is not None
        assert isinstance(j2_fresh.get_calculated_routes(), list)

        j3_fresh = Journey.get_by_id(j3.id)
        # Unreachable journey remains None for future retries
        assert j3_fresh.calculated_routes is None

        # Re-running sync immediately should find 0 pending reachable journeys
        result2 = sync_journey_routes(app=app)
        assert result2["status"] == "success"
        assert result2["records"] == 0


def test_sync_table_journey_routes(seeded_transit_network: None, app: Flask) -> None:
    """Test sync_table dispatches to sync_journey_routes."""
    with app.app_context():
        res = sync_table("journey_routes", app=app)
        assert res["table"] == "journey_routes"
        assert res["status"] == "success"


def test_journey_changeset_triggers_sync_and_resets_routes(
    client: FlaskClient, app: Flask, seeded_transit_network: None
) -> None:
    """Test creating or editing a journey via config API resets calculated_routes and triggers sync."""
    with app.app_context():
        existing = Journey.create(
            name="Old Journey",
            from_type="ha",
            from_id="ha:home",
            from_name="Home",
            to_type="custom",
            to_id="custom:parents_house",
            to_name="Parents",
            time_settings=[],
            calculated_routes=[{"corridor_id": "old_route"}],
        )

        with patch("app.views.config.journeys.request_sync") as mock_request_sync:
            # 1. Update existing journey
            resp = client.post(
                "/config/journeys/data",
                json={
                    "added": [],
                    "updated": [
                        {
                            "id": existing.id,
                            "name": "Updated Journey",
                            "from_type": "ha",
                            "from_id": "ha:home",
                            "from_name": "Home",
                            "to_type": "ha",
                            "to_id": "ha:work",
                            "to_name": "Work",
                            "time_settings": [],
                        }
                    ],
                    "deleted": [],
                },
            )
            assert resp.status_code == 200
            mock_request_sync.assert_any_call("journey_routes")

            refreshed = Journey.get_by_id(existing.id)
            assert refreshed.name == "Updated Journey"
            assert refreshed.calculated_routes is None

        with patch("app.views.config.journeys.request_sync") as mock_request_sync:
            # 2. Add new journey
            resp2 = client.post(
                "/config/journeys/data",
                json={
                    "added": [
                        {
                            "name": "New Journey",
                            "from_type": "ha",
                            "from_id": "ha:home",
                            "from_name": "Home",
                            "to_type": "ha",
                            "to_id": "ha:work",
                            "to_name": "Work",
                            "time_settings": [],
                        }
                    ],
                    "updated": [],
                    "deleted": [],
                },
            )
            assert resp2.status_code == 200
            mock_request_sync.assert_any_call("journey_routes")

            new_j = Journey.get(Journey.name == "New Journey")
            assert new_j.calculated_routes is None
