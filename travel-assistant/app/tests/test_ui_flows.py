"""Comprehensive UI flow, DOM structure, and Ingress integration unit tests."""

import json
import re
from bs4 import BeautifulSoup
from flask.testing import FlaskClient

from app.models import (
    Journey,
    Location,
    PlatformTransfer,
    Timetable,
    Walking,
)


def _seed_sample_data() -> None:
    """Helper to populate isolated test database with sample transit records."""
    Location.create(
        id="zone.home",
        name="Home Zone",
        latitude=51.5300,
        longitude=-0.1200,
        ha=True,
    )
    Location.create(
        id="custom:office",
        name="City Office",
        latitude=51.5150,
        longitude=-0.0900,
        ha=False,
    )

    tt = Timetable.create(
        name="Weekday Morning",
        transport_type="rail",
        monday=True,
        tuesday=True,
        wednesday=True,
        thursday=True,
        friday=True,
        saturday=False,
        sunday=False,
    )
    tt.set_content({"stops": ["9100KNGX"], "trips": [{"time": "08:00"}]})
    tt.save()

    PlatformTransfer.create(
        location_type="rail",
        location_id="9100KNGX",
        location_name="London King's Cross",
        from_platform="1",
        to_platform="8",
        transfer_time_minutes=4,
        bidirectional=True,
        step_free=True,
    )

    j = Journey.create(
        name="Office Commute",
        from_type="ha",
        from_id="zone.home",
        from_name="Home Zone",
        to_type="custom",
        to_id="custom:office",
        to_name="City Office",
    )
    j.set_time_settings([{"target_arrival": "09:00"}])
    j.save()

    Walking.create(
        start_type="ha",
        start_id="zone.home",
        start_name="Home Zone",
        finish_type="bus",
        finish_id="490000077E",
        finish_name="King's Cross Stop E",
        time_needed_minutes=5,
        bidirectional=True,
    )


def test_dashboard_and_navigation(client: FlaskClient) -> None:
    """Test dashboard root view and navigation header links."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    soup = BeautifulSoup(html, "html.parser")
    assert soup.title is not None
    assert "Overview" in soup.title.string
    assert "Travel Assistant" in html


def test_ingress_path_header_injection(client: FlaskClient) -> None:
    """Verify that X-Ingress-Path is injected into relative URLs and asset paths."""
    ingress_prefix = "/api/hassio_ingress/token123"
    response = client.get(
        "/config/credentials",
        headers={"X-Ingress-Path": ingress_prefix},
    )
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert f'action="{ingress_prefix}/config/credentials"' in html
    assert f'href="{ingress_prefix}/static/css/tables.css' in html


def test_places_search_autocomplete_api(client: FlaskClient) -> None:
    """Test /config/search/places autocomplete endpoint."""
    _seed_sample_data()
    resp = client.get("/config/search/places?q=City")
    assert resp.status_code == 200
    data = json.loads(resp.get_data(as_text=True))
    results = data.get("results", [])
    assert isinstance(results, list)
    assert any(item.get("name") == "City Office" for item in results)


def test_credentials_page_and_validation(client: FlaskClient) -> None:
    """Test credentials form retrieval, submission, and async validator."""
    # GET credentials
    resp = client.get("/config/credentials")
    assert resp.status_code == 200
    assert "API Credentials" in resp.get_data(as_text=True)

    # POST update credentials
    payload = {
        "bus_api_key": "new-bods-key-12345",
        "open_api_key": "sk-mock-key-abc",
        "open_api_model": "gpt-4o-mini",
        "google_maps_region": "uk",
    }
    post_resp = client.post(
        "/config/credentials",
        data=payload,
        follow_redirects=True,
    )
    assert post_resp.status_code == 200
    assert "API credentials saved successfully." in post_resp.get_data(as_text=True)

    # Test async validator endpoint
    from unittest.mock import MagicMock, patch

    mock_resp = MagicMock(status_code=401)
    with patch("app.datasources.bods.requests.get", return_value=mock_resp):
        val_resp = client.post(
            "/config/credentials/validate",
            json={"service": "bus", "bus_api_key": "invalid-test-key"},
        )
        assert val_resp.status_code == 200
        val_data = json.loads(val_resp.get_data(as_text=True))
        assert val_data.get("valid") is False
        assert "Invalid Bus API key" in val_data.get("message", "")


def test_locations_grid_data_binding_and_save(client: FlaskClient) -> None:
    """Test locations Grid.js JSON script embedding and form submission."""
    _seed_sample_data()
    get_resp = client.get("/config/locations")
    assert get_resp.status_code == 200
    data_resp = client.get("/config/locations/data")
    assert data_resp.status_code == 200
    locations = data_resp.get_json()["data"]
    assert len(locations) >= 2

    # Save new location list
    new_locations = {
        "added": [
            {
                "name": "Central Library",
                "latitude": 51.5180,
                "longitude": -0.1310,
                "ha": False,
            },
        ],
        "updated": [],
        "deleted": [],
    }
    post_resp = client.post(
        "/config/locations/data",
        json=new_locations,
    )
    assert post_resp.status_code == 200
    data_resp2 = client.get("/config/locations/data")
    assert data_resp2.status_code == 200
    updated_data = data_resp2.get_json()["data"]
    assert any(loc.get("name") == "Central Library" for loc in updated_data)


def test_timetables_grid_data_binding_and_save(client: FlaskClient) -> None:
    """Test timetables Grid.js JSON script embedding and form submission."""
    _seed_sample_data()
    get_resp = client.get("/config/timetables")
    assert get_resp.status_code == 200
    data_resp = client.get("/config/timetables/data")
    assert data_resp.status_code == 200
    timetables = data_resp.get_json()["data"]
    assert len(timetables) >= 1

    new_timetables = {
        "added": [
            {
                "name": "Evening Commute",
                "transport_type": "bus",
                "start_date": "2026-09-01",
                "end_date": "2026-12-31",
                "monday": True,
                "tuesday": True,
                "wednesday": True,
                "thursday": True,
                "friday": True,
                "saturday": False,
                "sunday": False,
                "bank_holiday": False,
                "content": {"stops": ["490000077E"], "trips": [{"time": "17:30"}]},
            }
        ],
        "updated": [],
        "deleted": [],
    }
    post_resp = client.post(
        "/config/timetables/data",
        json=new_timetables,
    )
    assert post_resp.status_code == 200
    data_resp2 = client.get("/config/timetables/data")
    assert data_resp2.status_code == 200
    updated_data = data_resp2.get_json()["data"]
    assert any(tt.get("name") == "Evening Commute" for tt in updated_data)


def test_transfers_grid_data_binding_and_save(client: FlaskClient) -> None:
    """Test transfers Grid.js JSON script embedding and form submission."""
    _seed_sample_data()
    get_resp = client.get("/config/transfers")
    assert get_resp.status_code == 200
    plat_resp = client.get("/config/transfers/data")
    assert plat_resp.status_code == 200

    plat_payload = [
        {
            "location_type": "rail",
            "location_id": "9100KNGX",
            "location_name": "London King's Cross",
            "from_platform": "1",
            "to_platform": "8",
            "transfer_time_minutes": 4,
            "bidirectional": True,
            "step_free": True,
            "notes": "Footbridge",
        }
    ]
    post_resp = client.post(
        "/config/transfers/data",
        json={"added": plat_payload, "updated": [], "deleted": []},
    )
    assert post_resp.status_code == 200
    plat_resp2 = client.get("/config/transfers/data")
    assert plat_resp2.status_code == 200
    updated_plat = plat_resp2.get_json()["data"]
    assert any(t.get("location_id") == "9100KNGX" for t in updated_plat)


def test_journeys_grid_data_binding_and_save(client: FlaskClient) -> None:
    """Test journeys Grid.js JSON script embedding and form submission."""
    _seed_sample_data()
    get_resp = client.get("/config/journeys")
    assert get_resp.status_code == 200
    j_resp = client.get("/config/journeys/data")
    assert j_resp.status_code == 200

    journeys_payload = [
        {
            "name": "Library Study Session",
            "from_type": "ha",
            "from_id": "zone.home",
            "from_name": "Home Zone",
            "to_type": "custom",
            "to_id": "custom:office",
            "to_name": "City Office",
            "time_settings": [
                {
                    "days": ["mon", "tue", "wed"],
                    "mode": "arrive",
                    "start_time": "13:30",
                    "end_time": "14:00",
                }
            ],
        }
    ]
    post_resp = client.post(
        "/config/journeys/data",
        json={"added": journeys_payload, "updated": [], "deleted": []},
    )
    assert post_resp.status_code == 200
    j_resp2 = client.get("/config/journeys/data")
    assert j_resp2.status_code == 200
    updated_j = j_resp2.get_json()["data"]
    assert any(j.get("name") == "Library Study Session" for j in updated_j)


def test_walking_grid_data_binding_and_save(client: FlaskClient) -> None:
    """Test walking Grid.js JSON script embedding and form submission."""
    _seed_sample_data()
    get_resp = client.get("/config/walking")
    assert get_resp.status_code == 200
    w_resp = client.get("/config/walking/data")
    assert w_resp.status_code == 200

    walking_payload = [
        {
            "start_type": "ha",
            "start_id": "zone.home",
            "start_name": "Home Zone",
            "finish_type": "custom",
            "finish_id": "custom:office",
            "finish_name": "City Office",
            "time_needed_minutes": 18,
            "bidirectional": True,
        }
    ]
    post_resp = client.post(
        "/config/walking/data",
        json={"added": walking_payload, "updated": [], "deleted": []},
    )
    assert post_resp.status_code == 200
    w_resp2 = client.get("/config/walking/data")
    assert w_resp2.status_code == 200
    updated_w = w_resp2.get_json()["data"]
    assert any(w.get("time_needed_minutes") == 18 for w in updated_w)


def test_journeys_ui_flow_create_save_navigate_return(client: FlaskClient) -> None:
    """Simulate full UI flow: create journey, save changes, navigate to overview and back."""
    _seed_sample_data()

    # Step 1: User visits journeys page
    resp1 = client.get("/config/journeys")
    assert resp1.status_code == 200
    assert "Configured Journeys" in resp1.get_data(as_text=True)

    # Step 2: User adds a new journey in the modal and submits form (Save Changes)
    new_journey = {
        "name": "Gym Workout Route",
        "from_type": "ha",
        "from_id": "zone.home",
        "from_name": "Home Zone",
        "to_type": "ha",
        "to_id": "zone.gym",
        "to_name": "City Health Club",
        "time_settings": [
            {
                "days": ["mon", "wed", "fri"],
                "mode": "arrive",
                "start_time": "07:00",
                "end_time": "07:15",
            }
        ],
    }
    save_resp = client.post(
        "/config/journeys/data",
        json={"added": [new_journey], "updated": [], "deleted": []},
    )
    assert save_resp.status_code == 200
    assert save_resp.get_json()["success"] is True

    # Step 3: User leaves page to Overview / other config section
    overview_resp = client.get("/")
    assert overview_resp.status_code == 200
    loc_resp = client.get("/config/locations")
    assert loc_resp.status_code == 200

    # Step 4: User returns to Journeys page
    return_resp = client.get("/config/journeys")
    assert return_resp.status_code == 200
    data_resp = client.get("/config/journeys/data")
    assert data_resp.status_code == 200
    loaded_journeys = data_resp.get_json()["data"]

    assert len(loaded_journeys) == 2
    j = next(item for item in loaded_journeys if item["name"] == "Gym Workout Route")
    assert j["name"] == "Gym Workout Route"
    assert j["from_name"] == "Home Zone"
    assert j["to_name"] == "City Health Club"
    assert len(j["time_settings"]) == 1
    assert j["time_settings"][0]["start_time"] == "07:00"
    assert j["time_settings"][0]["end_time"] == "07:15"


def test_all_pages_navigation_and_persistence_roundtrip(client: FlaskClient) -> None:
    """Test creating/saving on all pages sequentially and navigating between them."""
    _seed_sample_data()

    # 1. Update Credentials
    cred_payload = {
        "bus_api_key": "roundtrip_bods_key",
        "open_api_key": "roundtrip_openai_key",
        "open_api_model": "gpt-4o-mini",
        "google_maps_region": "uk",
    }
    resp = client.post("/config/credentials", data=cred_payload, follow_redirects=True)
    assert resp.status_code == 200

    # 2. Add Location
    loc_payload = {
        "added": [
            {
                "name": "Community Centre",
                "latitude": 51.5200,
                "longitude": -0.1100,
                "ha": False,
            }
        ],
        "updated": [],
        "deleted": [],
    }
    resp = client.post(
        "/config/locations/data",
        json=loc_payload,
    )
    assert resp.status_code == 200

    # 3. Add Timetable
    tt_payload = {
        "added": [
            {
                "name": "Saturday Market Shuttle",
                "transport_type": "bus",
                "start_date": "2026-06-01",
                "end_date": "2026-08-31",
                "monday": False,
                "tuesday": False,
                "wednesday": False,
                "thursday": False,
                "friday": False,
                "saturday": True,
                "sunday": False,
                "bank_holiday": False,
                "content": {"stops": ["490000077E"], "trips": [{"time": "10:00"}]},
            }
        ],
        "updated": [],
        "deleted": [],
    }
    resp = client.post(
        "/config/timetables/data",
        json=tt_payload,
    )
    assert resp.status_code == 200

    # 4. Add Transfer
    transfer_payload = {
        "added": [
            {
                "location_type": "rail",
                "location_id": "9100KNGX",
                "location_name": "London King's Cross",
                "from_platform": "1",
                "to_platform": "8",
                "transfer_time_minutes": 3,
                "bidirectional": True,
                "step_free": True,
                "notes": "Footbridge",
            }
        ],
        "updated": [],
        "deleted": [],
    }
    resp = client.post(
        "/config/transfers/data",
        json=transfer_payload,
    )
    assert resp.status_code == 200

    # 5. Add Journey
    journey_payload = {
        "added": [
            {
                "name": "Market Visit Route",
                "from_type": "ha",
                "from_id": "zone.home",
                "from_name": "Home Zone",
                "to_type": "custom",
                "to_id": "custom:community_centre",
                "to_name": "Community Centre",
                "time_settings": [
                    {
                        "days": ["sat"],
                        "mode": "arrive",
                        "start_time": "09:30",
                        "end_time": "10:00",
                    }
                ],
            }
        ],
        "updated": [],
        "deleted": [],
    }
    resp = client.post(
        "/config/journeys/data",
        json=journey_payload,
    )
    assert resp.status_code == 200

    # 6. Add Walking Route
    walking_payload = {
        "added": [
            {
                "start_type": "ha",
                "start_id": "zone.home",
                "start_name": "Home Zone",
                "finish_type": "bus",
                "finish_id": "490000077E",
                "finish_name": "King's Cross Stop E",
                "time_needed_minutes": 7,
                "bidirectional": True,
            }
        ],
        "updated": [],
        "deleted": [],
    }
    resp = client.post(
        "/config/walking/data",
        json=walking_payload,
    )
    assert resp.status_code == 200

    # 7. Now verify ALL pages retained their persisted state when revisited
    # A. Verify Credentials
    cred_get = client.get("/config/credentials")
    assert cred_get.status_code == 200
    assert 'value="roundtrip_bods_key"' in cred_get.get_data(as_text=True)

    # B. Verify Locations
    loc_get = client.get("/config/locations")
    assert loc_get.status_code == 200
    loc_data_resp = client.get("/config/locations/data")
    assert loc_data_resp.status_code == 200
    loc_data = loc_data_resp.get_json()["data"]
    assert any(loc_item["name"] == "Community Centre" for loc_item in loc_data)

    # C. Verify Timetables
    tt_get = client.get("/config/timetables")
    assert tt_get.status_code == 200
    tt_data_resp = client.get("/config/timetables/data")
    assert tt_data_resp.status_code == 200
    tt_data = tt_data_resp.get_json()["data"]
    assert any(t["name"] == "Saturday Market Shuttle" for t in tt_data)

    # D. Verify Transfers
    tr_get = client.get("/config/transfers")
    assert tr_get.status_code == 200
    tr_data_resp = client.get("/config/transfers/data")
    assert tr_data_resp.status_code == 200
    tr_data = tr_data_resp.get_json()["data"]
    assert any(t["notes"] == "Footbridge" for t in tr_data)

    # E. Verify Journeys
    j_get = client.get("/config/journeys")
    assert j_get.status_code == 200
    j_data_resp = client.get("/config/journeys/data")
    assert j_data_resp.status_code == 200
    j_data = j_data_resp.get_json()["data"]
    assert any(j["name"] == "Market Visit Route" for j in j_data)

    # F. Verify Walking
    w_get = client.get("/config/walking")
    assert w_get.status_code == 200
    w_data_resp = client.get("/config/walking/data")
    assert w_data_resp.status_code == 200
    w_data = w_data_resp.get_json()["data"]
    assert any(w["start_name"] == "Home Zone" for w in w_data)

    # G. Verify Database and Sync views
    db_resp = client.get("/config/db")
    assert db_resp.status_code == 200
    db_soup = BeautifulSoup(db_resp.get_data(as_text=True), "html.parser")
    dl_btn = db_soup.find("a", id="download-db-btn")
    assert dl_btn is not None
    assert "Download Database" in dl_btn.get_text()

    assert client.get("/config/sync").status_code == 200
    assert client.get("/").status_code == 200


def test_british_english_compliance_across_views(client: FlaskClient) -> None:
    """Verify that all rendered HTML templates adhere to British English standards."""
    routes = [
        "/",
        "/config/credentials",
        "/config/locations",
        "/config/timetables",
        "/config/transfers",
        "/config/journeys",
        "/config/walking",
        "/config/db",
        "/config/sync",
    ]
    prohibited_us_words = [
        r"\bcolor\b",
        r"\bcolors\b",
        r"\binitialize\b",
        r"\binitialized\b",
        r"\boptimizing\b",
        r"\bgrayscale\b",
    ]

    for route in routes:
        resp = client.get(route)
        assert resp.status_code == 200
        soup = BeautifulSoup(resp.get_data(as_text=True), "html.parser")
        text = soup.get_text()

        for pattern in prohibited_us_words:
            matches = re.findall(pattern, text, re.IGNORECASE)
            assert (
                len(matches) == 0
            ), f"Found US spelling violation {matches} on route {route}"
