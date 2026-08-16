"""Unit tests for Journeys configuration page, SQLite model, and location search."""

import json
import pytest
from flask import Flask
from flask.testing import FlaskClient

from app.db import get_db_stats
from app.models import Journey, Location, Stop


@pytest.fixture
def sample_station(app: Flask) -> Stop:
    """Create a sample railway station record."""
    with app.app_context():
        return Stop.create(
            atco_code="9100WAT",
            naptan_code="WAT",
            stop_type="rail",
            name="London Waterloo",
            latitude=51.5031,
            longitude=-0.1132,
        )


@pytest.fixture
def sample_bus_stop(app: Flask) -> Stop:
    """Create a sample bus stop record."""
    with app.app_context():
        return Stop.create(
            atco_code="490000077E",
            stop_type="bus",
            name="Euston Station",
            indicator="Stop E",
            locality="Euston",
            latitude=51.5284,
            longitude=-0.1337,
        )


@pytest.fixture
def sample_custom_location(app: Flask) -> Location:
    """Create a sample custom user location record."""
    with app.app_context():
        return Location.create(
            name="Home",
            latitude=51.5074,
            longitude=-0.1278,
        )


def test_journey_model_lifecycle(
    app: Flask, sample_station: Stop, sample_custom_location: Location
) -> None:
    """Test Journey model creation, time settings serialisation, and retrieval."""
    with app.app_context():
        time_windows = [
            {
                "days": ["mon", "tue", "wed", "thu", "fri"],
                "mode": "depart",
                "start_time": "07:30",
                "end_time": "08:30",
            },
            {
                "days": ["sat", "sun"],
                "mode": "arrive",
                "start_time": "10:00",
                "end_time": "11:30",
            },
        ]

        journey = Journey.create(
            name="Morning Commute",
            from_type="custom_location",
            from_id=str(sample_custom_location.id),
            from_name=sample_custom_location.name,
            to_type="station",
            to_id=sample_station.naptan_code or sample_station.atco_code,
            to_name=sample_station.name,
        )
        journey.set_time_settings(time_windows)
        journey.save()

        retrieved = Journey.get_by_id(journey.id)
        assert retrieved.name == "Morning Commute"
        assert retrieved.from_name == "Home"
        assert retrieved.to_name == "London Waterloo"
        assert len(retrieved.get_time_settings()) == 2
        assert retrieved.get_time_settings()[0]["mode"] == "depart"

        data = retrieved.to_dict()
        assert data["name"] == "Morning Commute"
        assert len(data["time_settings"]) == 2
        assert "created_at" in data

        # Test edge cases for time_settings
        retrieved.time_settings = "invalid-json"
        assert retrieved.get_time_settings() == []
        retrieved.time_settings = None
        assert retrieved.get_time_settings() == []


def test_journey_search_and_stats(app: Flask, sample_station: Stop) -> None:
    """Test Journey search helper and stats aggregate."""
    with app.app_context():
        Journey.create(
            name="Airport Shuttle",
            from_type="station",
            from_id="WAT",
            from_name="London Waterloo",
            to_type="station",
            to_id="LGW",
            to_name="Gatwick Airport",
            time_settings="[]",
        )
        Journey.create(
            name="Weekend Trip",
            from_type="station",
            from_id="WAT",
            from_name="London Waterloo",
            to_type="station",
            to_id="BHM",
            to_name="Birmingham New Street",
            time_settings="[]",
        )

        results = Journey.search("Airport")
        assert len(results) == 1
        assert results[0].name == "Airport Shuttle"

        results_dest = Journey.search("Birmingham")
        assert len(results_dest) == 1
        assert results_dest[0].name == "Weekend Trip"

        stats = Journey.get_stats()
        assert stats["total"] >= 2


def test_config_journeys_get(client: FlaskClient) -> None:
    """Test GET /config/journeys loads the configuration view successfully."""
    response = client.get("/config/journeys")
    assert response.status_code == 200
    assert b"Configured Journeys" in response.data
    assert b"journeys-grid-wrapper" in response.data
    assert b"Add New Journey" in response.data


def test_config_journeys_post_persistence(app: Flask, client: FlaskClient) -> None:
    """Test POST /config/journeys atomically persists journey records."""
    payload = [
        {
            "name": "Daily Commute",
            "from_type": "custom_location",
            "from_id": "1",
            "from_name": "Home",
            "to_type": "station",
            "to_id": "WAT",
            "to_name": "London Waterloo",
            "time_settings": [
                {
                    "days": ["mon", "tue", "wed", "thu", "fri", "bank_holiday"],
                    "mode": "depart",
                    "start_time": "08:00",
                    "end_time": "09:00",
                }
            ],
        },
        {
            "name": "Evening Return",
            "from_type": "station",
            "from_id": "WAT",
            "from_name": "London Waterloo",
            "to_type": "custom_location",
            "to_id": "1",
            "to_name": "Home",
            "time_settings": [],
        },
    ]

    response = client.post(
        "/config/journeys",
        data={"journeys_json": json.dumps(payload)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["Location"].endswith("/config/journeys")

    # Verify saved in database
    with app.app_context():
        journeys = list(Journey.select())
        assert len(journeys) == 2
        assert journeys[0].name == "Daily Commute"
        assert len(journeys[0].get_time_settings()) == 1
        assert journeys[0].get_time_settings()[0]["days"] == [
            "mon",
            "tue",
            "wed",
            "thu",
            "fri",
            "bank_holiday",
        ]
        assert journeys[1].name == "Evening Return"
        assert journeys[1].get_time_settings() == []


def test_config_journeys_post_invalid_json(client: FlaskClient) -> None:
    """Test POST /config/journeys gracefully handles invalid JSON."""
    response = client.post(
        "/config/journeys",
        data={"journeys_json": "invalid-non-json"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Failed to save journeys" in response.data


def test_config_journeys_search(
    client: FlaskClient,
    sample_station: Stop,
    sample_bus_stop: Stop,
    sample_custom_location: Location,
) -> None:
    """Test GET /config/search/places returns categorised locations with icons and IDs."""
    # Test broad search
    response = client.get("/config/search/places?q=London")
    assert response.status_code == 200
    data = response.get_json()
    assert "results" in data
    assert any(
        item["type"] == "station"
        and item["icon"] == "train"
        and item["id"] == "naptan:WAT"
        for item in data["results"]
    )

    # Test bus stop search
    response_bus = client.get("/config/search/places?q=Euston&type=bus_stop")
    assert response_bus.status_code == 200
    data_bus = response_bus.get_json()
    assert len(data_bus["results"]) >= 1
    assert data_bus["results"][0]["icon"] == "directions_bus"
    assert data_bus["results"][0]["indicator"] == "Stop E"
    assert data_bus["results"][0]["id"] == "atco:490000077E"

    # Test custom location search
    response_custom = client.get("/config/search/places?q=Home&type=custom_location")
    assert response_custom.status_code == 200
    data_custom = response_custom.get_json()
    assert len(data_custom["results"]) >= 1
    assert data_custom["results"][0]["icon"] == "pin_drop"
    assert data_custom["results"][0]["indicator"] == "Custom"
    assert data_custom["results"][0]["id"] == str(sample_custom_location.id)


def test_db_stats_includes_journeys(app: Flask) -> None:
    """Test get_db_stats correctly reports journeys table counts."""
    with app.app_context():
        Journey.create(
            name="Test Route",
            from_type="station",
            from_id="WAT",
            from_name="Waterloo",
            to_type="station",
            to_id="VIC",
            to_name="Victoria",
            time_settings="[]",
        )

        stats = get_db_stats(app)
        journey_table = next(
            (t for t in stats["tables"] if t["name"] == "journeys"), None
        )
        assert journey_table is not None
        assert journey_table["row_count"] >= 1
