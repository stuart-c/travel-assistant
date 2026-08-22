"""Unit tests for application-wide system and background process logging."""

import logging
import pytest
from flask import Flask

from app.db.core import init_db
from app.models.location import Location
from app.sync.common import run_sync_task
from app.sync.worker import SyncWorker, request_sync
from app.views.config.common import apply_model_changeset


def test_sync_worker_logging(app: Flask, caplog: pytest.LogCaptureFixture) -> None:
    """Verify that SyncWorker emits informative INFO level logs on startup and task execution."""
    worker = SyncWorker(app=app, initial_delay_seconds=0.0)

    with caplog.at_level(logging.INFO):
        worker.start()
        assert worker.is_running()
        worker.stop()

    assert any(
        "Background sync worker started" in record.message for record in caplog.records
    )
    assert any(
        "Background sync worker stopped" in record.message for record in caplog.records
    )


def test_request_sync_logging(caplog: pytest.LogCaptureFixture) -> None:
    """Verify that request_sync emits an INFO level log when queueing a table."""
    with caplog.at_level(logging.INFO):
        request_sync("stops")

    assert any(
        "Queued on-demand synchronisation request for 'stops'" in record.message
        for record in caplog.records
    )


def test_run_sync_task_logging(app: Flask, caplog: pytest.LogCaptureFixture) -> None:
    """Verify that run_sync_task emits INFO logs for task start and success."""
    with caplog.at_level(logging.INFO):
        result = run_sync_task(
            table_name="ha_locations",
            sync_operation=lambda: 5,
            app=app,
        )

    assert result["status"] == "success"
    assert any(
        "Starting synchronisation task for 'ha_locations'" in record.message
        for record in caplog.records
    )
    assert any(
        "Synchronisation task for 'ha_locations' completed successfully"
        in record.message
        for record in caplog.records
    )


def test_run_sync_task_skipped_logging(
    app: Flask, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify that run_sync_task emits WARNING logs when credentials are missing."""
    with caplog.at_level(logging.WARNING):
        result = run_sync_task(
            table_name="bus_routes",
            sync_operation=lambda: 10,
            client_check=lambda: "Missing API Key",
            app=app,
        )

    assert result["status"] == "skipped_no_credentials"
    assert any(
        "Synchronisation task for 'bus_routes' skipped: Missing API Key"
        in record.message
        for record in caplog.records
    )


def test_apply_model_changeset_logging(
    app: Flask, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify that apply_model_changeset logs changeset statistics at INFO level."""
    with app.app_context():
        with caplog.at_level(logging.INFO):
            stats = apply_model_changeset(
                model_class=Location,
                changeset={
                    "added": [
                        {
                            "id": "custom:testloc1",
                            "name": "Test Location",
                            "latitude": 51.5,
                            "longitude": -0.1,
                            "ha": False,
                        }
                    ],
                    "updated": [],
                    "deleted": [],
                },
                clean_item_func=lambda x: x,
            )

        assert stats["added"] == 1
        assert any(
            "Applied changeset for Location: 1 added, 0 updated, 0 deleted"
            in record.message
            for record in caplog.records
        )


def test_db_core_logging(app: Flask, caplog: pytest.LogCaptureFixture) -> None:
    """Verify that database initialisation and migration emit INFO logs."""
    with caplog.at_level(logging.INFO):
        init_db(app)

    assert any(
        "Initialising SQLite database" in record.message for record in caplog.records
    )
    assert any(
        "Verifying database tables and applying pending schema migrations"
        in record.message
        for record in caplog.records
    )
    assert any(
        "Database schema verification and migrations complete" in record.message
        for record in caplog.records
    )
