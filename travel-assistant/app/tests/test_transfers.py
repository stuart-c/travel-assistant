"""Unit tests for Transfers configuration page, Peewee models, and location search."""

import json
from flask import Flask
from flask.testing import FlaskClient

from app.models import (
    PlatformTransfer,
    Stop,
)


def test_platform_transfer_model_crud(app: Flask) -> None:
    """Test PlatformTransfer model create, get, update, delete, search, and find_transfer."""
    with app.app_context():
        assert list(PlatformTransfer.select()) == []
        assert PlatformTransfer.select().count() == 0

        item = PlatformTransfer.create(
            location_type="rail",
            location_id="PAD",
            location_name="London Paddington",
            from_platform="1",
            to_platform="2",
            transfer_time_minutes=2,
            bidirectional=True,
            step_free=True,
            notes="Adjacent island platform",
        )
        assert item.id > 0
        assert PlatformTransfer.select().count() == 1

        retrieved = PlatformTransfer.get_by_id(item.id)
        assert retrieved.location_type == "rail"
        assert retrieved.location_id == "PAD"
        assert retrieved.from_platform == "1"
        assert retrieved.to_platform == "2"
        assert retrieved.transfer_time_minutes == 2
        assert retrieved.step_free is True

        # Search with location and step_free
        p_res = PlatformTransfer.search(location_id="PAD", step_free=True)
        assert len(p_res) == 1

        # Search with query
        q_res = PlatformTransfer.search(query="Paddington")
        assert len(q_res) == 1

        # find_transfer direct and reverse
        pt_direct = PlatformTransfer.find_transfer("PAD", "1", "2")
        assert pt_direct is not None
        assert pt_direct.transfer_time_minutes == 2

        pt_reverse = PlatformTransfer.find_transfer("PAD", "2", "1")
        assert pt_reverse is not None
        assert pt_reverse.transfer_time_minutes == 2

        assert PlatformTransfer.find_transfer("PAD", "1", "9") is None

        # Update
        retrieved.transfer_time_minutes = 4
        retrieved.save()
        assert PlatformTransfer.get_by_id(item.id).transfer_time_minutes == 4

        # Delete
        retrieved.delete_instance()
        assert PlatformTransfer.select().count() == 0


def test_transfers_get_view(client: FlaskClient) -> None:
    """Test GET /config/transfers returns 200 with HTML template."""
    response = client.get("/config/transfers")
    assert response.status_code == 200
    assert (
        b"Transfers &amp; Interchanges" in response.data
        or b"Transfers" in response.data
    )


def test_transfers_post_save_valid(client: FlaskClient, app: Flask) -> None:
    """Test POST /config/transfers saves valid platform transfers."""
    platform_payload = [
        {
            "location_type": "rail",
            "location_id": "OXF",
            "location_name": "Oxford Rail Station",
            "from_platform": "1",
            "to_platform": "2",
            "transfer_time_minutes": 2,
            "bidirectional": False,
            "step_free": True,
            "notes": "Level footbridge",
        }
    ]

    response = client.post(
        "/config/transfers",
        data={
            "platform_transfers_json": json.dumps(
                {"added": platform_payload, "updated": [], "deleted": []}
            ),
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        plat_transfers = list(PlatformTransfer.select())
        assert len(plat_transfers) == 1
        assert plat_transfers[0].from_platform == "1"
        assert plat_transfers[0].bidirectional is False


def test_transfers_post_invalid_json(client: FlaskClient) -> None:
    """Test POST /config/transfers handles malformed JSON gracefully."""
    response = client.post(
        "/config/transfers",
        data={
            "platform_transfers_json": "INVALID_JSON",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200


def test_search_transfers_locations_all(client: FlaskClient, app: Flask) -> None:
    """Test GET /config/search/places returns empty when unpopulated and records when cached."""
    # 1. Unpopulated test
    response_empty = client.get("/config/search/places")
    assert response_empty.status_code == 200
    data_empty = response_empty.get_json()
    assert data_empty["total"] == 0
    assert data_empty["results"] == []

    # 2. Populated test
    with app.app_context():
        Stop.bulk_upsert(
            [
                {
                    "atco_code": "9100PAD",
                    "naptan_code": "PAD",
                    "stop_type": "rail",
                    "name": "London Paddington",
                },
                {
                    "atco_code": "490000001",
                    "stop_type": "bus",
                    "name": "Victoria Coach Station",
                },
            ]
        )

    response = client.get("/config/search/places")
    assert response.status_code == 200
    data = response.get_json()
    assert "results" in data
    assert "total" in data
    assert data["total"] == 2
    types = [item["type"] for item in data["results"]]
    assert "rail" in types and "bus" in types


def test_search_transfers_locations_rail_filter(
    client: FlaskClient, app: Flask
) -> None:
    """Test GET /config/search/places with type=rail filter."""
    with app.app_context():
        Stop.bulk_upsert(
            [
                {
                    "atco_code": "9100PAD",
                    "naptan_code": "PAD",
                    "stop_type": "rail",
                    "name": "London Paddington",
                },
                {
                    "atco_code": "490000001",
                    "stop_type": "bus",
                    "name": "Victoria Coach Station",
                },
            ]
        )

    response = client.get("/config/search/places?type=rail")
    assert response.status_code == 200
    data = response.get_json()
    assert data["total"] == 1
    for item in data["results"]:
        assert item["type"] == "rail"
        assert item["id"] == "naptan:PAD"


def test_search_transfers_locations_bus_filter(client: FlaskClient, app: Flask) -> None:
    """Test GET /config/search/places with type=bus filter."""
    with app.app_context():
        Stop.bulk_upsert(
            [
                {
                    "atco_code": "9100PAD",
                    "naptan_code": "PAD",
                    "stop_type": "rail",
                    "name": "London Paddington",
                },
                {
                    "atco_code": "490000001",
                    "stop_type": "bus",
                    "name": "Victoria Coach Station",
                },
            ]
        )

    response = client.get("/config/search/places?type=bus")
    assert response.status_code == 200
    data = response.get_json()
    assert data["total"] == 1
    for item in data["results"]:
        assert item["type"] == "bus"
        assert item["id"] == "atco:490000001"


def test_search_transfers_locations_query(client: FlaskClient, app: Flask) -> None:
    """Test GET /config/search/places with matching and non-matching queries."""
    with app.app_context():
        Stop.bulk_upsert(
            [
                {
                    "atco_code": "9100OXF",
                    "naptan_code": "OXF",
                    "stop_type": "rail",
                    "name": "Oxford Rail Station",
                }
            ]
        )

    res_match = client.get("/config/search/places?q=Oxford")
    assert res_match.status_code == 200
    data = res_match.get_json()
    assert data["total"] > 0
    assert any("Oxford" in item["name"] for item in data["results"])

    res_nomatch = client.get("/config/search/places?q=NonExistentLocXYZ999")
    assert res_nomatch.status_code == 200
    data_no = res_nomatch.get_json()
    assert data_no["total"] == 0


def test_transfers_save_leave_and_return_persistence(client: FlaskClient) -> None:
    """Verify that saving transfers persists across leaving and returning to the page."""
    plat_payload = [
        {
            "location_type": "rail",
            "location_id": "9100WAT",
            "location_name": "London Waterloo",
            "from_platform": "1",
            "to_platform": "12",
            "transfer_time_minutes": 5,
            "bidirectional": True,
            "step_free": True,
            "notes": "Footbridge",
        }
    ]

    post_resp = client.post(
        "/config/transfers",
        data={
            "platform_transfers_json": json.dumps(
                {"added": plat_payload, "updated": [], "deleted": []}
            ),
        },
        follow_redirects=True,
    )
    assert post_resp.status_code == 200
    assert b"Transfers saved successfully." in post_resp.data

    # Leave page
    assert client.get("/").status_code == 200
    assert client.get("/config/locations").status_code == 200
    assert client.get("/config/journeys").status_code == 200

    # Return to Transfers
    return_resp = client.get("/config/transfers")
    assert return_resp.status_code == 200
    # Verify data available via /data endpoint
    data_resp = client.get("/config/transfers/data")
    assert data_resp.status_code == 200
    plat_transfers = data_resp.get_json()["data"]

    assert len(plat_transfers) == 1
    assert plat_transfers[0]["location_name"] == "London Waterloo"
    assert plat_transfers[0]["from_platform"] == "1"
    assert plat_transfers[0]["to_platform"] == "12"
    assert plat_transfers[0]["transfer_time_minutes"] == 5


def test_config_transfers_data_endpoint(app: Flask, client: FlaskClient) -> None:
    """Test GET /config/transfers/data returns all platform transfers as JSON."""
    with app.app_context():
        PlatformTransfer.delete().execute()
        PlatformTransfer.insert_many(
            [
                {
                    "location_type": "rail",
                    "location_id": "WAT",
                    "location_name": "London Waterloo",
                    "from_platform": "1",
                    "to_platform": "2",
                    "transfer_time_minutes": 3,
                    "bidirectional": True,
                    "step_free": False,
                    "notes": "",
                }
            ]
        ).execute()

    response = client.get("/config/transfers/data")
    assert response.status_code == 200
    assert response.content_type.startswith("application/json")
    payload = response.get_json()
    assert "data" in payload
    assert "total" in payload
    assert payload["total"] == 1
    assert payload["data"][0]["location_name"] == "London Waterloo"
    assert payload["data"][0]["from_platform"] == "1"
