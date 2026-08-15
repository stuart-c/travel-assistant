"""Pytest configuration and fixtures for Travel Assistant test suite."""

import os
import tempfile
from typing import Generator
import pytest
from flask import Flask
from flask.testing import FlaskClient

from app.main import create_app
from app.db import SettingsRepository, init_db


@pytest.fixture
def temp_db_path() -> Generator[str, None, None]:
    """Create a temporary database file for test isolation."""
    db_fd, db_path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(db_fd)
    yield db_path
    if os.path.exists(db_path):
        os.unlink(db_path)


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


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """A test client for the app."""
    return app.test_client()


@pytest.fixture
def repo(app: Flask) -> Generator[SettingsRepository, None, None]:
    """Settings repository fixture with active application context."""
    with app.app_context():
        yield SettingsRepository()
