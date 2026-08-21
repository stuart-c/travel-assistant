"""Unit tests for transit dataset synchronisation and background sync worker."""

from typing import Any
from unittest.mock import MagicMock, patch
import requests
from flask import Flask

from app.models import (
    BusRoute,
    RailReference,
    Setting,
    Stop,
    SyncMetadata,
)
from app.sync import (
    SyncWorker,
    get_background_worker,
    request_sync,
    start_background_worker,
    stop_background_worker,
    sync_bus_routes,
    sync_rail_references,
    sync_stops,
    sync_table,
)


def test_sync_bus_routes_missing_credentials(app: Flask) -> None:
    """Test sync_bus_routes records skipped status when API key is missing."""
    with app.app_context():
        res = sync_bus_routes(app=app)
        assert res["status"] == "skipped_no_credentials"
        assert res["records"] == 0
        assert "not configured" in res["message"]

        meta = SyncMetadata.get_meta("bus_routes")
        assert meta is not None
        assert meta.status == "skipped"


def test_sync_bus_routes_auth_error(app: Flask) -> None:
    """Test sync_bus_routes handles 401/403 authentication failures."""
    with app.app_context():
        Setting.set_val("bus_api_key", "invalid-key")

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        with patch("requests.get", return_value=mock_resp):
            res = sync_bus_routes(app=app)
            assert res["status"] == "error"
            assert "Invalid Bus API key" in res["message"]

        meta = SyncMetadata.get_meta("bus_routes")
        assert meta is not None
        assert meta.status == "error"


def test_sync_bus_routes_success_with_lines(app: Flask) -> None:
    """Test sync_bus_routes successfully ingests line records."""
    with app.app_context():
        Setting.set_val("bus_api_key", "valid-key")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {
                    "name": "Oxfordshire Network",
                    "operator_name": "Oxford Bus Company",
                    "noc": ["OBC"],
                    "origin": "Oxford",
                    "destination": "London",
                    "description": "Express line",
                    "lines": ["OX-TUBE", "1"],
                },
                {
                    "id": 999,
                    "name": "Fallback Group",
                    "operator_name": "Stagecoach",
                    "noc": [],
                    "origin": "Witney",
                    "destination": "Oxford",
                    "comment": "Local line",
                    "lines": [],
                },
            ]
        }
        with patch("requests.get", return_value=mock_resp):
            res = sync_bus_routes(app=app)
            assert res["status"] == "success"
            assert res["records"] == 2

        routes = list(BusRoute.select())
        assert len(routes) == 2
        route_numbers = [r.route_number for r in routes]
        assert "OX-TUBE" in route_numbers
        assert "1" in route_numbers


def test_sync_bus_routes_request_exception(app: Flask) -> None:
    """Test sync_bus_routes handles network/requests exceptions."""
    with app.app_context():
        Setting.set_val("bus_api_key", "valid-key")

        with patch(
            "requests.get", side_effect=requests.exceptions.ConnectTimeout("Timeout")
        ):
            res = sync_bus_routes(app=app)
            assert res["status"] == "error"
            assert "Network or API error" in res["message"]


def test_sync_bus_routes_unexpected_exception(app: Flask) -> None:
    """Test sync_bus_routes handles general unexpected exceptions."""
    with app.app_context():
        Setting.set_val("bus_api_key", "valid-key")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("Corrupt JSON")
        with patch("requests.get", return_value=mock_resp):
            res = sync_bus_routes(app=app)
            assert res["status"] == "error"
            assert "Unexpected error" in res["message"]


def test_sync_stops_success(app: Flask) -> None:
    """Test sync_stops successfully parses NaPTAN CSV access nodes."""
    with app.app_context():
        csv_data = (
            "ATCOCode,NaptanCode,StopType,CommonName,Indicator,LocalityName,Latitude,Longitude\n"
            "0100BRP90310,bstpwat,BCT,Broad Quay,Stop C3,Bristol,51.452,-2.597\n"
            "9100PADTON,PAD,RLY,London Paddington,Platforms,London,51.517,-0.177\n"
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = csv_data
        with patch("requests.get", return_value=mock_resp):
            res = sync_stops(app=app)
            assert res["status"] == "success"
            assert res["records"] == 2
            assert "UK transit stops" in res["message"]

        stops = list(Stop.select())
        assert len(stops) == 2
        assert stops[0].atco_code == "0100BRP90310"
        assert stops[0].stop_type == "bus"
        assert stops[1].atco_code == "9100PADTON"
        assert stops[1].stop_type == "rail"


def test_sync_stops_network_and_unexpected_exceptions(app: Flask) -> None:
    """Test sync_stops exception capturing for connection and runtime errors."""
    with app.app_context():
        with patch(
            "requests.get", side_effect=requests.exceptions.ConnectionError("Failed")
        ):
            res = sync_stops(app=app)
            assert res["status"] == "error"
            assert "Network or connection error" in res["message"]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "ATCOCode,CommonName\n0100A,Stop A\n"
        with patch("requests.get", return_value=mock_resp):
            with patch.object(
                Stop, "bulk_upsert", side_effect=RuntimeError("Fatal error")
            ):
                res = sync_stops(app=app)
                assert res["status"] == "error"
                assert "Unexpected error" in res["message"]


def test_sync_table_dispatch(app: Flask) -> None:
    """Test sync_table dispatches to appropriate provider or returns error for invalid name."""
    with app.app_context():
        res_invalid = sync_table("invalid_table")
        assert res_invalid["status"] == "error"
        assert "Unknown or non-syncable table" in res_invalid["message"]

        with patch(
            "app.sync.transit_sync.sync_bus_routes",
            return_value={"status": "success", "records": 5},
        ):
            res = sync_table("bus_routes")
            assert res["status"] == "success"

        with patch(
            "app.sync.transit_sync.sync_stops",
            return_value={"status": "success", "records": 3},
        ):
            res = sync_table("stops")
            assert res["status"] == "success"

        with patch(
            "app.sync.transit_sync.sync_train_timetables",
            return_value={"status": "success", "records": 7},
        ):
            res = sync_table("train_timetables")
            assert res["status"] == "success"


def test_sync_train_timetables_missing_credentials(app: Flask) -> None:
    """Test sync_train_timetables records skipped status when S3 bucket is empty."""
    with app.app_context():
        from app.sync import sync_train_timetables

        Setting.set_val("train_s3_bucket", "")
        res = sync_train_timetables(app=app)
        assert res["status"] == "skipped_no_credentials"
        assert res["records"] == 0
        assert "not configured" in res["message"]

        meta = SyncMetadata.get_meta("train_timetables")
        assert meta is not None
        assert meta.status == "skipped"


def test_sync_train_timetables_success_and_preservation(app: Flask) -> None:
    """Test sync_train_timetables reconciles auto_added timetables
    while preserving custom records."""
    with app.app_context():
        from app.sync import sync_train_timetables
        from app.models import Timetable, Stop

        Setting.set_val("train_s3_bucket", "my-rail-bucket")

        # Create a rail stop
        Stop.create(
            atco_code="9100STEVNG",
            naptan_code="SVG",
            name="Stevenage",
            stop_type="rail",
            latitude=51.9018,
            longitude=-0.2065,
        )

        # Create an existing custom timetable
        custom_tt = Timetable.create(
            name="My Custom Bus",
            transport_type="bus",
            auto_added=False,
        )
        custom_tt.set_content({"stops": [], "trips": []})
        custom_tt.save()

        # Create an old auto timetable to be replaced
        old_auto_tt = Timetable.create(
            name="Old Auto Rail",
            transport_type="rail",
            auto_added=True,
        )
        old_auto_tt.set_content({"stops": [], "trips": []})
        old_auto_tt.save()

        mock_parsed = [
            {
                "name": "Stevenage to Cambridge",
                "transport_type": "rail",
                "auto_added": True,
                "monday": True,
                "tuesday": True,
                "wednesday": True,
                "thursday": True,
                "friday": True,
                "saturday": True,
                "sunday": True,
                "bank_holiday": True,
                "content": {
                    "stops": [
                        {
                            "id": "SVG",
                            "name": "Stevenage",
                            "type": "rail",
                            "indicator": "Station",
                            "icon": "train",
                        }
                    ],
                    "trips": [
                        {
                            "id": "trip-1",
                            "headsign": "TL 1T44",
                            "toc": "TL",
                            "operator": "Thameslink",
                            "times": ["07:00"],
                        }
                    ],
                },
            }
        ]

        with patch(
            "app.datasources.train_s3.TrainS3Client.fetch_timetables",
            return_value=mock_parsed,
        ):
            res = sync_train_timetables(app=app)
            assert res["status"] == "success"
            assert res["records"] == 1

            meta = SyncMetadata.get_meta("train_timetables")
            assert meta is not None
            assert meta.status == "success"

            # Check database: custom_tt should remain, old_auto_tt should be replaced
            timetables = list(Timetable.select())
            assert len(timetables) == 2
            custom_recs = [t for t in timetables if not t.auto_added]
            auto_recs = [t for t in timetables if t.auto_added]
            assert len(custom_recs) == 1
            assert custom_recs[0].name == "My Custom Bus"
            assert len(auto_recs) == 1
            assert auto_recs[0].name == "Stevenage to Cambridge"
            assert auto_recs[0].get_content()["trips"][0]["toc"] == "TL"


def test_sync_train_timetables_errors(app: Flask) -> None:
    """Test sync_train_timetables error paths."""
    with app.app_context():
        from app.sync import sync_train_timetables
        from app.datasources.exceptions import (
            DataSourceAuthError,
            DataSourceConnectionError,
            DataSourceError,
        )

        Setting.set_val("train_s3_bucket", "my-rail-bucket")

        # 1. Auth error
        with patch(
            "app.datasources.train_s3.TrainS3Client.fetch_timetables",
            side_effect=DataSourceAuthError("Access denied"),
        ):
            res = sync_train_timetables(app=app)
            assert res["status"] == "error"
            assert "Access denied" in res["message"]

        # 2. Connection error
        with patch(
            "app.datasources.train_s3.TrainS3Client.fetch_timetables",
            side_effect=DataSourceConnectionError("Timeout"),
        ):
            res = sync_train_timetables(app=app)
            assert res["status"] == "error"
            assert "Network or API error" in res["message"]

        # 3. DataSourceError
        with patch(
            "app.datasources.train_s3.TrainS3Client.fetch_timetables",
            side_effect=DataSourceError("Snapshot corrupt"),
        ):
            res = sync_train_timetables(app=app)
            assert res["status"] == "error"
            assert "Snapshot corrupt" in res["message"]

        # 4. Generic Exception
        with patch(
            "app.datasources.train_s3.TrainS3Client.fetch_timetables",
            side_effect=RuntimeError("Fatal error"),
        ):
            res = sync_train_timetables(app=app)
            assert res["status"] == "error"
            assert "Unexpected error" in res["message"]


def test_sync_bus_timetables_missing_credentials(app: Flask) -> None:
    """Test sync_bus_timetables records skipped status when API key is missing."""
    with app.app_context():
        from app.sync import sync_bus_timetables

        res = sync_bus_timetables(app=app)
        assert res["status"] == "skipped_no_credentials"
        assert res["records"] == 0
        assert "not configured" in res["message"]

        meta = SyncMetadata.get_meta("bus_timetables")
        assert meta is not None
        assert meta.status == "skipped"


def test_sync_bus_timetables_no_stops(app: Flask) -> None:
    """Test sync_bus_timetables returns success 0 records when no bus stops are found."""
    with app.app_context():
        from app.sync import sync_bus_timetables

        Setting.set_val("bus_api_key", "valid-bods-key")
        res = sync_bus_timetables(app=app)
        assert res["status"] == "success"
        assert res["records"] == 0
        assert "No bus stops found" in res["message"]

        meta = SyncMetadata.get_meta("bus_timetables")
        assert meta is not None
        assert meta.status == "success"
        assert meta.records_count == 0


def test_sync_bus_timetables_success_and_preservation(app: Flask) -> None:
    """Test sync_bus_timetables reconciles auto_added bus timetables and preserves others."""
    with app.app_context():
        import datetime
        from app.models import Journey, Timetable, Walking
        from app.sync import sync_bus_timetables

        Setting.set_val("bus_api_key", "valid-bods-key")

        # Create stops in Stop table (including non-target stops from other regions)
        Stop.bulk_upsert(
            [
                {
                    "atco_code": "049000001",
                    "naptan_code": "hrtaaaa",
                    "name": "Stevenage Bus Station",
                    "stop_type": "bus",
                    "latitude": 51.901,
                    "longitude": -0.201,
                },
                {
                    "atco_code": "049000002",
                    "naptan_code": "hrtbbbb",
                    "name": "Hitchin High Street",
                    "stop_type": "bus",
                    "latitude": 51.950,
                    "longitude": -0.278,
                },
                {
                    "atco_code": "670000001",
                    "naptan_code": "leeds01",
                    "name": "Leeds Bus Station",
                    "stop_type": "bus",
                    "latitude": 53.797,
                    "longitude": -1.536,
                },
            ]
        )

        # Create a Walking record referencing bus stop via naptan SMS code prefix
        Walking.create(
            start_type="custom",
            start_id="custom:1",
            start_name="Home",
            finish_type="bus",
            finish_id="naptan:hrtaaaa",
            finish_name="Stevenage Bus Station",
            time_needed_minutes=5,
        )

        # Create a Journey record referencing bus stop via atco prefix
        Journey.create(
            name="Daily Commute",
            from_type="bus",
            from_id="atco:049000002",
            from_name="Hitchin High Street",
            to_type="custom",
            to_id="custom:2",
            to_name="Work",
        )

        # Pre-populate custom timetable, existing auto train timetable, and old auto bus timetable
        Timetable.create(
            name="My Custom Timetable",
            transport_type="bus",
            auto_added=False,
            content={"stops": [], "trips": []},
        )
        Timetable.create(
            name="Stevenage to London King's Cross",
            transport_type="rail",
            auto_added=True,
            content={"stops": [], "trips": []},
        )
        Timetable.create(
            name="Old Bus 99",
            transport_type="bus",
            auto_added=True,
            content={"stops": [], "trips": []},
        )

        mock_bods_timetables = [
            {
                "name": "Bus 10: Stevenage to Hitchin",
                "transport_type": "bus",
                "start_date": datetime.date(2026, 1, 1),
                "end_date": datetime.date(2026, 12, 31),
                "monday": True,
                "tuesday": True,
                "wednesday": True,
                "thursday": True,
                "friday": True,
                "saturday": False,
                "sunday": False,
                "bank_holiday": False,
                "auto_added": True,
                "content": {
                    "stops": [
                        {
                            "id": "049000001",
                            "name": "Stevenage Bus Station",
                            "type": "bus",
                        },
                        {
                            "id": "049000002",
                            "name": "Hitchin High Street",
                            "type": "bus",
                        },
                    ],
                    "trips": [
                        {
                            "id": "vj_1",
                            "headsign": "10 to Hitchin",
                            "operator": "Arriva",
                            "times": ["08:30", "08:45"],
                        },
                    ],
                },
            }
        ]

        with patch(
            "app.datasources.bods.BodsClient.fetch_timetables",
            autospec=True,
            return_value=mock_bods_timetables,
        ) as mock_fetch:
            res = sync_bus_timetables(app=app)
            assert res["status"] == "success"
            assert res["records"] == 1
            assert "1 bus route timetable" in res["message"]

            assert mock_fetch.called
            call_kwargs = mock_fetch.call_args[1]
            assert (
                "049000001" in call_kwargs["target_stop_codes"]
                or "049000002" in call_kwargs["target_stop_codes"]
            )
            # Ensure non-target admin areas (like 670) are not passed
            assert call_kwargs["admin_areas"] == ["049"]

        meta = SyncMetadata.get_meta("bus_timetables")
        assert meta is not None
        assert meta.status == "success"
        assert meta.records_count == 1

        # Check database: custom_tt and train_tt should remain; old_auto_bus replaced
        all_tt = list(Timetable.select())
        assert len(all_tt) == 3
        names = {t.name for t in all_tt}
        assert "My Custom Timetable" in names
        assert "Stevenage to London King's Cross" in names
        assert "Bus 10: Stevenage to Hitchin" in names
        assert "Old Bus 99" not in names


def test_sync_bus_timetables_errors(app: Flask) -> None:
    """Test sync_bus_timetables error paths."""
    with app.app_context():
        from app.models import Walking
        from app.sync import sync_bus_timetables
        from app.datasources.exceptions import (
            DataSourceAuthError,
            DataSourceConnectionError,
            DataSourceError,
        )

        Setting.set_val("bus_api_key", "my-bus-key")
        Walking.create(
            start_type="bus",
            start_id="049000001",
            start_name="Bus Stop A",
            finish_type="custom",
            finish_id="custom:1",
            finish_name="Home",
            time_needed_minutes=5,
        )

        # 1. Auth error
        with patch(
            "app.datasources.bods.BodsClient.fetch_timetables",
            side_effect=DataSourceAuthError("Access denied"),
        ):
            res = sync_bus_timetables(app=app)
            assert res["status"] == "error"
            assert "Access denied" in res["message"]

        # 2. Connection error
        with patch(
            "app.datasources.bods.BodsClient.fetch_timetables",
            side_effect=DataSourceConnectionError("Timeout"),
        ):
            res = sync_bus_timetables(app=app)
            assert res["status"] == "error"
            assert "Network or API error" in res["message"]

        # 3. DataSourceError
        with patch(
            "app.datasources.bods.BodsClient.fetch_timetables",
            side_effect=DataSourceError("TransXChange corrupt"),
        ):
            res = sync_bus_timetables(app=app)
            assert res["status"] == "error"
            assert "TransXChange corrupt" in res["message"]

        # 4. Generic Exception
        with patch(
            "app.datasources.bods.BodsClient.fetch_timetables",
            side_effect=RuntimeError("Fatal error"),
        ):
            res = sync_bus_timetables(app=app)
            assert res["status"] == "error"
            assert "Unexpected error" in res["message"]


def test_sync_table_bus_timetables(app: Flask) -> None:
    """Test sync_table router with bus_timetables."""
    with app.app_context():
        with patch(
            "app.sync.transit_sync.sync_bus_timetables",
            return_value={"status": "success", "records": 3},
        ) as mock_sync:
            res = sync_table("bus_timetables", app=app)
            assert res["status"] == "success"
            assert res["records"] == 3
            mock_sync.assert_called_once()


# ---------------------------------------------------------------------------
# SyncMetadata flag tests
# ---------------------------------------------------------------------------


def test_sync_metadata_request_sync_sets_flag(app: Flask) -> None:
    """Test SyncMetadata.request_sync sets flag and pending status."""
    with app.app_context():
        meta = SyncMetadata.request_sync("bus_routes")
        assert meta.sync_requested is True
        assert meta.status == "pending"

        # Idempotent — calling again keeps flag set
        meta2 = SyncMetadata.request_sync("bus_routes")
        assert meta2.sync_requested is True


def test_sync_metadata_clear_sync_requested(app: Flask) -> None:
    """Test SyncMetadata.clear_sync_requested atomically clears the flag."""
    with app.app_context():
        SyncMetadata.request_sync("stops")
        meta = SyncMetadata.get_meta("stops")
        assert meta is not None and meta.sync_requested is True

        SyncMetadata.clear_sync_requested("stops")
        meta = SyncMetadata.get_meta("stops")
        assert meta is not None and meta.sync_requested is False


def test_sync_metadata_request_sync_does_not_overwrite_syncing(app: Flask) -> None:
    """Test request_sync does not downgrade a 'syncing' status to 'pending'."""
    with app.app_context():
        SyncMetadata.record_start("walking")
        SyncMetadata.request_sync("walking")
        meta = SyncMetadata.get_meta("walking")
        assert meta is not None
        assert meta.status == "syncing"
        assert meta.sync_requested is True


# ---------------------------------------------------------------------------
# SyncWorker lifecycle tests
# ---------------------------------------------------------------------------


def test_sync_worker_lifecycle(app: Flask) -> None:
    """Test SyncWorker start, idle loop, and stop."""
    with patch("app.sync.worker.SyncMetadata") as mock_meta:
        mock_meta.get_meta.return_value = None
        mock_meta.is_due_for_update.return_value = False

        worker = SyncWorker(app=app, initial_delay_seconds=0.0)
        assert worker.is_running() is False

        worker.start()
        assert worker.is_running() is True

        # Idempotent start
        worker.start()
        assert worker.is_running() is True

        worker.stop(timeout=2.0)
        assert worker.is_running() is False


def test_sync_worker_runs_sync_when_flag_set(app: Flask) -> None:
    """Test that the worker executes a sync function when sync_requested flag is set."""
    from app.sync.worker import SYNC_REGISTRY

    def _fake_meta_get(table_name):
        m = MagicMock()
        m.sync_requested = table_name == "bus_routes"
        return m

    def _fake_is_due(table_name, max_age_seconds):
        return False

    def _fake_clear(table_name):
        pass

    first_entry = SYNC_REGISTRY[0]
    assert first_entry.table_name == "bus_routes"

    with patch("app.sync.worker.SyncMetadata") as mock_meta:
        mock_meta.get_meta.side_effect = _fake_meta_get
        mock_meta.is_due_for_update.side_effect = _fake_is_due
        mock_meta.clear_sync_requested.side_effect = _fake_clear

        result_value = {"status": "success", "records": 1}

        with patch.object(first_entry, "sync_fn", return_value=result_value) as mock_fn:
            worker = SyncWorker(app=app, initial_delay_seconds=0.0)
            worker.start()
            import time

            time.sleep(0.2)
            worker.stop(timeout=2.0)
            assert mock_fn.called


def test_sync_worker_runs_sync_when_overdue(app: Flask) -> None:
    """Test that the worker executes a sync function when data is overdue."""
    from app.sync.worker import SYNC_REGISTRY

    first_entry = SYNC_REGISTRY[0]

    with patch("app.sync.worker.SyncMetadata") as mock_meta:
        mock_meta.get_meta.return_value = None
        mock_meta.is_due_for_update.side_effect = (
            lambda table_name, max_age_seconds: table_name == "bus_routes"
        )
        mock_meta.clear_sync_requested.return_value = None

        with patch.object(
            first_entry, "sync_fn", return_value={"status": "success", "records": 0}
        ) as mock_fn:
            worker = SyncWorker(app=app, initial_delay_seconds=0.0)
            worker.start()
            import time

            time.sleep(0.2)
            worker.stop(timeout=2.0)
            assert mock_fn.called


def test_sync_worker_sleeps_when_idle(app: Flask) -> None:
    """Test the worker enters idle sleep when no syncs are due."""
    with patch("app.sync.worker.SyncMetadata") as mock_meta:
        mock_meta.get_meta.return_value = None
        mock_meta.is_due_for_update.return_value = False

        worker = SyncWorker(app=app, initial_delay_seconds=0.0)
        worker.start()

        import time

        time.sleep(0.1)

        # The wake event should be cleared (worker is sleeping)
        assert not worker._wake_event.is_set()

        worker.stop(timeout=2.0)
        assert worker.is_running() is False


def test_sync_worker_handles_exception_in_loop(app: Flask) -> None:
    """Test the worker continues after a sync function raises an exception."""
    from app.sync.worker import SYNC_REGISTRY

    first_entry = SYNC_REGISTRY[0]

    with patch("app.sync.worker.SyncMetadata") as mock_meta:
        mock_meta.get_meta.return_value = None
        mock_meta.is_due_for_update.side_effect = (
            lambda table_name, max_age_seconds: table_name == "bus_routes"
        )
        mock_meta.clear_sync_requested.return_value = None

        with patch.object(first_entry, "sync_fn", side_effect=RuntimeError("boom")):
            worker = SyncWorker(app=app, initial_delay_seconds=0.0)
            worker.start()
            import time

            time.sleep(0.15)
            worker.stop(timeout=2.0)
            assert worker.is_running() is False


# ---------------------------------------------------------------------------
# Module-level worker helpers
# ---------------------------------------------------------------------------


def test_global_background_worker_helpers(app: Flask) -> None:
    """Test start_background_worker, stop_background_worker, get_background_worker."""
    stop_background_worker()

    # TESTING=True should suppress worker start
    w = start_background_worker(app)
    assert w is None

    # Non-testing config should start the worker
    non_test_app = Flask(__name__)
    non_test_app.config["TESTING"] = False

    with patch("app.sync.worker.SyncMetadata") as mock_meta:
        mock_meta.get_meta.return_value = None
        mock_meta.is_due_for_update.return_value = False

        worker = start_background_worker(non_test_app, initial_delay_seconds=0.0)
        assert worker is not None
        assert get_background_worker() is worker

        # Calling start again returns existing instance
        w2 = start_background_worker(non_test_app)
        assert w2 is worker

        stop_background_worker()
        assert get_background_worker() is None


def test_request_sync_sets_flag_and_wakes_worker(app: Flask) -> None:
    """Test request_sync sets the DB flag and signals a running worker."""
    with app.app_context():
        with patch("app.sync.worker.SyncMetadata") as mock_meta:
            mock_meta.get_meta.return_value = None
            mock_meta.is_due_for_update.return_value = False
            mock_meta.request_sync.return_value = MagicMock()

            worker = SyncWorker(app=app, initial_delay_seconds=0.0)
            worker.start()

            import time

            time.sleep(0.1)

            request_sync("ha_locations")
            mock_meta.request_sync.assert_called_with("ha_locations")

            worker.stop(timeout=2.0)


def test_sync_registry_ordering() -> None:
    """Test SYNC_REGISTRY defines expected dependency order: walking before bus_timetables."""
    from app.sync.worker import SYNC_REGISTRY

    table_order = [entry.table_name for entry in SYNC_REGISTRY]
    assert table_order == [
        "bus_routes",
        "stops",
        "rail_references",
        "stop_interchanges",
        "ha_locations",
        "train_timetables",
        "walking",
        "bus_timetables",
    ]
    walking_idx = table_order.index("walking")
    bus_tt_idx = table_order.index("bus_timetables")
    assert walking_idx < bus_tt_idx


def test_sync_metadata_record_error_logs_to_system_log(caplog: Any) -> None:
    """Test SyncMetadata.record_error outputs error to system log."""
    import logging

    with caplog.at_level(logging.ERROR):
        SyncMetadata.record_error(
            "bus_timetables", "Test simulated BODS connection timeout", 1.23
        )
        assert any(
            "Synchronisation error for 'bus_timetables'" in record.message
            and "Test simulated BODS connection timeout" in record.message
            for record in caplog.records
        )


def test_sync_metadata_record_skipped_logs_to_system_log(caplog: Any) -> None:
    """Test SyncMetadata.record_skipped outputs warning to system log."""
    import logging

    with caplog.at_level(logging.WARNING):
        SyncMetadata.record_skipped("bus_routes", "Missing API key")
        assert any(
            "Synchronisation skipped for 'bus_routes'" in record.message
            and "Missing API key" in record.message
            for record in caplog.records
        )


def test_sync_bus_timetables_logs_error(app: Flask, caplog: Any) -> None:
    """Test sync_bus_timetables logs error to system log when fetch fails."""
    import logging
    from app.sync.transit_sync import sync_bus_timetables

    with app.app_context():
        Setting.set_val("bus_api_key", "test-key")

        with patch("app.models.Walking.select") as mock_walk_select:
            mock_walk = MagicMock()
            mock_walk.start_type = "bus"
            mock_walk.start_id = "atco:490000077E"
            mock_walk.finish_type = "custom"
            mock_walk.finish_id = "custom:123"
            mock_walk_select.return_value = [mock_walk]

            with patch("app.datasources.BodsClient.fetch_timetables") as mock_fetch:
                mock_fetch.side_effect = RuntimeError("BODS service unavailable")
                with caplog.at_level(logging.ERROR):
                    res = sync_bus_timetables(app=app)
                    assert res["status"] == "error"
                    assert any(
                        "Synchronisation error for 'bus_timetables'" in record.message
                        and "BODS service unavailable" in record.message
                        for record in caplog.records
                    )


def test_sync_bus_timetables_logs_skipped(app: Flask, caplog: Any) -> None:
    """Test sync_bus_timetables logs warning to system log when unconfigured."""
    import logging
    from app.sync.transit_sync import sync_bus_timetables

    with app.app_context():
        Setting.set_val("bus_api_key", "")
        with caplog.at_level(logging.WARNING):
            res = sync_bus_timetables(app=app)
            assert res["status"] == "skipped_no_credentials"
            assert any(
                "Synchronisation skipped for 'bus_timetables'" in record.message
                and "Bus API Key not configured" in record.message
                for record in caplog.records
            )


def test_sync_table_unknown_logs_error(app: Flask, caplog: Any) -> None:
    """Test sync_table logs error to system log for unknown tables."""
    import logging

    with app.app_context():
        with caplog.at_level(logging.ERROR):
            res = sync_table("invalid_table_name", app=app)
            assert res["status"] == "error"
            assert any(
                "Unknown or non-syncable table: 'invalid_table_name'" in record.message
                for record in caplog.records
            )


def test_sync_worker_logs_failed_and_skipped_syncs(app: Flask, caplog: Any) -> None:
    """Test SyncWorker logs error when sync_fn returns error status and warning when skipped."""
    import logging
    import time
    from app.sync.worker import SYNC_REGISTRY

    first_entry = SYNC_REGISTRY[0]

    with app.app_context():
        with patch("app.sync.worker.SyncMetadata") as mock_meta:
            mock_meta.get_meta.return_value = None
            mock_meta.is_due_for_update.side_effect = (
                lambda table_name, max_age_seconds: table_name == "bus_routes"
            )
            mock_meta.clear_sync_requested.return_value = None

            # Test error status logging
            with patch.object(
                first_entry,
                "sync_fn",
                return_value={
                    "status": "error",
                    "message": "BODS connection timeout",
                    "records": 0,
                },
            ):
                with caplog.at_level(logging.ERROR):
                    worker = SyncWorker(app=app, initial_delay_seconds=0.0)
                    worker.start()
                    time.sleep(0.15)
                    worker.stop(timeout=2.0)
                    assert any(
                        "Sync failed for 'bus_routes': BODS connection timeout"
                        in record.message
                        for record in caplog.records
                    )

            # Test skipped status logging
            with patch.object(
                first_entry,
                "sync_fn",
                return_value={
                    "status": "skipped_no_credentials",
                    "message": "Missing API key",
                    "records": 0,
                },
            ):
                with caplog.at_level(logging.WARNING):
                    worker = SyncWorker(app=app, initial_delay_seconds=0.0)
                    worker.start()
                    time.sleep(0.15)
                    worker.stop(timeout=2.0)
                    assert any(
                        "Sync skipped for 'bus_routes': Missing API key"
                        in record.message
                        for record in caplog.records
                    )


# ---------------------------------------------------------------------------
# sync_rail_references tests
# ---------------------------------------------------------------------------


@patch("app.datasources.naptan.requests.get")
def test_sync_rail_references_success(mock_get: MagicMock, app: Flask) -> None:
    """Test sync_rail_references inserts records and records success metadata."""
    csv_data = (
        "TiplocCode,AtcoCode,CrsCode\n" "PADTON,9100PADTON,PAD\n" "OXFD,9100OXFD,OXF\n"
    )
    mock_get.return_value = MagicMock(status_code=200, text=csv_data)

    with app.app_context():
        res = sync_rail_references(app=app)

    assert res["status"] == "success"
    assert res["records"] == 2
    assert "2 rail reference" in res["message"]

    with app.app_context():
        meta = SyncMetadata.get_meta("rail_references")
        assert meta is not None
        assert meta.status == "success"
        assert meta.records_count == 2

        assert RailReference.select().count() == 2
        ref = RailReference.get_by_tiploc("PADTON")
        assert ref is not None
        assert ref.atco_code == "9100PADTON"
        assert ref.crs_code == "PAD"


@patch("app.datasources.naptan.requests.get")
def test_sync_rail_references_full_replace(mock_get: MagicMock, app: Flask) -> None:
    """Test sync_rail_references performs a full replace: previous rows are removed."""
    csv_data_first = (
        "TiplocCode,AtcoCode,CrsCode\n"
        "PADTON,9100PADTON,PAD\n"
        "OXFD,9100OXFD,OXF\n"
        "DIDCOT,9100DID,DID\n"
    )
    csv_data_second = "TiplocCode,AtcoCode,CrsCode\n" "PADTON,9100PADTON,PAD\n"

    with app.app_context():
        mock_get.return_value = MagicMock(status_code=200, text=csv_data_first)
        sync_rail_references(app=app)
        assert RailReference.select().count() == 3

        mock_get.return_value = MagicMock(status_code=200, text=csv_data_second)
        res = sync_rail_references(app=app)
        assert res["records"] == 1
        assert RailReference.select().count() == 1
        assert RailReference.get_by_tiploc("OXFD") is None
        assert RailReference.get_by_tiploc("PADTON") is not None


@patch("app.datasources.naptan.requests.get")
def test_sync_rail_references_connection_error(mock_get: MagicMock, app: Flask) -> None:
    """Test sync_rail_references records error metadata on connection failure."""
    import requests as req

    mock_get.side_effect = req.exceptions.ConnectionError("refused")

    with app.app_context():
        res = sync_rail_references(app=app)

    assert res["status"] == "error"
    assert res["records"] == 0

    with app.app_context():
        meta = SyncMetadata.get_meta("rail_references")
        assert meta is not None
        assert meta.status == "error"


def test_sync_table_dispatches_rail_references(app: Flask) -> None:
    """Test sync_table routes 'rail_references' to sync_rail_references."""
    with app.app_context():
        with patch(
            "app.sync.transit_sync.sync_rail_references",
            return_value={
                "table": "rail_references",
                "status": "success",
                "records": 0,
                "message": "ok",
                "duration_seconds": 0.0,
            },
        ) as mock_sync:
            res = sync_table("rail_references")
            mock_sync.assert_called_once()
            assert res["status"] == "success"
