"""Unit tests for transit dataset synchronisation and background worker daemon."""

import json
import time
from unittest.mock import MagicMock, patch
import requests
from botocore.exceptions import ClientError
from flask import Flask


from app.db import (
    BusRouteRepository,
    BusStopRepository,
    SettingsRepository,
    StationRepository,
    SyncMetadataRepository,
)
from app.sync import (
    TransitBackgroundWorker,
    check_and_run_background_sync,
    get_background_worker,
    start_background_worker,
    stop_background_worker,
    sync_all,
    sync_bus_routes,
    sync_bus_stops,
    sync_stations,
    sync_table,
)


def test_sync_bus_routes_missing_credentials(app: Flask) -> None:
    """Test sync_bus_routes records skipped status when API key is missing."""
    with app.app_context():
        res = sync_bus_routes(app=app)
        assert res["status"] == "skipped_no_credentials"
        assert res["records"] == 0
        assert "not configured" in res["message"]

        meta = SyncMetadataRepository().get("bus_routes")
        assert meta["status"] == "skipped_no_credentials"


def test_sync_bus_routes_auth_error(app: Flask) -> None:
    """Test sync_bus_routes handles 401/403 authentication failures."""
    with app.app_context():
        SettingsRepository().set("bus_api_key", "invalid-key")

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        with patch("requests.get", return_value=mock_resp):
            res = sync_bus_routes(app=app)
            assert res["status"] == "error"
            assert "Invalid Bus API key" in res["message"]

        meta = SyncMetadataRepository().get("bus_routes")
        assert meta["status"] == "error"


def test_sync_bus_routes_success_with_lines(app: Flask) -> None:
    """Test sync_bus_routes successfully ingests line records."""
    with app.app_context():
        SettingsRepository().set("bus_api_key", "valid-key")

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
            assert res["records"] == 3

        routes = BusRouteRepository().get_all()
        assert len(routes) == 3
        route_numbers = [r["route_number"] for r in routes]
        assert "OX-TUBE" in route_numbers
        assert "1" in route_numbers
        assert "DS-999" in route_numbers


def test_sync_bus_routes_request_exception(app: Flask) -> None:
    """Test sync_bus_routes handles network/requests exceptions."""
    with app.app_context():
        SettingsRepository().set("bus_api_key", "valid-key")

        with patch(
            "requests.get", side_effect=requests.exceptions.ConnectTimeout("Timeout")
        ):
            res = sync_bus_routes(app=app)
            assert res["status"] == "error"
            assert "Network or API error" in res["message"]


def test_sync_bus_routes_unexpected_exception(app: Flask) -> None:
    """Test sync_bus_routes handles general unexpected exceptions."""
    with app.app_context():
        SettingsRepository().set("bus_api_key", "valid-key")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("Corrupt JSON")
        with patch("requests.get", return_value=mock_resp):
            res = sync_bus_routes(app=app)
            assert res["status"] == "error"
            assert "Unexpected error" in res["message"]


def test_sync_bus_stops_missing_credentials(app: Flask) -> None:
    """Test sync_bus_stops records skipped status when API key is missing."""
    with app.app_context():
        res = sync_bus_stops(app=app)
        assert res["status"] == "skipped_no_credentials"
        assert res["records"] == 0


def test_sync_bus_stops_auth_error(app: Flask) -> None:
    """Test sync_bus_stops handles authentication failures."""
    with app.app_context():
        SettingsRepository().set("bus_api_key", "bad-key")

        mock_resp = MagicMock()
        mock_resp.status_code = 403
        with patch("requests.get", return_value=mock_resp):
            res = sync_bus_stops(app=app)
            assert res["status"] == "error"
            assert "BODS authentication failed" in res["message"]


def test_sync_bus_stops_success(app: Flask) -> None:
    """Test sync_bus_stops successfully parses feed items."""
    with app.app_context():
        SettingsRepository().set("bus_api_key", "good-key")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {
                    "id": 101,
                    "operator_name": "Oxford Bus",
                    "url": "https://data.bus-data.dft.gov.uk/feed/101",
                },
                {
                    "id": 102,
                    "name": "Stagecoach East",
                    "url": "https://data.bus-data.dft.gov.uk/feed/102",
                },
            ]
        }
        with patch("requests.get", return_value=mock_resp):
            res = sync_bus_stops(app=app)
            assert res["status"] == "success"
            assert res["records"] == 2

        stops = BusStopRepository().get_all()
        assert len(stops) == 2
        assert stops[0]["atco_code"] == "BODS-FEED-101"


def test_sync_bus_stops_network_and_unexpected_exceptions(app: Flask) -> None:
    """Test sync_bus_stops exception capturing."""
    with app.app_context():
        SettingsRepository().set("bus_api_key", "good-key")

        with patch(
            "requests.get", side_effect=requests.exceptions.ConnectionError("Failed")
        ):
            res = sync_bus_stops(app=app)
            assert res["status"] == "error"
            assert "Network or API error" in res["message"]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = RuntimeError("Fatal error")
        with patch("requests.get", return_value=mock_resp):
            res = sync_bus_stops(app=app)
            assert res["status"] == "error"
            assert "Unexpected error" in res["message"]


def test_sync_stations_missing_credentials(app: Flask) -> None:
    """Test sync_stations records skipped status when credentials are not configured."""
    with app.app_context():
        res = sync_stations(app=app)
        assert res["status"] == "skipped_no_credentials"
        assert res["records"] == 0


def test_sync_stations_s3_success_with_json(app: Flask) -> None:
    """Test sync_stations parses stations.json from configured S3 bucket."""
    with app.app_context():
        repo = SettingsRepository()
        repo.set("train_s3_bucket", "my-transit-bucket")
        repo.set("train_s3_access_key", "AKIA12345")
        repo.set("train_s3_secret_key", "secret123")
        repo.set("train_s3_region", "eu-west-1")

        mock_s3 = MagicMock()
        mock_body = MagicMock()
        station_json = json.dumps(
            [
                {
                    "crs_code": "OXF",
                    "name": "Oxford",
                    "tiploc_code": "OXFD",
                    "latitude": 51.753,
                    "longitude": -1.27,
                    "operator": "GWR",
                },
                {
                    "crs_code": "DID",
                    "name": "Didcot Parkway",
                    "tiploc_code": "DIDCOT",
                    "latitude": 51.61,
                    "longitude": -1.24,
                    "operator": "GWR",
                },
            ]
        ).encode("utf-8")
        mock_body.read.return_value = station_json
        mock_s3.get_object.return_value = {"Body": mock_body}

        with patch("boto3.client", return_value=mock_s3):
            res = sync_stations(app=app)
            assert res["status"] == "success"
            assert res["records"] == 2

        st_repo = StationRepository()
        assert st_repo.count() == 2
        oxf = st_repo.get_by_crs("OXF")
        assert oxf is not None
        assert oxf["name"] == "Oxford"


def test_sync_stations_s3_nosuchkey_fallback(app: Flask) -> None:
    """Test sync_stations registers bucket gateway hub when stations.json is not present."""
    with app.app_context():
        repo = SettingsRepository()
        repo.set("train_s3_bucket", "test-bucket")

        mock_s3 = MagicMock()
        err_response = {"Error": {"Code": "NoSuchKey", "Message": "Not found"}}
        mock_s3.get_object.side_effect = ClientError(err_response, "GetObject")

        with patch("boto3.client", return_value=mock_s3):
            res = sync_stations(app=app)
            assert res["status"] == "success"
            assert res["records"] == 1

        st = StationRepository().get_by_crs("S3-HUB")
        assert st is not None
        assert "test-bucket" in st["name"]


def test_sync_stations_live_api_key_fallback(app: Flask) -> None:
    """Test sync_stations registers LDBWS live gateway hub when live API key is set."""
    with app.app_context():
        repo = SettingsRepository()
        repo.set("train_live_api_key", "token-xyz")

        res = sync_stations(app=app)
        assert res["status"] == "success"
        assert res["records"] == 1

        st = StationRepository().get_by_crs("LDBWS-HUB")
        assert st is not None


def test_sync_stations_errors(app: Flask) -> None:
    """Test sync_stations handles AWS and unexpected errors."""
    with app.app_context():
        repo = SettingsRepository()
        repo.set("train_s3_bucket", "invalid-bucket")

        mock_s3 = MagicMock()
        err_response = {"Error": {"Code": "AccessDenied", "Message": "Denied"}}
        mock_s3.get_object.side_effect = ClientError(err_response, "GetObject")

        with patch("boto3.client", return_value=mock_s3):
            res = sync_stations(app=app)
            assert res["status"] == "error"
            assert "AWS S3 error" in res["message"]

        mock_s3.get_object.side_effect = Exception("Crash")
        with patch("boto3.client", return_value=mock_s3):
            res = sync_stations(app=app)
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
            "app.sync.transit_sync.sync_bus_stops",
            return_value={"status": "success", "records": 3},
        ):
            res = sync_table("bus_stops")
            assert res["status"] == "success"

        with patch(
            "app.sync.transit_sync.sync_stations",
            return_value={"status": "success", "records": 8},
        ):
            res = sync_table("stations")
            assert res["status"] == "success"


def test_sync_all(app: Flask) -> None:
    """Test sync_all runs all 3 transit synchronisations."""
    with app.app_context():
        with patch("app.sync.transit_sync.sync_table") as mock_sync:
            mock_sync.return_value = {"status": "success", "records": 2}
            res = sync_all(app=app)
            assert res["success"] is True
            assert res["total_records"] == 6
            assert len(res["tables"]) == 3


def test_check_and_run_background_sync(app: Flask) -> None:
    """Test check_and_run_background_sync only triggers overdue tables."""
    with app.app_context():
        sync_repo = SyncMetadataRepository()
        # bus_routes is up to date
        sync_repo.record_sync_success("bus_routes", 10)
        # bus_stops is not synced
        # stations is not synced

        with patch("app.sync.transit_sync.sync_table") as mock_sync:
            mock_sync.return_value = {"status": "success", "records": 1}
            res = check_and_run_background_sync(app=app, max_age_seconds=86400)
            assert res["triggered_count"] == 2
            assert "bus_stops" in res["results"]
            assert "stations" in res["results"]
            assert "bus_routes" not in res["results"]


def test_background_worker_lifecycle(app: Flask) -> None:
    """Test TransitBackgroundWorker start, loop execution, and stop."""
    worker = TransitBackgroundWorker(
        app=app,
        check_interval_seconds=1,
        initial_delay_seconds=0.01,
        max_age_seconds=86400,
    )
    assert worker.is_running() is False
    worker.start()
    assert worker.is_running() is True
    # Idempotent start
    worker.start()

    time.sleep(0.05)
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
    worker = start_background_worker(
        non_test_app,
        check_interval_seconds=1,
        initial_delay_seconds=0.01,
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
            ]
            res = sync_all(app=app)
            assert res["success"] is False
            assert res["total_records"] == 8


def test_background_worker_handles_exception_in_loop(app: Flask) -> None:
    """Test background worker continues and catches exceptions inside loop."""
    worker = TransitBackgroundWorker(
        app=app,
        check_interval_seconds=1,
        initial_delay_seconds=0.01,
    )
    with patch(
        "app.sync.worker.check_and_run_background_sync",
        side_effect=RuntimeError("Loop error"),
    ):
        worker.start()
        time.sleep(0.05)
        worker.stop()
        assert worker.is_running() is False
