"""Unit tests for Locations configuration page, Peewee model, and map integration."""

import json
from flask import Flask
from flask.testing import FlaskClient

from app.db import get_db_stats
from app.models import Location


def test_location_model_crud(app: Flask) -> None:
    """Test Location model create, get, update, delete, search, and stats."""
    with app.app_context():
        assert list(Location.select()) == []
        assert Location.select().count() == 0

        # Create locations
        loc1 = Location.create(
            name="Home",
            latitude=51.7520,
            longitude=-1.2577,
        )
        loc2 = Location.create(
            name="Workplace",
            latitude=51.5074,
            longitude=-0.1278,
        )

        assert loc1.id > 0
        assert loc2.id > 0
        assert Location.select().count() == 2

        # Get by ID and check dict representation
        retrieved = Location.get_by_id(loc1.id)
        assert retrieved.name == "Home"
        assert retrieved.latitude == 51.7520
        assert retrieved.longitude == -1.2577

        loc_dict = retrieved.to_dict()
        assert loc_dict["name"] == "Home"
        assert loc_dict["latitude"] == 51.7520
        assert loc_dict["longitude"] == -1.2577
        assert "created_at" in loc_dict
        assert "updated_at" in loc_dict

        # Update
        retrieved.name = "Home Sweet Home"
        retrieved.save()
        assert Location.get_by_id(loc1.id).name == "Home Sweet Home"

        # Search
        search_res = Location.search("Home")
        assert len(search_res) == 1
        assert search_res[0].name == "Home Sweet Home"

        search_empty = Location.search("NonExistent")
        assert len(search_empty) == 0

        search_all = Location.search("")
        assert len(search_all) == 2

        # Stats
        stats = Location.get_stats()
        assert stats["total"] == 2

        # Delete
        loc2.delete_instance()
        assert Location.select().count() == 1


def test_get_locations_page(client: FlaskClient, app: Flask) -> None:
    """Test GET /config/locations renders correctly with empty and populated initial data."""
    # Empty state
    response = client.get("/config/locations")
    assert response.status_code == 200
    assert b"Locations" in response.data
    assert b"Configured Locations" in response.data
    assert b"location-modal" in response.data
    assert b"location-map" in response.data
    assert b"nav-link-locations" in response.data
    assert b"leaflet" in response.data

    # Populated state
    with app.app_context():
        Location.create(
            name="Oxford Town Hall",
            latitude=51.7519,
            longitude=-1.2578,
        )

    response_populated = client.get("/config/locations")
    assert response_populated.status_code == 200
    assert b"Oxford Town Hall" in response_populated.data


def test_post_locations_success(client: FlaskClient, app: Flask) -> None:
    """Test POST /config/locations saves locations atomically and performs PRG redirect."""
    with app.app_context():
        Location.create(name="Old Location", latitude=50.0, longitude=0.0)
        assert Location.select().count() == 1

    payload = [
        {"name": "London Eye", "latitude": 51.5033, "longitude": -0.1195},
        {"name": "Big Ben", "latitude": "51.5007", "longitude": "-0.1246"},
    ]

    response = client.post(
        "/config/locations",
        data={"locations_json": json.dumps(payload)},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Locations saved successfully." in response.data

    with app.app_context():
        saved = list(Location.select())
        assert len(saved) == 2
        names = [s.name for s in saved]
        assert "London Eye" in names
        assert "Big Ben" in names


def test_post_locations_empty_list_clears_records(
    client: FlaskClient, app: Flask
) -> None:
    """Test POST /config/locations with empty list clears existing records."""
    with app.app_context():
        Location.create(name="Temporary Place", latitude=51.5, longitude=-0.1)
        assert Location.select().count() == 1

    response = client.post(
        "/config/locations",
        data={"locations_json": "[]"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Locations saved successfully." in response.data

    with app.app_context():
        assert Location.select().count() == 0


def test_post_locations_invalid_json(client: FlaskClient) -> None:
    """Test POST /config/locations with invalid JSON displays error message."""
    response = client.post(
        "/config/locations",
        data={"locations_json": "invalid-json-{"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Failed to save locations:" in response.data


def test_post_locations_non_list_payload(client: FlaskClient) -> None:
    """Test POST /config/locations with a non-list JSON payload."""
    response = client.post(
        "/config/locations",
        data={"locations_json": json.dumps({"name": "Solo Object"})},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert (
        b"Failed to save locations: Payload must be a list of location objects."
        in response.data
    )


def test_post_locations_skips_invalid_entries(client: FlaskClient, app: Flask) -> None:
    """Test POST /config/locations skips entries with missing name or invalid coordinates."""
    payload = [
        "not-a-dict",
        {"name": "", "latitude": 51.5, "longitude": -0.1},  # missing name
        {"name": "Missing Lat", "longitude": -0.1},  # missing lat
        {"name": "Missing Lon", "latitude": 51.5},  # missing lon
        {"name": "Bad Lat Str", "latitude": "invalid", "longitude": -0.1},  # bad lat
        {"name": "Bad Lon Str", "latitude": 51.5, "longitude": "invalid"},  # bad lon
        {"name": "Lat Out of Range", "latitude": 95.0, "longitude": -0.1},  # lat > 90
        {"name": "Lat Neg Range", "latitude": -95.0, "longitude": -0.1},  # lat < -90
        {"name": "Lon Out of Range", "latitude": 51.5, "longitude": 185.0},  # lon > 180
        {"name": "Lon Neg Range", "latitude": 51.5, "longitude": -185.0},  # lon < -180
        {"name": "Valid Place", "latitude": 51.7520, "longitude": -1.2577},  # valid
    ]

    response = client.post(
        "/config/locations",
        data={"locations_json": json.dumps(payload)},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Locations saved successfully." in response.data

    with app.app_context():
        saved = list(Location.select())
        assert len(saved) == 1
        assert saved[0].name == "Valid Place"
        assert saved[0].latitude == 51.7520
        assert saved[0].longitude == -1.2577


def test_db_stats_includes_locations(app: Flask) -> None:
    """Test get_db_stats inspects and reports records for locations table."""
    with app.app_context():
        Location.create(name="Stats Location 1", latitude=51.5, longitude=-0.1)
        Location.create(name="Stats Location 2", latitude=51.6, longitude=-0.2)

        stats = get_db_stats(app)
        assert "tables" in stats
        loc_table = next((t for t in stats["tables"] if t["name"] == "locations"), None)
        assert loc_table is not None
        assert loc_table["row_count"] == 2
