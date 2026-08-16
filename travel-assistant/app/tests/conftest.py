"""Pytest configuration and fixtures for Travel Assistant test suite."""

from typing import Generator
import uuid
import pytest
from flask import Flask
from flask.testing import FlaskClient

from app.db import db, init_db
from app.main import create_app
from app.models.setting import Setting


@pytest.fixture
def temp_db_path(tmp_path: pytest.TempPathFactory) -> Generator[str, None, None]:
    """Create a temporary database file for robust and isolated testing with WAL mode."""
    db_file = str(tmp_path / f"test_{uuid.uuid4().hex}.db")
    yield db_file


@pytest.fixture
def app(temp_db_path: str) -> Generator[Flask, None, None]:
    """Create and configure a Flask application instance for testing."""
    test_app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": temp_db_path,
            "VERSION": "0.1.0-test",
            "APP_NAME": "Travel Assistant Test",
            "SECRET_KEY": "test-secret-key",
        }
    )
    with test_app.app_context():
        init_db(test_app)
        yield test_app
        if db.obj is not None and not db.obj.is_closed():
            db.obj.close()


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """A test client for the app."""
    return app.test_client()


@pytest.fixture
def setting_model(app: Flask) -> Generator[type, None, None]:
    """Setting model fixture with active application context."""
    with app.app_context():
        yield Setting


@pytest.fixture(autouse=True)
def cleanup_worker() -> Generator[None, None, None]:
    """Ensure background worker daemon thread is stopped after each test."""
    yield
    from app.sync.worker import stop_background_worker

    stop_background_worker()
