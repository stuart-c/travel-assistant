"""Comprehensive UI flow, DOM structure, and Ingress integration unit tests."""

import json
import re
from typing import Any
from bs4 import BeautifulSoup
import pytest

from app.models import (
    Journey,
    Location,
    LocationTransfer,
    PlatformTransfer,
    Setting,
    Timetable,
)


@pytest.fixture
def client_with_sample_data(app: Any) -> Any:
    """Fixture providing a test client with pre-seeded sample transit data."""
    with app.app_context():
        # Clean existing test data
        Location.delete().execute()
        Timetable.delete().execute()
        LocationTransfer.delete().execute()
        PlatformTransfer.delete().execute()
        Journey.delete().execute()
        Setting.delete().execute()

        # Seed sample locations
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

        # Seed sample timetable
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

        # Seed sample transfers
        LocationTransfer.create(
            from_type="rail",
            from_id="9100KNGX",
            from_name="London King's Cross",
            to_type="bus",
            to_id="490000077E",
            to_name="King's Cross Stop E",
            transfer_time_minutes=3,
            bidirectional=True,
            step_free=True,
        )
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

        # Seed sample journey
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

    return app.test_client()


def test_dashboard_and_navigation(client_with_sample_data: Any) -> None:
    """Test dashboard root view and navigation header links."""
    response = client_with_sample_data.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    soup = BeautifulSoup(html, "html.parser")
    assert soup.title is not None
    assert "Overview" in soup.title.string
    assert "Travel Assistant" in html


def test_ingress_path_header_injection(client_with_sample_data: Any) -> None:
    """Verify that X-Ingress-Path is injected into relative URLs and asset paths."""
    ingress_prefix = "/api/hassio_ingress/token123"
    response = client_with_sample_data.get(
        "/config/credentials",
        headers={"X-Ingress-Path": ingress_prefix},
    )
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert f'action="{ingress_prefix}/config/credentials"' in html
    assert f'href="{ingress_prefix}/static/css/tables.css' in html


def test_places_search_autocomplete_api(client_with_sample_data: Any) -> None:
    """Test /config/search/places autocomplete endpoint."""
    resp = client_with_sample_data.get("/config/search/places?q=City")
    assert resp.status_code == 200
    data = json.loads(resp.get_data(as_text=True))
    results = data.get("results", [])
    assert isinstance(results, list)
    assert any(item.get("name") == "City Office" for item in results)


def test_credentials_page_and_validation(client_with_sample_data: Any) -> None:
    """Test credentials form retrieval, submission, and async validator."""
    # GET credentials
    resp = client_with_sample_data.get("/config/credentials")
    assert resp.status_code == 200
    assert "API Credentials" in resp.get_data(as_text=True)

    # POST update credentials
    payload = {
        "bus_api_key": "new-bods-key-12345",
        "open_api_key": "sk-mock-key-abc",
        "open_api_model": "gpt-4o-mini",
        "google_maps_region": "uk",
    }
    post_resp = client_with_sample_data.post(
        "/config/credentials",
        data=payload,
        follow_redirects=True,
    )
    assert post_resp.status_code == 200
    assert "API credentials saved successfully." in post_resp.get_data(as_text=True)

    # Test async validator endpoint
    val_resp = client_with_sample_data.post(
        "/config/credentials/validate",
        json={"service": "bus", "bus_api_key": "invalid-test-key"},
    )
    assert val_resp.status_code == 200
    val_data = json.loads(val_resp.get_data(as_text=True))
    assert val_data.get("valid") is False
    assert "Invalid Bus API key" in val_data.get("message", "")


def test_locations_grid_data_binding_and_save(client_with_sample_data: Any) -> None:
    """Test locations Grid.js JSON script embedding and form submission."""
    # Verify initial data script tag
    get_resp = client_with_sample_data.get("/config/locations")
    assert get_resp.status_code == 200
    soup = BeautifulSoup(get_resp.get_data(as_text=True), "html.parser")
    data_script = soup.find("script", id="initial-locations-data")
    assert data_script is not None
    locations = json.loads(data_script.string)
    assert len(locations) >= 2

    # Save new location list
    new_locations = [
        {
            "id": "zone.home",
            "name": "Home Zone Updated",
            "latitude": 51.5310,
            "longitude": -0.1210,
            "ha": True,
        },
        {
            "id": "custom:library",
            "name": "Central Library",
            "latitude": 51.5180,
            "longitude": -0.1310,
            "ha": False,
        },
    ]
    post_resp = client_with_sample_data.post(
        "/config/locations",
        data={"locations_json": json.dumps(new_locations)},
        follow_redirects=True,
    )
    assert post_resp.status_code == 200
    soup_post = BeautifulSoup(post_resp.get_data(as_text=True), "html.parser")
    updated_script = soup_post.find("script", id="initial-locations-data")
    updated_data = json.loads(updated_script.string)
    assert any(loc.get("name") == "Central Library" for loc in updated_data)


def test_timetables_grid_data_binding_and_save(client_with_sample_data: Any) -> None:
    """Test timetables Grid.js JSON script embedding and form submission."""
    get_resp = client_with_sample_data.get("/config/timetables")
    assert get_resp.status_code == 200
    soup = BeautifulSoup(get_resp.get_data(as_text=True), "html.parser")
    data_script = soup.find("script", id="initial-timetables-data")
    assert data_script is not None
    timetables = json.loads(data_script.string)
    assert len(timetables) >= 1

    new_timetables = [
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
    ]
    post_resp = client_with_sample_data.post(
        "/config/timetables",
        data={"timetables_json": json.dumps(new_timetables)},
        follow_redirects=True,
    )
    assert post_resp.status_code == 200
    soup_post = BeautifulSoup(post_resp.get_data(as_text=True), "html.parser")
    updated_script = soup_post.find("script", id="initial-timetables-data")
    updated_data = json.loads(updated_script.string)
    assert any(tt.get("name") == "Evening Commute" for tt in updated_data)


def test_transfers_grid_data_binding_and_save(client_with_sample_data: Any) -> None:
    """Test transfers Grid.js JSON script embedding and form submission."""
    get_resp = client_with_sample_data.get("/config/transfers")
    assert get_resp.status_code == 200
    soup = BeautifulSoup(get_resp.get_data(as_text=True), "html.parser")
    loc_script = soup.find("script", id="initial-location-transfers-data")
    plat_script = soup.find("script", id="initial-platform-transfers-data")
    assert loc_script is not None and plat_script is not None

    loc_payload = [
        {
            "from_type": "rail",
            "from_id": "9100KNGX",
            "from_name": "London King's Cross",
            "to_type": "rail",
            "to_id": "9100STPX",
            "to_name": "London St Pancras",
            "transfer_time_minutes": 4,
            "bidirectional": True,
            "step_free": True,
            "notes": "Pedestrian link",
        }
    ]
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
    post_resp = client_with_sample_data.post(
        "/config/transfers",
        data={
            "location_transfers_json": json.dumps(loc_payload),
            "platform_transfers_json": json.dumps(plat_payload),
        },
        follow_redirects=True,
    )
    assert post_resp.status_code == 200
    soup_post = BeautifulSoup(post_resp.get_data(as_text=True), "html.parser")
    updated_loc = json.loads(
        soup_post.find("script", id="initial-location-transfers-data").string
    )
    assert any(t.get("from_id") == "9100KNGX" for t in updated_loc)


def test_journeys_grid_data_binding_and_save(client_with_sample_data: Any) -> None:
    """Test journeys Grid.js JSON script embedding and form submission."""
    get_resp = client_with_sample_data.get("/config/journeys")
    assert get_resp.status_code == 200
    soup = BeautifulSoup(get_resp.get_data(as_text=True), "html.parser")
    j_script = soup.find("script", id="initial-journeys-data")
    assert j_script is not None

    journeys_payload = [
        {
            "name": "Library Study Session",
            "from_type": "ha",
            "from_id": "zone.home",
            "from_name": "Home Zone",
            "to_type": "custom",
            "to_id": "custom:office",
            "to_name": "City Office",
            "time_settings": [{"target_arrival": "14:00"}],
        }
    ]
    post_resp = client_with_sample_data.post(
        "/config/journeys",
        data={"journeys_json": json.dumps(journeys_payload)},
        follow_redirects=True,
    )
    assert post_resp.status_code == 200
    soup_post = BeautifulSoup(post_resp.get_data(as_text=True), "html.parser")
    updated_j = json.loads(soup_post.find("script", id="initial-journeys-data").string)
    assert any(j.get("name") == "Library Study Session" for j in updated_j)


def test_british_english_compliance_across_views(client_with_sample_data: Any) -> None:
    """Verify that all rendered HTML templates adhere to British English standards."""
    routes = [
        "/",
        "/config/credentials",
        "/config/locations",
        "/config/timetables",
        "/config/transfers",
        "/config/journeys",
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
        resp = client_with_sample_data.get(route)
        assert resp.status_code == 200
        soup = BeautifulSoup(resp.get_data(as_text=True), "html.parser")
        text = soup.get_text()

        for pattern in prohibited_us_words:
            matches = re.findall(pattern, text, re.IGNORECASE)
            assert (
                len(matches) == 0
            ), f"Found US spelling violation {matches} on route {route}"
