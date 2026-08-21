"""Unit tests for Journeys configuration page, SQLite model, and location search."""

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
            from_type="custom",
            from_id=str(sample_custom_location.id),
            from_name=sample_custom_location.name,
            to_type="rail",
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
            from_type="rail",
            from_id="WAT",
            from_name="London Waterloo",
            to_type="rail",
            to_id="LGW",
            to_name="Gatwick Airport",
            time_settings="[]",
        )
        Journey.create(
            name="Weekend Trip",
            from_type="rail",
            from_id="WAT",
            from_name="London Waterloo",
            to_type="rail",
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
            "from_type": "custom",
            "from_id": "1",
            "from_name": "Home",
            "to_type": "rail",
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
            "from_type": "rail",
            "from_id": "WAT",
            "from_name": "London Waterloo",
            "to_type": "custom",
            "to_id": "1",
            "to_name": "Home",
            "time_settings": [],
        },
    ]

    response = client.post(
        "/config/journeys/data",
        json={"added": payload, "updated": [], "deleted": []},
    )
    assert response.status_code == 200
    res_data = response.get_json()
    assert res_data["success"] is True
    assert res_data["stats"]["added"] == 2

    # Verify POST to HTML page URL returns 405 Method Not Allowed
    page_post_resp = client.post("/config/journeys")
    assert page_post_resp.status_code == 405

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
    """Test POST /config/journeys/data gracefully handles invalid JSON."""
    response = client.post(
        "/config/journeys/data",
        data="invalid-non-json",
        content_type="application/json",
    )
    assert response.status_code == 400
    res_data = response.get_json()
    assert res_data["success"] is False
    assert "Invalid JSON body" in res_data["message"]


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
        item["type"] == "rail"
        and item["icon"] == "train"
        and item["id"] == "naptan:WAT"
        for item in data["results"]
    )

    # Test bus stop search
    response_bus = client.get("/config/search/places?q=Euston&type=bus")
    assert response_bus.status_code == 200
    data_bus = response_bus.get_json()
    assert len(data_bus["results"]) >= 1
    assert data_bus["results"][0]["icon"] == "directions_bus"
    assert data_bus["results"][0]["indicator"] == "Stop E"
    assert data_bus["results"][0]["id"] == "atco:490000077E"

    # Test custom location search
    response_custom = client.get("/config/search/places?q=Home&type=custom")
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
            from_type="rail",
            from_id="WAT",
            from_name="Waterloo",
            to_type="rail",
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


def test_journey_save_leave_and_return_persistence(client: FlaskClient) -> None:
    """Verify that saving a new journey persists across navigation away and returning."""
    # 1. Create a new journey
    new_journey_payload = [
        {
            "name": "Gym Workout Route",
            "from_type": "ha",
            "from_id": "ha:home",
            "from_name": "Home",
            "to_type": "ha",
            "to_id": "ha:gym",
            "to_name": "City Health Club",
            "time_settings": [
                {
                    "days": ["mon", "wed", "fri"],
                    "mode": "arrive",
                    "start_time": "06:45",
                    "end_time": "07:15",
                }
            ],
        }
    ]

    # POST Save Changes
    save_resp = client.post(
        "/config/journeys/data",
        json={"added": new_journey_payload, "updated": [], "deleted": []},
    )
    assert save_resp.status_code == 200
    assert save_resp.get_json()["success"] is True

    # 2. Leave the page (navigate to Locations & Timetables)
    loc_resp = client.get("/config/locations")
    assert loc_resp.status_code == 200

    tt_resp = client.get("/config/timetables")
    assert tt_resp.status_code == 200

    # 3. Return to Journeys page
    return_resp = client.get("/config/journeys")
    assert return_resp.status_code == 200

    # 4. Verify data available via /data endpoint
    data_resp = client.get("/config/journeys/data")
    assert data_resp.status_code == 200

    persisted_journeys = data_resp.get_json()["data"]
    assert len(persisted_journeys) == 1
    item = persisted_journeys[0]
    assert item["name"] == "Gym Workout Route"
    assert item["from_id"] == "ha:home"
    assert item["to_id"] == "ha:gym"
    assert len(item["time_settings"]) == 1
    assert item["time_settings"][0]["mode"] == "arrive"
    assert item["time_settings"][0]["days"] == ["mon", "wed", "fri"]
    assert item["time_settings"][0]["start_time"] == "06:45"
    assert item["time_settings"][0]["end_time"] == "07:15"


def test_journey_edit_and_delete_persistence(client: FlaskClient) -> None:
    """Verify editing and deleting existing journeys persists properly."""
    # Seed 2 journeys
    initial_payload = {
        "added": [
            {
                "name": "Library Study Session",
                "from_type": "ha",
                "from_id": "ha:home",
                "from_name": "Home",
                "to_type": "custom",
                "to_id": "custom:library",
                "to_name": "Central Public Library",
                "time_settings": [],
            },
            {
                "name": "Weekend Family Visit",
                "from_type": "ha",
                "from_id": "ha:home",
                "from_name": "Home",
                "to_type": "custom",
                "to_id": "custom:parents",
                "to_name": "Parents House",
                "time_settings": [],
            },
        ],
        "updated": [],
        "deleted": [],
    }

    client.post(
        "/config/journeys/data",
        json=initial_payload,
    )

    from app.models import Journey

    journeys = list(Journey.select())
    assert len(journeys) == 2
    lib_journey = next(j for j in journeys if "Library" in j.name)
    fam_journey = next(j for j in journeys if "Family" in j.name)

    # Edit Library Study Session -> Central Library Research Session and Delete Weekend Family Visit
    updated_payload = {
        "added": [],
        "updated": [
            {
                "id": lib_journey.id,
                "name": "Central Library Research Session",
                "from_type": "ha",
                "from_id": "ha:home",
                "from_name": "Home",
                "to_type": "custom",
                "to_id": "custom:library",
                "to_name": "Central Public Library",
                "time_settings": [
                    {
                        "days": ["sat"],
                        "mode": "depart",
                        "start_time": "10:00",
                        "end_time": "11:00",
                    }
                ],
            }
        ],
        "deleted": [fam_journey.id],
    }

    save_resp = client.post(
        "/config/journeys/data",
        json=updated_payload,
    )
    assert save_resp.status_code == 200

    # Return to Journeys and verify
    client.get("/config/journeys")
    data_resp = client.get("/config/journeys/data")
    assert data_resp.status_code == 200
    persisted = data_resp.get_json()["data"]

    assert len(persisted) == 1
    assert persisted[0]["name"] == "Central Library Research Session"
    assert persisted[0]["time_settings"][0]["days"] == ["sat"]


def test_config_journeys_data_endpoint(app: Flask, client: FlaskClient) -> None:
    """Test GET /config/journeys/data returns all journeys as JSON."""
    # Seed a journey
    with app.app_context():
        Journey.delete().execute()
        Journey.insert_many(
            [
                {
                    "name": "Data Endpoint Test Journey",
                    "from_type": "ha",
                    "from_id": "ha:home",
                    "from_name": "Home",
                    "to_type": "rail",
                    "to_id": "WAT",
                    "to_name": "London Waterloo",
                    "time_settings": [],
                }
            ]
        ).execute()

    response = client.get("/config/journeys/data")
    assert response.status_code == 200
    assert response.content_type.startswith("application/json")
    payload = response.get_json()
    assert "data" in payload
    assert "total" in payload
    assert payload["total"] == 1
    assert payload["data"][0]["name"] == "Data Endpoint Test Journey"
    assert payload["data"][0]["from_id"] == "ha:home"


def test_config_journeys_pagination_and_sorting(
    app: Flask, client: FlaskClient
) -> None:
    """Test server-side pagination and sorting query parameters on /config/journeys/data."""
    with app.app_context():
        Journey.delete().execute()
        for i in range(12):
            Journey.create(
                name=f"Journey {chr(65 + i)}",
                from_type="rail",
                from_id=f"STN{i}",
                from_name=f"Station {chr(65 + i)}",
                to_type="rail",
                to_id="WAT",
                to_name="Waterloo",
                time_settings=[],
            )

    # Test limit and offset
    resp_p1 = client.get("/config/journeys/data?limit=4&offset=0")
    assert resp_p1.status_code == 200
    data_p1 = resp_p1.get_json()
    assert data_p1["total"] == 12
    assert len(data_p1["data"]) == 4
    assert data_p1["data"][0]["name"] == "Journey A"

    # Test sorting descending
    resp_desc = client.get("/config/journeys/data?limit=4&sort_by=name&order=desc")
    assert resp_desc.status_code == 200
    data_desc = resp_desc.get_json()
    assert data_desc["data"][0]["name"] == "Journey L"
