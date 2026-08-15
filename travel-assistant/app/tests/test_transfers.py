"""Unit tests for Transfers configuration page, database repositories, and location search."""

import json
from unittest.mock import MagicMock
import pytest
from flask import Flask
from flask.testing import FlaskClient

from app.db import (
    BusStopRepository,
    LocationTransferRepository,
    PlatformTransferRepository,
    StationRepository,
    TransferRepository,
)

# --- Repository Unit Tests ---


def test_location_transfer_repository_crud(app: Flask) -> None:
    """Test LocationTransferRepository add, get, update, delete, and get_all."""
    with app.app_context():
        repo = LocationTransferRepository()

        # Initial state should be empty
        assert repo.get_all() == []
        assert repo.get(999) is None
        assert repo.count() == 0

        # Add an inter-location transfer
        trans_id = repo.add(
            from_type="station",
            from_id="OXF",
            from_name="Oxford Rail Station",
            to_type="bus_stop",
            to_id="340000001",
            to_name="Frideswide Square (Stop R1)",
            transfer_time_minutes=4,
            bidirectional=True,
            step_free=True,
            notes="Exit via main forecourt",
        )
        assert trans_id > 0
        assert repo.count() == 1

        # Retrieve single transfer
        item = repo.get(trans_id)
        assert item is not None
        assert item["id"] == trans_id
        assert item["from_type"] == "station"
        assert item["from_id"] == "OXF"
        assert item["from_name"] == "Oxford Rail Station"
        assert item["to_type"] == "bus_stop"
        assert item["to_id"] == "340000001"
        assert item["to_name"] == "Frideswide Square (Stop R1)"
        assert item["transfer_time_minutes"] == 4
        assert item["bidirectional"] is True
        assert item["step_free"] is True
        assert item["notes"] == "Exit via main forecourt"
        assert "created_at" in item

        # Update transfer
        updated = repo.update(
            trans_id,
            from_type="station",
            from_id="OXF",
            from_name="Oxford Station Central",
            to_type="bus_stop",
            to_id="340000001",
            to_name="Frideswide Square (Stop R1)",
            transfer_time_minutes=3,
            bidirectional=False,
            step_free=False,
            notes="",
        )
        assert updated is True
        item_updated = repo.get(trans_id)
        assert item_updated["from_name"] == "Oxford Station Central"
        assert item_updated["transfer_time_minutes"] == 3
        assert item_updated["bidirectional"] is False
        assert item_updated["step_free"] is False
        assert item_updated["notes"] == ""

        # Update non-existent transfer
        assert repo.update(888, "station", "A", "A", "bus_stop", "B", "B") is False

        # Get all transfers
        all_items = repo.get_all()
        assert len(all_items) == 1
        assert all_items[0]["id"] == trans_id

        # Delete transfer
        assert repo.delete(trans_id) is True
        assert repo.get(trans_id) is None
        assert repo.count() == 0
        assert repo.delete(999) is False


def test_location_transfer_repository_replace_all(app: Flask) -> None:
    """Test LocationTransferRepository replace_all replaces entire dataset."""
    with app.app_context():
        repo = LocationTransferRepository()
        repo.add(
            "station",
            "OLD",
            "Old Station",
            "bus_stop",
            "OLD_STOP",
            "Old Stop",
            5,
        )
        assert repo.count() == 1

        new_items = [
            {
                "from_type": "station",
                "from_id": "OXF",
                "from_name": "Oxford Station",
                "to_type": "bus_stop",
                "to_id": "340001",
                "to_name": "Frideswide Square",
                "transfer_time_minutes": 3,
                "bidirectional": True,
                "step_free": True,
                "notes": "Direct path",
            },
            {
                "from_type": "bus_stop",
                "from_id": "340002",
                "from_name": "Gloucester Green",
                "to_type": "station",
                "to_id": "OXF",
                "to_name": "Oxford Station",
                "transfer_time_minutes": 10,
                "bidirectional": False,
                "step_free": False,
                "notes": "Via George St",
            },
        ]

        repo.replace_all(new_items)
        all_items = repo.get_all()
        assert len(all_items) == 2
        assert all_items[0]["from_id"] == "OXF"
        assert all_items[1]["from_id"] == "340002"

        # Test replace_all with empty list
        repo.replace_all([])
        assert repo.count() == 0


def test_location_transfer_repository_clear(app: Flask) -> None:
    """Test LocationTransferRepository clear method."""
    with app.app_context():
        repo = LocationTransferRepository()
        repo.add("station", "A", "A", "bus_stop", "B", "B", 5)
        assert repo.count() == 1
        repo.clear()
        assert repo.count() == 0


def test_platform_transfer_repository_crud(app: Flask) -> None:
    """Test PlatformTransferRepository add, get, update, delete, and get_all."""
    with app.app_context():
        repo = PlatformTransferRepository()

        # Initial state should be empty
        assert repo.get_all() == []
        assert repo.get(999) is None
        assert repo.count() == 0

        # Add a platform transfer
        plat_id = repo.add(
            location_type="station",
            location_id="OXF",
            location_name="Oxford Rail Station",
            from_platform="Platform 1",
            to_platform="Platform 2",
            transfer_time_minutes=2,
            bidirectional=True,
            step_free=True,
            notes="Use footbridge lift",
        )
        assert plat_id > 0
        assert repo.count() == 1

        # Retrieve single transfer
        item = repo.get(plat_id)
        assert item is not None
        assert item["id"] == plat_id
        assert item["location_type"] == "station"
        assert item["location_id"] == "OXF"
        assert item["location_name"] == "Oxford Rail Station"
        assert item["from_platform"] == "Platform 1"
        assert item["to_platform"] == "Platform 2"
        assert item["transfer_time_minutes"] == 2
        assert item["bidirectional"] is True
        assert item["step_free"] is True
        assert item["notes"] == "Use footbridge lift"

        # Update platform transfer
        updated = repo.update(
            plat_id,
            location_type="station",
            location_id="OXF",
            location_name="Oxford Rail Station",
            from_platform="Platform 1",
            to_platform="Platform 2",
            transfer_time_minutes=1,
            bidirectional=False,
            step_free=False,
            notes="Direct cross-platform",
        )
        assert updated is True
        item_updated = repo.get(plat_id)
        assert item_updated["transfer_time_minutes"] == 1
        assert item_updated["bidirectional"] is False
        assert item_updated["step_free"] is False
        assert item_updated["notes"] == "Direct cross-platform"

        # Update non-existent transfer
        assert (
            repo.update(888, "station", "OXF", "Oxford", "Platform 1", "Platform 2")
            is False
        )

        # Get all platform transfers
        all_items = repo.get_all()
        assert len(all_items) == 1
        assert all_items[0]["id"] == plat_id

        # Delete transfer
        assert repo.delete(plat_id) is True
        assert repo.get(plat_id) is None
        assert repo.count() == 0
        assert repo.delete(999) is False


def test_platform_transfer_repository_replace_all(app: Flask) -> None:
    """Test PlatformTransferRepository replace_all replaces entire dataset."""
    with app.app_context():
        repo = PlatformTransferRepository()
        repo.add(
            "station",
            "OLD",
            "Old Stn",
            "Plat 1",
            "Plat 2",
            3,
        )
        assert repo.count() == 1

        new_items = [
            {
                "location_type": "station",
                "location_id": "PAD",
                "location_name": "London Paddington",
                "from_platform": "Platform 1",
                "to_platform": "Platform 8",
                "transfer_time_minutes": 4,
                "bidirectional": True,
                "step_free": True,
                "notes": "Main concourse walkway",
            },
            {
                "location_type": "bus_stop",
                "location_id": "340002",
                "location_name": "Gloucester Green",
                "from_platform": "Stand 1",
                "to_platform": "Stand 5",
                "transfer_time_minutes": 1,
                "bidirectional": True,
                "step_free": True,
                "notes": "Direct island",
            },
        ]

        repo.replace_all(new_items)
        all_items = repo.get_all()
        assert len(all_items) == 2
        assert all_items[0]["location_id"] == "PAD"
        assert all_items[1]["location_id"] == "340002"

        # Test replace_all with empty list
        repo.replace_all([])
        assert repo.count() == 0


def test_platform_transfer_repository_clear(app: Flask) -> None:
    """Test PlatformTransferRepository clear method."""
    with app.app_context():
        repo = PlatformTransferRepository()
        repo.add("station", "OXF", "Oxford", "P1", "P2", 2)
        assert repo.count() == 1
        repo.clear()
        assert repo.count() == 0


def test_transfer_repository_orchestration(app: Flask) -> None:
    """Test TransferRepository orchestrating both location and platform transfers."""
    with app.app_context():
        repo = TransferRepository()

        # Both sub-repositories should initialise and be accessible
        assert repo.get_all_location_transfers() == []
        assert repo.get_all_platform_transfers() == []

        loc_data = [
            {
                "from_type": "station",
                "from_id": "OXF",
                "from_name": "Oxford Station",
                "to_type": "bus_stop",
                "to_id": "340001",
                "to_name": "Frideswide Square",
                "transfer_time_minutes": 5,
                "bidirectional": True,
                "step_free": True,
                "notes": "Walk",
            }
        ]

        plat_data = [
            {
                "location_type": "station",
                "location_id": "OXF",
                "location_name": "Oxford Station",
                "from_platform": "Platform 1",
                "to_platform": "Platform 2",
                "transfer_time_minutes": 2,
                "bidirectional": True,
                "step_free": False,
                "notes": "Bridge",
            }
        ]

        repo.replace_all(loc_data, plat_data)
        combined = repo.get_all()
        assert len(combined["location_transfers"]) == 1
        assert len(combined["platform_transfers"]) == 1
        assert combined["location_transfers"][0]["from_id"] == "OXF"
        assert combined["platform_transfers"][0]["location_id"] == "OXF"


# --- View & HTTP Endpoint Tests ---


def test_get_transfers_page_initial_empty(client: FlaskClient) -> None:
    """Test GET /config/transfers renders both Grid.js tables with empty states."""
    response = client.get("/config/transfers")
    assert response.status_code == 200
    assert b"Inter-Location Transfers" in response.data
    assert b"Platform &amp; Stand Transfers" in response.data
    assert b'id="location-transfers-grid-wrapper"' in response.data
    assert b'id="platform-transfers-grid-wrapper"' in response.data
    assert b'id="location-transfer-modal"' in response.data
    assert b'id="platform-transfer-modal"' in response.data
    assert b'id="nav-link-transfers"' in response.data


def test_post_transfers_saves_and_redirects(client: FlaskClient, app: Flask) -> None:
    """Test POST /config/transfers saves valid transfers and performs PRG redirect."""
    loc_payload = [
        {
            "from_type": "station",
            "from_id": "OXF",
            "from_name": "Oxford Rail Station",
            "to_type": "bus_stop",
            "to_id": "340000001",
            "to_name": "Frideswide Square (Stop R1)",
            "transfer_time_minutes": 4,
            "bidirectional": True,
            "step_free": True,
            "notes": "Pelican crossing",
        }
    ]

    plat_payload = [
        {
            "location_type": "station",
            "location_id": "OXF",
            "location_name": "Oxford Rail Station",
            "from_platform": "Platform 1",
            "to_platform": "Platform 2",
            "transfer_time_minutes": 2,
            "bidirectional": True,
            "step_free": False,
            "notes": "North footbridge",
        }
    ]

    response = client.post(
        "/config/transfers",
        data={
            "location_transfers_json": json.dumps(loc_payload),
            "platform_transfers_json": json.dumps(plat_payload),
        },
    )

    # 303 PRG redirect
    assert response.status_code == 303
    assert response.headers["Location"].endswith("/config/transfers")

    with app.app_context():
        repo = TransferRepository()
        all_locs = repo.get_all_location_transfers()
        all_plats = repo.get_all_platform_transfers()
        assert len(all_locs) == 1
        assert all_locs[0]["from_id"] == "OXF"
        assert all_locs[0]["to_id"] == "340000001"
        assert all_locs[0]["transfer_time_minutes"] == 4
        assert all_locs[0]["bidirectional"] is True

        assert len(all_plats) == 1
        assert all_plats[0]["location_id"] == "OXF"
        assert all_plats[0]["from_platform"] == "Platform 1"
        assert all_plats[0]["to_platform"] == "Platform 2"

    # Follow redirect to verify flash message
    follow_res = client.get("/config/transfers")
    assert follow_res.status_code == 200
    assert b"Transfers saved successfully." in follow_res.data


def test_post_transfers_invalid_json(client: FlaskClient) -> None:
    """Test POST /config/transfers handles invalid JSON gracefully."""
    response = client.post(
        "/config/transfers",
        data={
            "location_transfers_json": "INVALID_JSON",
            "platform_transfers_json": "[]",
        },
    )
    assert response.status_code == 303
    follow_res = client.get("/config/transfers")
    assert b"Failed to save transfers:" in follow_res.data


def test_post_transfers_non_list_json(client: FlaskClient) -> None:
    """Test POST /config/transfers handles non-list JSON payload."""
    response = client.post(
        "/config/transfers",
        data={
            "location_transfers_json": '{"key": "value"}',
            "platform_transfers_json": "[]",
        },
    )
    assert response.status_code == 303
    follow_res = client.get("/config/transfers")
    assert b"Failed to save transfers:" in follow_res.data


def test_post_transfers_sanitisation_and_defaults(
    client: FlaskClient, app: Flask
) -> None:
    """Test POST /config/transfers sanitises types and sets default transfer times."""
    loc_payload = [
        {
            "from_type": "invalid_mode",  # should default to station
            "from_id": "PAD",
            "from_name": "London Paddington",
            "to_type": "invalid_mode",  # should default to bus_stop
            "to_id": "490001",
            "to_name": "Paddington Station (Stop H)",
            "transfer_time_minutes": "not_a_number",  # should default to 5
            "bidirectional": 1,
            "step_free": 0,
            "notes": None,
        },
        "not_a_dict_entry",  # should be ignored
    ]

    plat_payload = [
        {
            "location_type": "invalid_type",  # should default to station
            "location_id": "PAD",
            "location_name": "London Paddington",
            "from_platform": "Platform 1",
            "to_platform": "Platform 2",
            "transfer_time_minutes": "invalid",  # should default to 2
            "bidirectional": False,
            "step_free": True,
        },
        123,  # should be ignored
    ]

    response = client.post(
        "/config/transfers",
        data={
            "location_transfers_json": json.dumps(loc_payload),
            "platform_transfers_json": json.dumps(plat_payload),
        },
    )
    assert response.status_code == 303

    with app.app_context():
        repo = TransferRepository()
        locs = repo.get_all_location_transfers()
        plats = repo.get_all_platform_transfers()
        assert len(locs) == 1
        assert locs[0]["from_type"] == "station"
        assert locs[0]["to_type"] == "bus_stop"
        assert locs[0]["transfer_time_minutes"] == 5

        assert len(plats) == 1
        assert plats[0]["location_type"] == "station"
        assert plats[0]["transfer_time_minutes"] == 2
        assert plats[0]["bidirectional"] is False
        assert plats[0]["step_free"] is True


def test_search_transfers_locations_all(client: FlaskClient, app: Flask) -> None:
    """Test GET /config/transfers/search returns empty when unpopulated and records when cached."""
    # 1. Unpopulated test
    response_empty = client.get("/config/transfers/search")
    assert response_empty.status_code == 200
    data_empty = response_empty.get_json()
    assert data_empty["total"] == 0
    assert data_empty["results"] == []

    # 2. Populated test
    with app.app_context():
        StationRepository().bulk_upsert(
            [{"crs_code": "PAD", "name": "London Paddington"}]
        )
        BusStopRepository().bulk_upsert(
            [{"atco_code": "490000001", "name": "Victoria Coach Station"}]
        )

    response = client.get("/config/transfers/search")
    assert response.status_code == 200
    data = response.get_json()
    assert "results" in data
    assert "total" in data
    assert data["total"] == 2
    types = [item["type"] for item in data["results"]]
    assert "station" in types and "bus_stop" in types


def test_search_transfers_locations_station_filter(
    client: FlaskClient, app: Flask
) -> None:
    """Test GET /config/transfers/search with type=station filter."""
    with app.app_context():
        StationRepository().bulk_upsert(
            [{"crs_code": "PAD", "name": "London Paddington"}]
        )
        BusStopRepository().bulk_upsert(
            [{"atco_code": "490000001", "name": "Victoria Coach Station"}]
        )

    response = client.get("/config/transfers/search?type=station")
    assert response.status_code == 200
    data = response.get_json()
    assert data["total"] == 1
    for item in data["results"]:
        assert item["type"] == "station"


def test_search_transfers_locations_bus_stop_filter(
    client: FlaskClient, app: Flask
) -> None:
    """Test GET /config/transfers/search with type=bus_stop filter."""
    with app.app_context():
        StationRepository().bulk_upsert(
            [{"crs_code": "PAD", "name": "London Paddington"}]
        )
        BusStopRepository().bulk_upsert(
            [{"atco_code": "490000001", "name": "Victoria Coach Station"}]
        )

    response = client.get("/config/transfers/search?type=bus_stop")
    assert response.status_code == 200
    data = response.get_json()
    assert data["total"] == 1
    for item in data["results"]:
        assert item["type"] == "bus_stop"


def test_search_transfers_locations_query(client: FlaskClient, app: Flask) -> None:
    """Test GET /config/transfers/search with matching and non-matching queries."""
    with app.app_context():
        StationRepository().bulk_upsert(
            [{"crs_code": "OXF", "name": "Oxford Rail Station"}]
        )

    res_match = client.get("/config/transfers/search?q=Oxford")
    assert res_match.status_code == 200
    data = res_match.get_json()
    assert data["total"] > 0
    assert any("Oxford" in item["name"] for item in data["results"])

    res_nomatch = client.get("/config/transfers/search?q=NonExistentLocXYZ999")
    assert res_nomatch.status_code == 200
    data_no = res_nomatch.get_json()
    assert data_no["total"] == 0


def test_search_transfers_locations_with_db_records(
    client: FlaskClient, app: Flask
) -> None:
    """Test GET /config/transfers/search queries SQLite database records when populated."""
    with app.app_context():
        stn_repo = StationRepository()
        stn_repo.bulk_upsert(
            [
                {
                    "crs_code": "CDF",
                    "name": "Cardiff Central",
                    "operator": "Transport for Wales",
                },
                {
                    "crs_code": "OXF",
                    "name": "Oxford Rail Station",
                    "operator": "GWR",
                },
            ]
        )

        stop_repo = BusStopRepository()
        stop_repo.bulk_upsert(
            [
                {
                    "atco_code": "520000001",
                    "name": "Cardiff Bay Millennium Centre",
                    "indicator": "Bay A",
                    "locality": "Cardiff",
                }
            ]
        )

    res = client.get("/config/transfers/search?q=Cardiff")
    assert res.status_code == 200
    data = res.get_json()
    assert data["total"] >= 2
    names = [item["name"] for item in data["results"]]
    assert any("Cardiff Central" in n for n in names)
    assert any("Cardiff Bay" in n for n in names)

    res_oxf = client.get("/config/transfers/search?q=OXF")
    assert res_oxf.status_code == 200
    data_oxf = res_oxf.get_json()
    assert data_oxf["total"] >= 1
    assert any(item["id"] == "OXF" for item in data_oxf["results"])


def test_search_transfers_locations_db_exception_fallback(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test GET /config/transfers/search falls back gracefully if SQLite raises an exception."""
    mock_conn = MagicMock()
    mock_conn.cursor.side_effect = Exception("Simulated DB connection error")

    monkeypatch.setattr(
        "app.views.config.StationRepository.conn",
        property(lambda self: mock_conn),
    )
    monkeypatch.setattr(
        "app.views.config.BusStopRepository.conn",
        property(lambda self: mock_conn),
    )

    response = client.get("/config/transfers/search?q=London")
    assert response.status_code == 200
    data = response.get_json()
    assert data["total"] == 0
    assert data["results"] == []
