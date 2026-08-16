"""Unit tests for Walking configuration page, Peewee model, and CRUD workflows."""

import json
from flask import Flask
from flask.testing import FlaskClient

from app.db import get_db_stats
from app.models import Walking


def test_walking_model_crud(app: Flask) -> None:
    """Test Walking model create, get, update, delete, search, reverse lookup, and stats."""
    with app.app_context():
        assert list(Walking.select()) == []
        assert Walking.select().count() == 0

        # Create walking routes
        w1 = Walking.create(
            start_type="ha",
            start_id="zone.home",
            start_name="Home",
            finish_type="bus",
            finish_id="490000077E",
            finish_name="King's Cross Station (Stop E)",
            time_needed_minutes=8,
            bidirectional=True,
        )
        w2 = Walking.create(
            start_type="rail",
            start_id="9100KNGX",
            start_name="London King's Cross",
            finish_type="custom",
            finish_id="custom:office",
            finish_name="Workplace",
            time_needed_minutes=15,
            bidirectional=False,
        )

        assert w1.id > 0
        assert w2.id > 0
        assert Walking.select().count() == 2

        # Get by ID and verify dict conversion
        retrieved = Walking.get_by_id(w1.id)
        assert retrieved.start_type == "ha"
        assert retrieved.start_id == "zone.home"
        assert retrieved.start_name == "Home"
        assert retrieved.finish_type == "bus"
        assert retrieved.finish_id == "490000077E"
        assert retrieved.finish_name == "King's Cross Station (Stop E)"
        assert retrieved.time_needed_minutes == 8
        assert retrieved.bidirectional is True

        w_dict = retrieved.to_dict()
        assert w_dict["id"] == w1.id
        assert w_dict["start_type"] == "ha"
        assert w_dict["start_id"] == "zone.home"
        assert w_dict["time_needed_minutes"] == 8
        assert w_dict["bidirectional"] is True
        assert "created_at" in w_dict
        assert "updated_at" in w_dict

        # Update
        retrieved.time_needed_minutes = 10
        retrieved.save()
        assert Walking.get_by_id(w1.id).time_needed_minutes == 10

        # Search by name
        res_home = Walking.search("Home")
        assert len(res_home) == 1
        assert res_home[0].start_name == "Home"

        # Search by ID
        res_id = Walking.search("490000077E")
        assert len(res_id) == 1
        assert res_id[0].finish_id == "490000077E"

        # Search non-existent
        assert len(Walking.search("NonExistentXYZ")) == 0

        # Find walking route (direct)
        direct = Walking.find_walking_route("ha", "zone.home", "bus", "490000077E")
        assert direct is not None
        assert direct.id == w1.id

        # Find walking route (reverse - bidirectional=True)
        reverse_bidi = Walking.find_walking_route(
            "bus", "490000077E", "ha", "zone.home"
        )
        assert reverse_bidi is not None
        assert reverse_bidi.id == w1.id

        # Find walking route (reverse - bidirectional=False)
        reverse_unidi = Walking.find_walking_route(
            "custom", "custom:office", "rail", "9100KNGX"
        )
        assert reverse_unidi is None

        # Stats
        stats = Walking.get_stats()
        assert stats["total"] == 2

        # Delete
        w2.delete_instance()
        assert Walking.select().count() == 1


def test_get_walking_page(client: FlaskClient, app: Flask) -> None:
    """Test GET /config/walking renders correctly with empty and populated initial data."""
    # Empty state
    response = client.get("/config/walking")
    assert response.status_code == 200
    assert b"Walking" in response.data
    assert b"Configured Walking Routes" in response.data
    assert b"walking-modal" in response.data
    assert b"nav-link-walking" in response.data
    assert b"walking.js" in response.data

    # Populated state
    with app.app_context():
        Walking.create(
            start_type="ha",
            start_id="zone.home",
            start_name="Home Sweet Home",
            finish_type="bus",
            finish_id="3400001",
            finish_name="Local Bus Stop",
            time_needed_minutes=6,
            bidirectional=True,
        )

    response_populated = client.get("/config/walking")
    assert response_populated.status_code == 200
    assert b"Home Sweet Home" in response_populated.data
    assert b"Local Bus Stop" in response_populated.data


def test_post_walking_success(client: FlaskClient, app: Flask) -> None:
    """Test POST /config/walking saves walking routes atomically and performs PRG redirect."""
    with app.app_context():
        Walking.create(
            start_type="custom",
            start_id="loc1",
            start_name="Old Route",
            finish_type="custom",
            finish_id="loc2",
            finish_name="Old Dest",
            time_needed_minutes=5,
        )
        assert Walking.select().count() == 1

    payload = [
        {
            "start_type": "ha",
            "start_id": "zone.home",
            "start_name": "Home",
            "finish_type": "bus",
            "finish_id": "490000077E",
            "finish_name": "King's Cross Stop E",
            "time_needed_minutes": 7,
            "bidirectional": True,
        },
        {
            "start_type": "rail",
            "start_id": "9100KNGX",
            "start_name": "King's Cross",
            "finish_type": "custom",
            "finish_id": "custom:cafe",
            "finish_name": "Coffee Shop",
            "time_needed_minutes": "4",
            "bidirectional": False,
        },
    ]

    response = client.post(
        "/config/walking",
        data={"walking_json": json.dumps(payload)},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Walking saved successfully." in response.data

    with app.app_context():
        saved = list(Walking.select())
        assert len(saved) == 2
        start_names = [s.start_name for s in saved]
        assert "Home" in start_names
        assert "King's Cross" in start_names
        assert "Old Route" not in start_names


def test_post_walking_empty_list_clears_records(
    client: FlaskClient, app: Flask
) -> None:
    """Test POST /config/walking with empty list clears existing records."""
    with app.app_context():
        Walking.create(
            start_type="custom",
            start_id="c1",
            start_name="Path A",
            finish_type="custom",
            finish_id="c2",
            finish_name="Path B",
            time_needed_minutes=5,
        )
        assert Walking.select().count() == 1

    response = client.post(
        "/config/walking",
        data={"walking_json": "[]"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Walking saved successfully." in response.data

    with app.app_context():
        assert Walking.select().count() == 0


def test_post_walking_invalid_json(client: FlaskClient) -> None:
    """Test POST /config/walking with invalid JSON displays error message."""
    response = client.post(
        "/config/walking",
        data={"walking_json": "invalid-json-{"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Failed to save walking:" in response.data


def test_post_walking_non_list_payload(client: FlaskClient) -> None:
    """Test POST /config/walking with a non-list JSON payload."""
    response = client.post(
        "/config/walking",
        data={"walking_json": json.dumps({"start_name": "Solo Object"})},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Failed to save walking:" in response.data
    assert b"must contain a JSON list" in response.data


def test_post_walking_skips_invalid_entries(client: FlaskClient, app: Flask) -> None:
    """Test POST /config/walking skips malformed entries."""
    payload = [
        "not-a-dict",
        {"start_name": "", "finish_name": "Dest"},  # missing start_id & start_name
        {
            "start_type": "custom",
            "start_id": "c1",
            "start_name": "Start",
            "finish_id": "",
            "finish_name": "",
        },  # missing finish
        {
            "start_type": "custom",
            "start_id": "c1",
            "start_name": "Start",
            "finish_type": "unknown_type",
            "finish_id": "c2",
            "finish_name": "Finish",
            "time_needed_minutes": -5,  # negative time defaults to min 1
            "bidirectional": True,
        },
    ]

    response = client.post(
        "/config/walking",
        data={"walking_json": json.dumps(payload)},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Walking saved successfully." in response.data

    with app.app_context():
        saved = list(Walking.select())
        assert len(saved) == 1
        assert saved[0].start_id == "c1"
        assert saved[0].finish_type == "custom"  # fallback for unknown type
        assert saved[0].time_needed_minutes == 1


def test_db_stats_includes_walking(app: Flask) -> None:
    """Test get_db_stats inspects and reports records for walking table."""
    with app.app_context():
        Walking.create(
            start_type="custom",
            start_id="a1",
            start_name="Alpha",
            finish_type="custom",
            finish_id="b1",
            finish_name="Beta",
            time_needed_minutes=10,
        )

        stats = get_db_stats(app)
        assert "tables" in stats
        walking_table = next(
            (t for t in stats["tables"] if t["name"] == "walking"), None
        )
        assert walking_table is not None
        assert walking_table["row_count"] == 1
        assert walking_table["syncable"] is False


def test_clean_walking_item() -> None:
    """Test clean_walking_item validator with various valid and invalid inputs."""
    from app.views.config.walking import clean_walking_item

    # Non-dict
    assert clean_walking_item("not a dict") is None
    assert clean_walking_item(123) is None

    # Missing mandatory fields
    assert clean_walking_item({"start_id": "s1", "start_name": "S1"}) is None
    assert clean_walking_item({"finish_id": "f1", "finish_name": "F1"}) is None
    assert clean_walking_item({}) is None

    # Invalid types fallback to custom
    res = clean_walking_item(
        {
            "start_type": "invalid_type",
            "start_id": "s1",
            "start_name": "Start",
            "finish_type": "another_invalid",
            "finish_id": "f1",
            "finish_name": "Finish",
            "time_needed_minutes": "not_a_number",
            "bidirectional": False,
        }
    )
    assert res is not None
    assert res["start_type"] == "custom"
    assert res["finish_type"] == "custom"
    assert res["time_needed_minutes"] == 5
    assert res["bidirectional"] is False

    # Valid item
    valid = clean_walking_item(
        {
            "start_type": "rail",
            "start_id": "9100KNGX",
            "start_name": "King's Cross",
            "finish_type": "bus",
            "finish_id": "490000077E",
            "finish_name": "Stop E",
            "time_needed_minutes": "12",
            "bidirectional": "true",
        }
    )
    assert valid is not None
    assert valid["start_type"] == "rail"
    assert valid["start_id"] == "9100KNGX"
    assert valid["finish_type"] == "bus"
    assert valid["finish_id"] == "490000077E"
    assert valid["time_needed_minutes"] == 12
    assert valid["bidirectional"] is True
