"""Unit tests for transit dataset synchronisation and background sync worker."""

from typing import Any
from unittest.mock import MagicMock, patch
import requests
from flask import Flask

from app.models import (
    Stop,
    SyncMetadata,
)
from app.sync import (
    SyncWorker,
    get_background_worker,
    request_sync,
    start_background_worker,
    stop_background_worker,
    sync_stops,
    sync_table,
)


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

        res_bus = sync_table("bus_routes")
        assert res_bus["status"] == "error"
        assert "Unknown or non-syncable table" in res_bus["message"]

        with patch(
            "app.sync.transit_sync.sync_stops",
            return_value={"status": "success", "records": 3},
        ):
            res = sync_table("stops")
            assert res["status"] == "success"

        with patch(
            "app.sync.walking_sync.sync_walking_routes",
            return_value={"status": "success", "records": 5},
        ):
            res = sync_table("walking")
            assert res["status"] == "success"

        res_train = sync_table("train_timetables")
        assert res_train["status"] == "error"
        assert "Unknown or non-syncable table" in res_train["message"]


# ---------------------------------------------------------------------------
# SyncMetadata flag tests
# ---------------------------------------------------------------------------


def test_sync_metadata_request_sync_sets_flag(app: Flask) -> None:
    """Test SyncMetadata.request_sync sets flag and pending status."""
    with app.app_context():
        meta = SyncMetadata.request_sync("stops")
        assert meta.sync_requested is True
        assert meta.status == "pending"

        # Idempotent — calling again keeps flag set
        meta2 = SyncMetadata.request_sync("stops")
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
        m.sync_requested = table_name == "stops"
        return m

    def _fake_is_due(table_name, max_age_seconds):
        return False

    def _fake_clear(table_name):
        pass

    first_entry = SYNC_REGISTRY[0]
    assert first_entry.table_name == "stops"

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
            lambda table_name, max_age_seconds: table_name == "stops"
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
            lambda table_name, max_age_seconds: table_name == "stops"
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
    """Test SYNC_REGISTRY defines expected dependency order."""
    from app.sync.worker import SYNC_REGISTRY

    table_order = [entry.table_name for entry in SYNC_REGISTRY]
    assert table_order == ["stops", "ha_locations", "walking"]


def test_sync_metadata_record_error_logs_to_system_log(app: Flask, caplog: Any) -> None:
    """Test SyncMetadata.record_error outputs error to system log."""
    import logging

    with app.app_context(), caplog.at_level(logging.ERROR):
        SyncMetadata.record_error(
            "bus_timetables", "Test simulated BODS connection timeout", 1.23
        )
        assert any(
            "Synchronisation error for 'bus_timetables'" in record.message
            and "Test simulated BODS connection timeout" in record.message
            for record in caplog.records
        )


def test_sync_metadata_record_skipped_logs_to_system_log(
    app: Flask, caplog: Any
) -> None:
    """Test SyncMetadata.record_skipped outputs warning to system log."""
    import logging

    with app.app_context(), caplog.at_level(logging.WARNING):
        SyncMetadata.record_skipped("stops", "Missing API key")
        assert any(
            "Synchronisation skipped for 'stops'" in record.message
            and "Missing API key" in record.message
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
                lambda table_name, max_age_seconds: table_name == "stops"
            )
            mock_meta.clear_sync_requested.return_value = None

            # Test error status logging
            with patch.object(
                first_entry,
                "sync_fn",
                return_value={
                    "status": "error",
                    "message": "NaPTAN connection timeout",
                    "records": 0,
                },
            ):
                with caplog.at_level(logging.ERROR):
                    worker = SyncWorker(app=app, initial_delay_seconds=0.0)
                    worker.start()
                    time.sleep(0.15)
                    worker.stop(timeout=2.0)
                    assert any(
                        "Sync failed for 'stops': NaPTAN connection timeout"
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
                        "Sync skipped for 'stops': Missing API key" in record.message
                        for record in caplog.records
                    )


def test_sync_worker_runs_database_maintenance_when_flag_set(app: Flask) -> None:
    """Test that SyncWorker executes database vacuum when sync_requested flag is set."""
    with app.app_context():
        SyncMetadata.delete().where(
            SyncMetadata.table_name == "database_vacuum"
        ).execute()
        SyncMetadata.request_sync("database_vacuum")

        with patch("app.sync.worker.vacuum_database") as mock_vac:
            mock_vac.return_value = {
                "status": "success",
                "pages_reclaimed": 50,
                "bytes_reclaimed": 204800,
                "duration_seconds": 0.12,
            }
            worker = SyncWorker(app=app, initial_delay_seconds=0.0)
            did_work = worker._evaluate_database_maintenance()
            assert did_work is True
            mock_vac.assert_called_once_with(force=True, app=app)
            meta = SyncMetadata.get_meta("database_vacuum")
            assert meta is not None
            assert meta.sync_requested is False


def test_sync_worker_runs_database_maintenance_when_overdue(app: Flask) -> None:
    """Test that SyncWorker executes database vacuum when weekly freshness expires."""
    with app.app_context():
        SyncMetadata.delete().where(
            SyncMetadata.table_name == "database_vacuum"
        ).execute()

        with patch("app.sync.worker.vacuum_database") as mock_vac:
            mock_vac.return_value = {
                "status": "success",
                "pages_reclaimed": 20,
                "bytes_reclaimed": 81920,
                "duration_seconds": 0.05,
            }
            worker = SyncWorker(app=app, initial_delay_seconds=0.0)
            did_work = worker._evaluate_database_maintenance()
            assert did_work is True
            mock_vac.assert_called_once_with(force=False, app=app)


def test_sync_worker_database_maintenance_skipped_below_threshold(app: Flask) -> None:
    """Test that SyncWorker handles skipped_below_threshold status gracefully."""
    with app.app_context():
        SyncMetadata.delete().where(
            SyncMetadata.table_name == "database_vacuum"
        ).execute()

        with patch("app.sync.worker.vacuum_database") as mock_vac:
            mock_vac.return_value = {
                "status": "skipped_below_threshold",
                "freelist_count_before": 10,
                "pages_reclaimed": 0,
                "bytes_reclaimed": 0,
                "duration_seconds": 0.01,
                "message": "Below threshold",
            }
            worker = SyncWorker(app=app, initial_delay_seconds=0.0)
            did_work = worker._evaluate_database_maintenance()
            assert did_work is True


def test_sync_worker_database_maintenance_error(app: Flask) -> None:
    """Test that SyncWorker handles vacuum error status gracefully."""
    with app.app_context():
        SyncMetadata.delete().where(
            SyncMetadata.table_name == "database_vacuum"
        ).execute()

        with patch("app.sync.worker.vacuum_database") as mock_vac:
            mock_vac.return_value = {
                "status": "error",
                "message": "Disk I/O error",
                "duration_seconds": 0.02,
            }
            worker = SyncWorker(app=app, initial_delay_seconds=0.0)
            did_work = worker._evaluate_database_maintenance()
            assert did_work is True


def test_request_sync_database_vacuum(app: Flask) -> None:
    """Test request_sync queues database_vacuum maintenance."""
    with app.app_context():
        SyncMetadata.delete().where(
            SyncMetadata.table_name == "database_vacuum"
        ).execute()
        request_sync("database_vacuum")
        meta = SyncMetadata.get_meta("database_vacuum")
        assert meta is not None
        assert meta.sync_requested is True
