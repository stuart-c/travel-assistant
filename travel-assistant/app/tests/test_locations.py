"""Unit tests for Locations configuration page, Peewee model, and map integration."""

from flask import Flask
from flask.testing import FlaskClient

from app.db import get_db_stats
from app.models import Location, SyncMetadata


def test_location_model_crud(app: Flask) -> None:
    """Test Location model create, get, update, delete, search, and stats."""
    with app.app_context():
        assert list(Location.select()) == []
        assert Location.select().count() == 0

        # Create locations
        loc1 = Location.create(
            id="ha:home",
            name="Home",
            latitude=51.7520,
            longitude=-1.2577,
            ha=True,
        )
        loc2 = Location.create(
            name="Workplace",
            latitude=51.5074,
            longitude=-0.1278,
            ha=False,
        )

        assert loc1.id == "ha:home"
        assert loc2.id.startswith("custom:")
        assert len(loc2.id) > 7
        assert loc1.ha is True
        assert loc2.ha is False
        assert Location.select().count() == 2

        # Get by ID and check dict representation
        retrieved = Location.get_by_id(loc1.id)
        assert retrieved.name == "Home"
        assert retrieved.latitude == 51.7520
        assert retrieved.longitude == -1.2577
        assert retrieved.ha is True

        loc_dict = retrieved.to_dict()
        assert loc_dict["id"] == "ha:home"
        assert loc_dict["name"] == "Home"
        assert loc_dict["latitude"] == 51.7520
        assert loc_dict["longitude"] == -1.2577
        assert loc_dict["ha"] is True
        assert "created_at" in loc_dict
        assert "updated_at" in loc_dict

        # Update
        retrieved.name = "Home Sweet Home"
        retrieved.save()
        assert Location.get_by_id(loc1.id).name == "Home Sweet Home"

        # Search by name
        search_res = Location.search("Home")
        assert len(search_res) == 1
        assert search_res[0].name == "Home Sweet Home"

        # Search by ID
        search_by_id = Location.search("ha:home")
        assert len(search_by_id) == 1
        assert search_by_id[0].id == "ha:home"

        search_empty = Location.search("NonExistent")
        assert len(search_empty) == 0

        search_all = Location.search("")
        assert len(search_all) == 2

        # Stats
        stats = Location.get_stats()
        assert stats["total"] == 2
        assert stats["ha_count"] == 1
        assert stats["manual_count"] == 1

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
    assert b"locations-grid-wrapper" in response_populated.data

    data_resp = client.get("/config/locations/data")
    assert data_resp.status_code == 200
    names = [loc["name"] for loc in data_resp.get_json()["data"]]
    assert "Oxford Town Hall" in names


def test_post_locations_success(client: FlaskClient, app: Flask) -> None:
    """Test POST /config/locations saves locations atomically and performs PRG redirect."""
    with app.app_context():
        Location.create(name="Existing Location", latitude=50.0, longitude=0.0)
        assert Location.select().count() == 1

    payload = {
        "added": [
            {"name": "London Eye", "latitude": 51.5033, "longitude": -0.1195},
            {"name": "Big Ben", "latitude": "51.5007", "longitude": "-0.1246"},
        ],
        "updated": [],
        "deleted": [],
    }

    response = client.post(
        "/config/locations/data",
        json=payload,
    )

    assert response.status_code == 200
    res_data = response.get_json()
    assert res_data["success"] is True
    assert res_data["stats"]["added"] == 2

    # Verify POST to HTML page URL returns 405 Method Not Allowed
    page_post_resp = client.post("/config/locations")
    assert page_post_resp.status_code == 405

    with app.app_context():
        saved = list(Location.select())
        assert len(saved) == 3
        names = [s.name for s in saved]
        assert "London Eye" in names
        assert "Big Ben" in names
        assert "Existing Location" in names


def test_post_locations_empty_changeset_leaves_records(
    client: FlaskClient, app: Flask
) -> None:
    """Test POST /config/locations/data with empty changeset preserves existing records."""
    with app.app_context():
        Location.create(name="Temporary Place", latitude=51.5, longitude=-0.1, ha=False)
        assert Location.select().count() == 1

    response = client.post(
        "/config/locations/data",
        json={"added": [], "updated": [], "deleted": []},
    )

    assert response.status_code == 200
    assert response.get_json()["success"] is True

    with app.app_context():
        assert Location.select().count() == 1


def test_post_locations_differential_updates(client: FlaskClient, app: Flask) -> None:
    """Test POST /config/locations/data updates only changed rows and preserves timestamps."""
    with app.app_context():
        loc1 = Location.create(
            name="Unchanged Loc", latitude=51.1, longitude=0.1, ha=False
        )
        loc2 = Location.create(name="To Update", latitude=51.2, longitude=0.2, ha=False)
        loc3 = Location.create(name="To Delete", latitude=51.3, longitude=0.3, ha=False)

    payload = {
        "added": [{"name": "Brand New", "latitude": 51.4, "longitude": 0.4}],
        "updated": [
            {"id": loc2.id, "name": "Updated Name", "latitude": 51.25, "longitude": 0.2}
        ],
        "deleted": [loc3.id],
    }

    response = client.post(
        "/config/locations/data",
        json=payload,
    )
    assert response.status_code == 200
    assert response.get_json()["success"] is True

    with app.app_context():
        saved = {loc_item.id: loc_item for loc_item in Location.select()}
        assert loc3.id not in saved
        assert loc1.id in saved
        assert saved[loc1.id].name == "Unchanged Loc"
        assert saved[loc1.id].updated_at == loc1.updated_at
        assert loc2.id in saved
        assert saved[loc2.id].name == "Updated Name"
        assert saved[loc2.id].latitude == 51.25


def test_post_locations_preserves_ha_records(client: FlaskClient, app: Flask) -> None:
    """Test POST /config/locations preserves existing HA records even if omitted."""
    with app.app_context():
        ha_loc = Location.create(
            name="HA Home", latitude=51.7520, longitude=-1.2577, ha=True
        )
        man_loc = Location.create(
            name="Manual Place", latitude=51.5, longitude=-0.1, ha=False
        )
        assert Location.select().count() == 2

    # Attempt to delete HA record and manual record via changeset
    payload = {
        "added": [
            {
                "name": "New Manual Place",
                "latitude": 52.0,
                "longitude": 0.0,
                "ha": False,
            }
        ],
        "updated": [],
        "deleted": [ha_loc.id, man_loc.id],
    }

    response = client.post(
        "/config/locations/data",
        json=payload,
    )

    assert response.status_code == 200
    assert response.get_json()["success"] is True

    with app.app_context():
        saved = list(Location.select())
        assert len(saved) == 2
        names = {s.name: s for s in saved}
        assert "HA Home" in names
        assert names["HA Home"].ha is True
        assert names["HA Home"].latitude == 51.7520
        assert "New Manual Place" in names
        assert names["New Manual Place"].ha is False
        assert "Manual Place" not in names


def test_post_locations_invalid_json(client: FlaskClient) -> None:
    """Test POST /config/locations/data with invalid JSON returns 400 error."""
    response = client.post(
        "/config/locations/data",
        data="invalid-json-{",
        content_type="application/json",
    )
    assert response.status_code == 400
    assert response.get_json()["success"] is False


def test_post_locations_invalid_payload_shape(client: FlaskClient) -> None:
    """Test POST /config/locations/data with a non-changeset JSON payload returns 400 error."""
    response = client.post(
        "/config/locations/data",
        json={"name": "Solo Object"},
    )
    assert response.status_code == 400
    assert response.get_json()["success"] is False


def test_post_locations_skips_invalid_entries(client: FlaskClient, app: Flask) -> None:
    """Test POST /config/locations/data skips entries with missing name or invalid coordinates."""
    payload = {
        "added": [
            "not-a-dict",
            {"name": "", "latitude": 51.5, "longitude": -0.1},  # missing name
            {"name": "Missing Lat", "longitude": -0.1},  # missing lat
            {"name": "Missing Lon", "latitude": 51.5},  # missing lon
            {
                "name": "Bad Lat Str",
                "latitude": "invalid",
                "longitude": -0.1,
            },  # bad lat
            {
                "name": "Bad Lon Str",
                "latitude": 51.5,
                "longitude": "invalid",
            },  # bad lon
            {
                "name": "Lat Out of Range",
                "latitude": 95.0,
                "longitude": -0.1,
            },  # lat > 90
            {
                "name": "Lat Neg Range",
                "latitude": -95.0,
                "longitude": -0.1,
            },  # lat < -90
            {
                "name": "Lon Out of Range",
                "latitude": 51.5,
                "longitude": 185.0,
            },  # lon > 180
            {
                "name": "Lon Neg Range",
                "latitude": 51.5,
                "longitude": -185.0,
            },  # lon < -180
            {"name": "Valid Place", "latitude": 51.7520, "longitude": -1.2577},  # valid
        ],
        "updated": [],
        "deleted": [],
    }

    response = client.post(
        "/config/locations/data",
        json=payload,
    )

    assert response.status_code == 200
    assert response.get_json()["success"] is True

    with app.app_context():
        saved = list(Location.select())
        assert len(saved) == 1
        assert saved[0].name == "Valid Place"
        assert saved[0].latitude == 51.7520
        assert saved[0].longitude == -1.2577


def test_db_stats_includes_locations(app: Flask) -> None:
    """Test get_db_stats inspects and reports records for locations table and marks it syncable."""
    with app.app_context():
        Location.create(name="Stats Location 1", latitude=51.5, longitude=-0.1)
        Location.create(name="Stats Location 2", latitude=51.6, longitude=-0.2)
        SyncMetadata.record_success("ha_locations", 2, 0.25)

        stats = get_db_stats(app)
        assert "tables" in stats
        loc_table = next((t for t in stats["tables"] if t["name"] == "locations"), None)
        assert loc_table is not None
        assert loc_table["row_count"] == 2
        assert loc_table["syncable"] is True
        assert loc_table["sync_status"] == "success"
        assert loc_table["last_updated_at"] is not None


def test_location_save_leave_and_return_persistence(
    client: FlaskClient, app: Flask
) -> None:
    """Verify that saving a location persists across leaving and returning to the page."""
    with app.app_context():
        Location.create(
            id="ha:home",
            name="Home",
            latitude=51.5300,
            longitude=-0.1200,
            ha=True,
        )

    # 1. Save new custom location
    new_locations = {
        "added": [
            {
                "name": "St Pancras International Library",
                "latitude": 51.5310,
                "longitude": -0.1260,
                "ha": False,
            }
        ],
        "updated": [],
        "deleted": [],
    }
    post_resp = client.post(
        "/config/locations/data",
        json=new_locations,
    )
    assert post_resp.status_code == 200
    assert post_resp.get_json()["success"] is True

    # 2. Leave the page (visit Overview, Journeys, Credentials)
    assert client.get("/").status_code == 200
    assert client.get("/config/journeys").status_code == 200
    assert client.get("/config/credentials").status_code == 200

    # 3. Return to Locations page
    return_resp = client.get("/config/locations")
    assert return_resp.status_code == 200

    # Verify data available via /config/locations/data endpoint
    data_resp = client.get("/config/locations/data")
    assert data_resp.status_code == 200
    persisted = data_resp.get_json()["data"]

    assert len(persisted) == 2
    ha_loc = next((loc for loc in persisted if loc.get("ha")), None)
    custom_loc = next((loc for loc in persisted if not loc.get("ha")), None)

    assert ha_loc is not None
    assert ha_loc["name"] == "Home"
    assert ha_loc["id"] == "ha:home"

    assert custom_loc is not None
    assert custom_loc["name"] == "St Pancras International Library"
    assert custom_loc["latitude"] == 51.5310
    assert custom_loc["longitude"] == -0.1260


def test_config_locations_data_endpoint(app: Flask, client: FlaskClient) -> None:
    """Test GET /config/locations/data returns all locations as JSON."""
    with app.app_context():
        Location.delete().execute()
        Location.insert_many(
            [
                {
                    "id": "custom:test1",
                    "name": "Test Location",
                    "latitude": 51.5,
                    "longitude": -0.1,
                    "ha": False,
                },
            ]
        ).execute()

    response = client.get("/config/locations/data")
    assert response.status_code == 200
    assert response.content_type.startswith("application/json")
    payload = response.get_json()
    assert "data" in payload
    assert "total" in payload
    assert payload["total"] == 1
    assert payload["data"][0]["name"] == "Test Location"


def test_config_locations_pagination_and_sorting(
    app: Flask, client: FlaskClient
) -> None:
    """Test server-side pagination and sorting query parameters on /config/locations/data."""
    with app.app_context():
        Location.delete().execute()
        for i in range(15):
            Location.create(
                id=f"custom:loc{i:02d}",
                name=f"Location {chr(65 + i)}",  # Location A, B, C, ...
                latitude=50.0 + (i * 0.1),
                longitude=0.0,
                ha=False,
            )

    # Test limit and offset
    resp_p1 = client.get("/config/locations/data?limit=5&offset=0")
    assert resp_p1.status_code == 200
    data_p1 = resp_p1.get_json()
    assert data_p1["total"] == 15
    assert len(data_p1["data"]) == 5
    assert data_p1["data"][0]["name"] == "Location A"
    assert data_p1["data"][4]["name"] == "Location E"

    # Test page parameter (page 1 with limit 5 -> offset 5)
    resp_p2 = client.get("/config/locations/data?limit=5&page=1")
    assert resp_p2.status_code == 200
    data_p2 = resp_p2.get_json()
    assert data_p2["total"] == 15
    assert len(data_p2["data"]) == 5
    assert data_p2["data"][0]["name"] == "Location F"

    # Test sorting descending
    resp_desc = client.get("/config/locations/data?limit=5&sort_by=name&order=desc")
    assert resp_desc.status_code == 200
    data_desc = resp_desc.get_json()
    assert data_desc["data"][0]["name"] == "Location O"

    # Test invalid sort field gracefully ignored
    resp_inv = client.get("/config/locations/data?limit=5&sort_by=invalid_field")
    assert resp_inv.status_code == 200
    assert len(resp_inv.get_json()["data"]) == 5
