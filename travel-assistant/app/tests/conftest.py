"""Pytest configuration and fixtures."""

import pytest
from flask import Flask
from flask.testing import FlaskClient

try:
    from app.main import create_app
except ImportError:  # pragma: no cover
    from travel_assistant.app.main import create_app


@pytest.fixture
def app() -> Flask:
    """Create and configure a Flask application instance for testing."""
    test_app = create_app(
        {
            "TESTING": True,
            "VERSION": "0.1.0-test",
            "APP_NAME": "Travel Assistant Test",
        }
    )
    return test_app


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """A test client for the app."""
    return app.test_client()
