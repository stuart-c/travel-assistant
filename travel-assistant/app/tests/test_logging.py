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


def test_static_access_log_filter_levels() -> None:
    """Verify that StaticAccessLogFilter downgrades JS and CSS access log records to DEBUG."""
    from app.logging_config import StaticAccessLogFilter

    log_filter = StaticAccessLogFilter()

    # JS request
    record_js = logging.LogRecord(
        name="werkzeug",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='"GET /static/js/db.js?v=abcd1234 HTTP/1.1" 200 -',
        args=(),
        exc_info=None,
    )
    assert log_filter.filter(record_js) is True
    assert record_js.levelno == logging.DEBUG
    assert record_js.levelname == "DEBUG"

    # CSS request
    record_css = logging.LogRecord(
        name="werkzeug",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='"GET /static/css/tables.css HTTP/1.1" 304 -',
        args=(),
        exc_info=None,
    )
    assert log_filter.filter(record_css) is True
    assert record_css.levelno == logging.DEBUG
    assert record_css.levelname == "DEBUG"

    # Standard API request (should remain INFO)
    record_api = logging.LogRecord(
        name="werkzeug",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='"GET /api/ping HTTP/1.1" 200 -',
        args=(),
        exc_info=None,
    )
    assert log_filter.filter(record_api) is True
    assert record_api.levelno == logging.INFO
    assert record_api.levelname == "INFO"

    # Gunicorn access log formatted record
    record_gunicorn_js = logging.LogRecord(
        name="gunicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='127.0.0.1 - - [22/Aug/2026:20:25:00 +0100] "GET /static/js/dirty-manager.js HTTP/1.1" 200 1200 "-" "Mozilla/5.0"',
        args=(),
        exc_info=None,
    )
    assert log_filter.filter(record_gunicorn_js) is True
    assert record_gunicorn_js.levelno == logging.DEBUG
    assert record_gunicorn_js.levelname == "DEBUG"


def test_static_access_log_filter_stream_emission() -> None:
    """Verify stream emission suppression at INFO level and inclusion at DEBUG level."""
    import io
    from app.logging_config import StaticAccessLogFilter

    # 1. INFO level stream
    stream_info = io.StringIO()
    handler_info = logging.StreamHandler(stream_info)
    handler_info.setLevel(logging.INFO)
    handler_info.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

    logger_info = logging.getLogger("test_stream_info")
    logger_info.setLevel(logging.INFO)
    logger_info.handlers.clear()
    logger_info.addHandler(handler_info)
    logger_info.addFilter(StaticAccessLogFilter())

    logger_info.info('"GET /api/ping HTTP/1.1" 200 -')
    logger_info.info('"GET /static/js/db.js HTTP/1.1" 200 -')
    logger_info.info('"GET /static/css/tables.css HTTP/1.1" 200 -')
    logger_info.info('"GET /config/transfers HTTP/1.1" 200 -')

    output_info = stream_info.getvalue()
    assert "GET /api/ping" in output_info
    assert "GET /config/transfers" in output_info
    assert "GET /static/js/db.js" not in output_info
    assert "GET /static/css/tables.css" not in output_info

    # 2. DEBUG level stream
    stream_debug = io.StringIO()
    handler_debug = logging.StreamHandler(stream_debug)
    handler_debug.setLevel(logging.DEBUG)
    handler_debug.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

    logger_debug = logging.getLogger("test_stream_debug")
    logger_debug.setLevel(logging.DEBUG)
    logger_debug.handlers.clear()
    logger_debug.addHandler(handler_debug)
    logger_debug.addFilter(StaticAccessLogFilter())

    logger_debug.info('"GET /api/ping HTTP/1.1" 200 -')
    logger_debug.info('"GET /static/js/db.js HTTP/1.1" 200 -')
    logger_debug.info('"GET /static/css/tables.css HTTP/1.1" 200 -')

    output_debug = stream_debug.getvalue()
    assert 'INFO: "GET /api/ping' in output_debug
    assert 'DEBUG: "GET /static/js/db.js' in output_debug
    assert 'DEBUG: "GET /static/css/tables.css' in output_debug


def test_gunicorn_logger_access_routing() -> None:
    """Verify that GunicornLogger routes JS and CSS access logs to debug and others to info."""
    import datetime
    from unittest.mock import MagicMock
    from gunicorn.config import Config
    from app.logging_config import GunicornLogger

    cfg = Config()
    cfg.set("accesslog", "-")
    cfg.set("errorlog", "-")
    cfg.set("loglevel", "debug")

    glogger = GunicornLogger(cfg)
    glogger.access_log = MagicMock()
    req_time = datetime.timedelta(seconds=0, microseconds=1000)
    mock_resp = MagicMock(status="200 OK")

    # 1. JS request
    glogger.access(
        resp=mock_resp,
        req=MagicMock(path="/static/js/app.js"),
        environ={
            "REQUEST_METHOD": "GET",
            "RAW_URI": "/static/js/app.js",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "PATH_INFO": "/static/js/app.js",
        },
        request_time=req_time,
    )
    assert glogger.access_log.debug.called
    assert not glogger.access_log.info.called
    glogger.access_log.reset_mock()

    # 2. CSS request with query string
    glogger.access(
        resp=mock_resp,
        req=MagicMock(path="/static/css/tables.css"),
        environ={
            "REQUEST_METHOD": "GET",
            "RAW_URI": "/static/css/tables.css?v=123",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "PATH_INFO": "/static/css/tables.css?v=123",
        },
        request_time=req_time,
    )
    assert glogger.access_log.debug.called
    assert not glogger.access_log.info.called
    glogger.access_log.reset_mock()

    # 3. HTML/API request
    glogger.access(
        resp=mock_resp,
        req=MagicMock(path="/api/ping"),
        environ={
            "REQUEST_METHOD": "GET",
            "RAW_URI": "/api/ping",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "PATH_INFO": "/api/ping",
        },
        request_time=req_time,
    )
    assert glogger.access_log.info.called
    assert not glogger.access_log.debug.called
    glogger.access_log.reset_mock()

    # 4. Disabled access log
    cfg_disabled = Config()
    cfg_disabled.set("accesslog", None)
    glogger_disabled = GunicornLogger(cfg_disabled)
    glogger_disabled.access_log = MagicMock()
    glogger_disabled.access(
        resp=mock_resp,
        req=MagicMock(path="/api/ping"),
        environ={
            "REQUEST_METHOD": "GET",
            "RAW_URI": "/api/ping",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "PATH_INFO": "/api/ping",
        },
        request_time=req_time,
    )
    assert not glogger_disabled.access_log.info.called
    assert not glogger_disabled.access_log.debug.called

    # 5. Error handling during access log formatting
    glogger.error = MagicMock()
    glogger.atoms_wrapper_class = MagicMock(side_effect=RuntimeError("Test error"))
    glogger.access(
        resp=mock_resp,
        req=MagicMock(path="/api/ping"),
        environ={
            "REQUEST_METHOD": "GET",
            "RAW_URI": "/api/ping",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "PATH_INFO": "/api/ping",
        },
        request_time=req_time,
    )
    assert glogger.error.called


def test_gunicorn_logger_setup() -> None:
    """Verify that GunicornLogger.setup configures log levels and attaches filters."""
    from gunicorn.config import Config
    from app.logging_config import GunicornLogger, StaticAccessLogFilter

    cfg = Config()
    cfg.set("accesslog", "-")
    cfg.set("errorlog", "-")
    cfg.set("loglevel", "debug")

    glogger = GunicornLogger(cfg)
    glogger.setup(cfg)

    assert glogger.access_log.level == logging.DEBUG
    assert any(isinstance(f, StaticAccessLogFilter) for f in glogger.access_log.filters)


def test_static_access_log_filter_exception_handling() -> None:
    """Verify that StaticAccessLogFilter returns True even if record.getMessage raises."""
    from unittest.mock import MagicMock
    from app.logging_config import StaticAccessLogFilter

    log_filter = StaticAccessLogFilter()
    record = MagicMock()
    record.getMessage.side_effect = RuntimeError("getMessage failure")

    assert log_filter.filter(record) is True


def test_configure_logging_handlers() -> None:
    """Verify that configure_logging applies filters to handlers on werkzeug and gunicorn loggers."""
    import os
    from unittest.mock import patch
    from app.logging_config import configure_logging, StaticAccessLogFilter

    w_logger = logging.getLogger("werkzeug")
    w_handler = logging.StreamHandler()
    w_logger.addHandler(w_handler)

    g_logger = logging.getLogger("gunicorn.access")
    g_handler = logging.StreamHandler()
    g_logger.addHandler(g_handler)

    with patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"}):
        configure_logging()

    assert any(isinstance(f, StaticAccessLogFilter) for f in w_handler.filters)
    assert any(isinstance(f, StaticAccessLogFilter) for f in g_handler.filters)
    assert w_handler.level == logging.DEBUG
    assert g_handler.level == logging.DEBUG
