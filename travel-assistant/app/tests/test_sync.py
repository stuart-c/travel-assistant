"""Unit tests for transit dataset synchronisation and background worker daemon."""

from unittest.mock import MagicMock, patch
import requests
from flask import Flask

from app.models import (
    BusRoute,
    Setting,
    Stop,
    SyncMetadata,
)
from app.sync import (
    TransitBackgroundWorker,
    check_and_run_background_sync,
    get_background_worker,
    start_background_worker,
    stop_background_worker,
    sync_all,
    sync_bus_routes,
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
            res2 = sync_table("timetables")
            assert res2["status"] == "success"


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

            # Check database: custom_tt should remain, old_auto_tt should be replaced by new one
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


def test_sync_all(app: Flask) -> None:
    """Test sync_all runs all registered transit synchronisations."""
    with app.app_context():
        with patch("app.sync.transit_sync.sync_table") as mock_sync:
            mock_sync.return_value = {"status": "success", "records": 2}
            res = sync_all(app=app)
            assert res["success"] is True
            assert res["total_records"] == 8
            assert len(res["tables"]) == 4


def test_check_and_run_background_sync(app: Flask) -> None:
    """Test check_and_run_background_sync only triggers overdue tables."""
    with app.app_context():
        # bus_routes, ha_locations, and train_timetables are up to date
        SyncMetadata.record_success("bus_routes", 10, 1.0)
        SyncMetadata.record_success("ha_locations", 5, 0.5)
        SyncMetadata.record_success("train_timetables", 2, 0.8)
        # stops is not synced

        with patch("app.sync.transit_sync.sync_table") as mock_sync:
            mock_sync.return_value = {"status": "success", "records": 1}
            res = check_and_run_background_sync(app=app, max_age_seconds=86400)
            assert res["triggered_count"] == 1
            assert "stops" in res["results"]
            assert "bus_routes" not in res["results"]
            assert "ha_locations" not in res["results"]
            assert "train_timetables" not in res["results"]


def test_background_worker_lifecycle(app: Flask) -> None:
    """Test TransitBackgroundWorker start, loop execution, and stop."""
    with patch(
        "app.sync.worker.check_and_run_background_sync",
        return_value={"triggered_count": 0},
    ):
        worker = TransitBackgroundWorker(
            app=app,
            check_interval_seconds=1,
            initial_delay_seconds=0.0,
            max_age_seconds=86400,
        )
        assert worker.is_running() is False
        worker.start()
        assert worker.is_running() is True
        # Idempotent start
        worker.start()

        worker.stop()
        assert worker.is_running() is False


def test_global_background_worker_helpers(app: Flask) -> None:
    """Test start_background_worker, stop_background_worker, get_background_worker."""
    stop_background_worker()

    # Test with TESTING=True should not start by default
    w = start_background_worker(app)
    assert w is None

    # Test with non-testing config
    non_test_app = Flask(__name__)
    non_test_app.config["TESTING"] = False
    with patch(
        "app.sync.worker.check_and_run_background_sync",
        return_value={"triggered_count": 0},
    ):
        worker = start_background_worker(
            non_test_app,
            check_interval_seconds=1,
            initial_delay_seconds=0.0,
        )
        assert worker is not None
        assert get_background_worker() is worker

        # Calling start again returns existing instance
        w2 = start_background_worker(non_test_app)
        assert w2 is worker

        stop_background_worker()
        assert get_background_worker() is None


def test_sync_all_with_table_error(app: Flask) -> None:
    """Test sync_all correctly reports success=False when one table errors."""
    with app.app_context():
        with patch("app.sync.transit_sync.sync_table") as mock_sync:
            mock_sync.side_effect = [
                {"status": "success", "records": 5},
                {"status": "error", "records": 0, "message": "Failed"},
                {"status": "success", "records": 3},
                {"status": "success", "records": 2},
            ]
            res = sync_all(app=app)
            assert res["success"] is False
            assert res["total_records"] == 10


def test_background_worker_handles_exception_in_loop(app: Flask) -> None:
    """Test background worker continues and catches exceptions inside loop."""
    worker = TransitBackgroundWorker(
        app=app,
        check_interval_seconds=1,
        initial_delay_seconds=0.0,
    )
    with patch(
        "app.sync.worker.check_and_run_background_sync",
        side_effect=RuntimeError("Loop error"),
    ):
        worker.start()
        worker.stop()
        assert worker.is_running() is False
