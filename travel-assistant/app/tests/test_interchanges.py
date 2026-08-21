"""Unit tests for StopInterchange model, SQLite R*Tree geospatial discovery, and synchronisation."""

from unittest.mock import MagicMock, patch
from flask import Flask

from app.db import get_db_stats
from app.models import (
    Stop,
    StopInterchange,
    SyncMetadata,
)
from app.sync import (
    SYNC_REGISTRY,
    sync_stops,
    sync_table,
)
from app.sync.transit_sync import (
    find_nearby_stop_interchanges,
    populate_stops_rtree,
    sync_stop_interchanges,
)


def test_stop_interchange_model_crud(app: Flask) -> None:
    """Test StopInterchange model insertion, queries, and bulk_replace."""
    with app.app_context():
        # Clear existing
        StopInterchange.delete().execute()

        # Bulk replace
        records = [
            {
                "from_stop_atco": "0100B1",
                "from_stop_name": "High Street (Stop A)",
                "from_stop_type": "bus",
                "to_stop_atco": "9100PAD",
                "to_stop_name": "Paddington Station",
                "to_stop_type": "rail",
                "distance_metres": 150,
                "estimated_walk_minutes": 2,
            },
            {
                "from_stop_atco": "9100PAD",
                "from_stop_name": "Paddington Station",
                "from_stop_type": "rail",
                "to_stop_atco": "0100B1",
                "to_stop_name": "High Street (Stop A)",
                "to_stop_type": "bus",
                "distance_metres": 150,
                "estimated_walk_minutes": 2,
            },
        ]
        count = StopInterchange.bulk_replace(records)
        assert count == 2
        assert StopInterchange.select().count() == 2

        # Query helper
        outgoing = StopInterchange.get_interchanges_for_stop("0100B1")
        assert len(outgoing) == 1
        assert outgoing[0].to_stop_atco == "9100PAD"
        assert outgoing[0].distance_metres == 150
        assert outgoing[0].estimated_walk_minutes == 2
        assert outgoing[0].to_stop_type == "rail"

        # Bulk replace with empty list removes all
        StopInterchange.bulk_replace([])
        assert StopInterchange.select().count() == 0


def test_populate_stops_rtree(app: Flask) -> None:
    """Test populating SQLite stops_rtree virtual table with stops coordinates."""
    with app.app_context():
        Stop.delete().execute()

        # Insert 3 stops: 2 with valid coordinates, 1 with None
        Stop.create(
            atco_code="0100A",
            name="Stop A",
            stop_type="bus",
            easting=500000,
            northing=200000,
        )
        Stop.create(
            atco_code="0100B",
            name="Stop B",
            stop_type="rail",
            easting=500100,
            northing=200100,
        )
        Stop.create(
            atco_code="0100C",
            name="Stop C",
            stop_type="tram",
            easting=None,
            northing=None,
        )

        indexed_count = populate_stops_rtree()
        assert indexed_count == 2


def test_find_nearby_stop_interchanges_spatial_filter(app: Flask) -> None:
    """Test spatial R*Tree bounding box and exact Euclidean distance filtering."""
    with app.app_context():
        Stop.delete().execute()
        StopInterchange.delete().execute()

        # Stop A at (500000, 200000)
        Stop.create(
            atco_code="0100A",
            name="Stop A",
            stop_type="bus",
            easting=500000,
            northing=200000,
        )
        # Stop B at (500100, 200100) -> distance = sqrt(100^2 + 100^2) = 141.42m (<= 250m)
        Stop.create(
            atco_code="9100B",
            name="Station B",
            stop_type="rail",
            easting=500100,
            northing=200100,
        )
        # Stop C at (500200, 200200) -> distance from A = 282.84m (> 250m), from B = 141.42m (<= 250m)
        Stop.create(
            atco_code="0100C",
            name="Stop C",
            stop_type="bus",
            easting=500200,
            northing=200200,
        )
        # Stop D far away at (600000, 300000)
        Stop.create(
            atco_code="0100D",
            name="Stop D",
            stop_type="bus",
            easting=600000,
            northing=300000,
        )

        interchanges = find_nearby_stop_interchanges(radius_metres=250.0)
        # Expected pairs: A <-> B (2), B <-> C (2) => Total 4
        assert len(interchanges) == 4

        pair_keys = {
            (item["from_stop_atco"], item["to_stop_atco"]) for item in interchanges
        }
        assert ("0100A", "9100B") in pair_keys
        assert ("9100B", "0100A") in pair_keys
        assert ("9100B", "0100C") in pair_keys
        assert ("0100C", "9100B") in pair_keys
        assert ("0100A", "0100C") not in pair_keys
        assert ("0100A", "0100D") not in pair_keys

        # Check walk time calculation: 141m -> ceil(141.42 / 80) = 2 minutes
        for item in interchanges:
            assert item["distance_metres"] == 141
            assert item["estimated_walk_minutes"] == 2


def test_sync_stop_interchanges_success(app: Flask) -> None:
    """Test sync_stop_interchanges executes, populates StopInterchange table, and updates telemetry."""
    with app.app_context():
        Stop.delete().execute()
        StopInterchange.delete().execute()

        Stop.create(
            atco_code="0100A",
            name="Stop A",
            stop_type="bus",
            easting=500000,
            northing=200000,
        )
        Stop.create(
            atco_code="9100B",
            name="Station B",
            stop_type="rail",
            easting=500050,
            northing=200000,
        )

        result = sync_stop_interchanges(app=app)
        assert result["status"] == "success"
        assert result["records"] == 2
        assert "2 nearby stop interchange pairs" in result["message"]

        meta = SyncMetadata.get_meta("stop_interchanges")
        assert meta is not None
        assert meta.status == "success"
        assert meta.records_count == 2

        interchanges = list(StopInterchange.select())
        assert len(interchanges) == 2
        # 50m distance -> max(1, ceil(50 / 80)) = 1 min
        assert interchanges[0].distance_metres == 50
        assert interchanges[0].estimated_walk_minutes == 1


def test_sync_stop_interchanges_full_replace(app: Flask) -> None:
    """Test sync_stop_interchanges clears obsolete pairs when stops change."""
    with app.app_context():
        Stop.delete().execute()
        StopInterchange.delete().execute()

        # Initial two stops
        Stop.create(
            atco_code="0100A",
            name="Stop A",
            stop_type="bus",
            easting=500000,
            northing=200000,
        )
        Stop.create(
            atco_code="9100B",
            name="Station B",
            stop_type="rail",
            easting=500050,
            northing=200000,
        )
        sync_stop_interchanges(app=app)
        assert StopInterchange.select().count() == 2

        # Move Station B far away and re-sync
        Stop.update(easting=600000, northing=300000).where(
            Stop.atco_code == "9100B"
        ).execute()
        result = sync_stop_interchanges(app=app)
        assert result["status"] == "success"
        assert result["records"] == 0
        assert StopInterchange.select().count() == 0


def test_sync_stops_triggers_stop_interchanges_request(app: Flask) -> None:
    """Test sync_stops queues stop_interchanges sync upon successful stop ingest."""
    with app.app_context():
        mock_client = MagicMock()
        mock_client.fetch_stops.return_value = [
            {
                "atco_code": "0100TEST",
                "naptan_code": "tst1",
                "stop_type": "bus",
                "name": "Test Stop",
                "indicator": None,
                "locality": None,
                "latitude": 51.5,
                "longitude": -0.1,
                "easting": 500000,
                "northing": 200000,
            }
        ]

        with patch(
            "app.sync.transit_sync.NaptanClient.from_settings", return_value=mock_client
        ):
            with patch("app.sync.worker.request_sync") as mock_req_sync:
                res = sync_stops(app=app)
                assert res["status"] == "success"
                mock_req_sync.assert_called_with("stop_interchanges")


def test_sync_table_dispatches_stop_interchanges(app: Flask) -> None:
    """Test sync_table routes stop_interchanges and aliases properly."""
    with app.app_context():
        with patch(
            "app.sync.transit_sync.sync_stop_interchanges",
            return_value={
                "table": "stop_interchanges",
                "status": "success",
                "records": 5,
                "message": "ok",
                "duration_seconds": 0.1,
            },
        ) as mock_sync:
            res1 = sync_table("stop_interchanges")
            assert res1["status"] == "success"
            assert mock_sync.call_count == 1

            res2 = sync_table("interchanges")
            assert res2["status"] == "success"
            assert mock_sync.call_count == 2


def test_get_db_stats_includes_stop_interchanges(app: Flask) -> None:
    """Test get_db_stats reports stop_interchanges in tables list."""
    with app.app_context():
        stats = get_db_stats(app=app)
        table_names = [t["name"] for t in stats["tables"]]
        assert "stop_interchanges" in table_names

        interchange_stat = next(
            t for t in stats["tables"] if t["name"] == "stop_interchanges"
        )
        assert interchange_stat["syncable"] is True


def test_worker_registry_has_stop_interchanges() -> None:
    """Test SYNC_REGISTRY registers stop_interchanges with weekly max age."""
    names = [e.table_name for e in SYNC_REGISTRY]
    assert "stop_interchanges" in names

    entry = next(e for e in SYNC_REGISTRY if e.table_name == "stop_interchanges")
    assert entry.max_age_seconds == 604_800
    assert entry.sync_fn == sync_stop_interchanges
