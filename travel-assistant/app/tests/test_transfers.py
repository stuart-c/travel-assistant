"""Unit tests for Transfers configuration page, Peewee models, and location search."""

import json
from flask import Flask
from flask.testing import FlaskClient

from app.models import (
    LocationTransfer,
    PlatformTransfer,
    Stop,
)


def test_location_transfer_model_crud(app: Flask) -> None:
    """Test LocationTransfer model create, get, update, delete, and search."""
    with app.app_context():
        # Initial state should be empty
        assert list(LocationTransfer.select()) == []
        assert LocationTransfer.select().count() == 0

        # Add an inter-location transfer
        item = LocationTransfer.create(
            from_type="rail",
            from_id="OXF",
            from_name="Oxford Rail Station",
            to_type="bus",
            to_id="340000001",
            to_name="Frideswide Square (Stop R1)",
            transfer_time_minutes=4,
            bidirectional=True,
            step_free=True,
            notes="Exit via main forecourt",
        )
        assert item.id > 0
        assert LocationTransfer.select().count() == 1

        # Retrieve single transfer
        retrieved = LocationTransfer.get_by_id(item.id)
        assert retrieved.from_type == "rail"
        assert retrieved.from_id == "OXF"
        assert retrieved.from_name == "Oxford Rail Station"
        assert retrieved.to_type == "bus"
        assert retrieved.to_id == "340000001"
        assert retrieved.to_name == "Frideswide Square (Stop R1)"
        assert retrieved.transfer_time_minutes == 4
        assert retrieved.bidirectional is True
        assert retrieved.step_free is True
        assert retrieved.notes == "Exit via main forecourt"

        # Update
        retrieved.transfer_time_minutes = 6
        retrieved.save()
        assert LocationTransfer.get_by_id(item.id).transfer_time_minutes == 6

        # Search with type filters
        res = LocationTransfer.search(from_type="rail", to_type="bus", step_free=True)
        assert len(res) == 1

        # Delete
        retrieved.delete_instance()
        assert LocationTransfer.select().count() == 0


def test_platform_transfer_model_crud(app: Flask) -> None:
    """Test PlatformTransfer model create, get, update, and delete."""
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
    """Test POST /config/transfers saves valid location and platform transfers."""
    location_payload = [
        {
            "from_type": "rail",
            "from_id": "OXF",
            "from_name": "Oxford Rail Station",
            "to_type": "bus",
            "to_id": "340000001",
            "to_name": "Frideswide Square (Stop R1)",
            "transfer_time_minutes": 5,
            "bidirectional": True,
            "step_free": True,
            "notes": "Main exit",
        }
    ]
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
            "location_transfers_json": json.dumps(location_payload),
            "platform_transfers_json": json.dumps(platform_payload),
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        loc_transfers = list(LocationTransfer.select())
        plat_transfers = list(PlatformTransfer.select())
        assert len(loc_transfers) == 1
        assert loc_transfers[0].from_id == "OXF"
        assert len(plat_transfers) == 1
        assert plat_transfers[0].from_platform == "1"
        assert plat_transfers[0].bidirectional is False


def test_transfers_post_invalid_json(client: FlaskClient) -> None:
    """Test POST /config/transfers handles malformed JSON gracefully."""
    response = client.post(
        "/config/transfers",
        data={
            "location_transfers_json": "INVALID_JSON",
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
    loc_payload = [
        {
            "from_type": "rail",
            "from_id": "9100WAT",
            "from_name": "London Waterloo",
            "to_type": "bus",
            "to_id": "490000077E",
            "to_name": "Euston Bus Stop",
            "transfer_time_minutes": 8,
            "bidirectional": True,
            "step_free": True,
            "notes": "Walking connection",
        }
    ]
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
            "location_transfers_json": json.dumps(loc_payload),
            "platform_transfers_json": json.dumps(plat_payload),
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
    page_html = return_resp.get_data(as_text=True)

    # Verify location transfer
    start_tag_loc = (
        '<script id="initial-location-transfers-data" type="application/json">'
    )
    end_tag = "</script>"
    start_idx = page_html.find(start_tag_loc) + len(start_tag_loc)
    end_idx = page_html.find(end_tag, start_idx)
    loc_transfers = json.loads(page_html[start_idx:end_idx])

    assert len(loc_transfers) == 1
    assert loc_transfers[0]["from_name"] == "London Waterloo"
    assert loc_transfers[0]["to_name"] == "Euston Bus Stop"
    assert loc_transfers[0]["transfer_time_minutes"] == 8
    assert loc_transfers[0]["step_free"] is True

    # Verify platform transfer
    start_tag_plat = (
        '<script id="initial-platform-transfers-data" type="application/json">'
    )
    start_plat_idx = page_html.find(start_tag_plat) + len(start_tag_plat)
    end_plat_idx = page_html.find(end_tag, start_plat_idx)
    plat_transfers = json.loads(page_html[start_plat_idx:end_plat_idx])

    assert len(plat_transfers) == 1
    assert plat_transfers[0]["location_name"] == "London Waterloo"
    assert plat_transfers[0]["from_platform"] == "1"
    assert plat_transfers[0]["to_platform"] == "12"
    assert plat_transfers[0]["transfer_time_minutes"] == 5
