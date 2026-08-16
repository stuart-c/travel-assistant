"""Unit tests for configuration views and credentials management."""

import json
from unittest.mock import MagicMock
from pytest import MonkeyPatch
from flask.testing import FlaskClient

from app.models import Setting, Timetable


def test_config_index_redirect(client: FlaskClient) -> None:
    """Test that /config redirects to /config/credentials."""
    response = client.get("/config")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/config/credentials")

    response_slash = client.get("/config/")
    assert response_slash.status_code == 302
    assert response_slash.headers["Location"].endswith("/config/credentials")


def test_get_credentials_page_initial_empty(client: FlaskClient) -> None:
    """Test GET /config/credentials renders empty form fields with default model and region."""

    response = client.get("/config/credentials")
    assert response.status_code == 200
    assert b"Bus API Key" in response.data
    assert b"Train S3 Bucket Details" in response.data
    assert b"Train Live Credentials" in response.data
    assert b"OpenAI &amp; LLM Credentials" in response.data
    assert b"Google Maps API" in response.data
    assert b"1. Bus API Key" not in response.data
    assert b'name="bus_api_key"' in response.data
    assert b'name="train_s3_bucket"' in response.data
    assert b'name="train_s3_access_key"' in response.data
    assert b'name="train_s3_secret_key"' in response.data
    assert b'name="train_s3_region"' in response.data
    assert b'name="train_live_api_key"' in response.data
    assert b'name="train_live_endpoint"' in response.data
    assert b'name="open_api_key"' in response.data
    assert b'name="open_api_base_url"' in response.data
    assert b'name="open_api_model"' in response.data
    assert b'name="google_maps_api_key"' in response.data
    assert b'name="google_maps_region"' in response.data
    assert b'href="https://developers.openai.com/api/docs/pricing"' in response.data
    assert b'value="gpt-4o-mini"' in response.data
    assert b'value="uk"' in response.data


def test_post_credentials_saves_and_redirects(client: FlaskClient) -> None:
    """Test POST /config/credentials saves settings and performs PRG redirect."""
    post_data = {
        "bus_api_key": "test_bus_key_123",
        "train_s3_bucket": "my-train-bucket",
        "train_s3_access_key": "AKIA1234567890",
        "train_s3_secret_key": "supersecretkey999",
        "train_s3_region": "eu-west-2",
        "train_live_api_key": "train_live_token_abc",
        "train_live_endpoint": "https://darwin.live.trains.api",
        "open_api_key": "sk-openai-key-test",
        "open_api_base_url": "https://api.openai.com/v1",
        "open_api_model": "gpt-4o",
        "google_maps_api_key": "AIzaSyTest123",
        "google_maps_region": "gb",
    }

    response = client.post(
        "/config/credentials",
        data=post_data,
    )
    assert response.status_code == 303
    assert response.headers["Location"].endswith("/config/credentials")

    saved = Setting.get_by_category("credentials")
    assert saved["bus_api_key"] == "test_bus_key_123"
    assert saved["train_s3_bucket"] == "my-train-bucket"
    assert saved["train_s3_region"] == "eu-west-2"
    assert saved["open_api_model"] == "gpt-4o"
    assert saved["google_maps_api_key"] == "AIzaSyTest123"
    assert saved["google_maps_region"] == "gb"

    # Follow redirect
    follow = client.get("/config/credentials")
    assert follow.status_code == 200
    assert b"API credentials saved successfully." in follow.data
    assert b'value="test_bus_key_123"' in follow.data
    assert b'value="my-train-bucket"' in follow.data
    assert b'value="AIzaSyTest123"' in follow.data
    assert b'value="gb"' in follow.data


def test_credentials_ingress_header(client: FlaskClient) -> None:
    """Test that Ingress base path is prepended to form action and links."""
    response = client.get(
        "/config/credentials",
        headers={"X-Ingress-Path": "/api/hassio_ingress/xyz123"},
    )
    assert response.status_code == 200
    assert b'action="/api/hassio_ingress/xyz123/config/credentials"' in response.data
    assert b'href="/api/hassio_ingress/xyz123/config/credentials"' in response.data


def test_validate_credentials_missing_service(client: FlaskClient) -> None:
    """Test POST /config/credentials/validate without service returns 400."""
    response = client.post(
        "/config/credentials/validate",
        json={"bus_api_key": "token123"},
    )
    assert response.status_code == 400
    data = response.get_json()
    assert data["valid"] is False
    assert "Service name is required" in data["message"]


def test_validate_credentials_unknown_service(client: FlaskClient) -> None:
    """Test POST /config/credentials/validate with unknown service returns 400."""
    response = client.post(
        "/config/credentials/validate",
        json={"service": "unknown_transit_svc"},
    )
    assert response.status_code == 400
    data = response.get_json()
    assert data["valid"] is False
    assert "Unknown service" in data["message"]


def test_validate_credentials_form_post_compatibility(
    client: FlaskClient, monkeypatch: MonkeyPatch
) -> None:
    """Test POST /config/credentials/validate accepts form-encoded data."""
    from app import views

    mock_validate = MagicMock(return_value=(True, "Bus credentials valid.", {}))
    monkeypatch.setattr(
        views.config.credentials, "validate_service_credentials", mock_validate
    )

    response = client.post(
        "/config/credentials/validate",
        data={"service": "bus", "bus_api_key": "my_bus_token"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["valid"] is True
    assert data["message"] == "Bus credentials valid."
    assert data["service"] == "bus"


def test_validate_credentials_fallback_to_repo(
    client: FlaskClient, monkeypatch: MonkeyPatch
) -> None:
    """Test POST /config/credentials/validate merges saved DB credentials."""
    from app import views

    Setting.set_val("train_s3_bucket", "saved-bucket-name", category="credentials")
    Setting.set_val("train_s3_region", "eu-west-1", category="credentials")

    mock_validate = MagicMock(return_value=(True, "S3 bucket is valid.", {}))
    monkeypatch.setattr(
        views.config.credentials, "validate_service_credentials", mock_validate
    )

    response = client.post(
        "/config/credentials/validate",
        json={"service": "train_s3"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["valid"] is True


def test_get_timetables_page_initial_empty(client: FlaskClient) -> None:
    """Test GET /config/timetables renders empty list."""
    response = client.get("/config/timetables")
    assert response.status_code == 200
    assert b"Active Timetables" in response.data
    assert b"No timetables configured" in response.data
    assert b"Add Timetable" in response.data


def test_post_timetables_saves_and_redirects(client: FlaskClient) -> None:
    """Test POST /config/timetables stores valid entries."""
    items = [
        {
            "name": "Standard Commute Schedule",
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
        },
        {
            "name": "Weekend Service",
            "start_date": None,
            "end_date": None,
            "monday": False,
            "tuesday": False,
            "wednesday": False,
            "thursday": False,
            "friday": False,
            "saturday": True,
            "sunday": True,
            "bank_holiday": True,
        },
    ]

    response = client.post(
        "/config/timetables",
        data={"timetables_json": json.dumps(items)},
    )
    assert response.status_code == 303
    assert response.headers["Location"].endswith("/config/timetables")

    # Verify model has items
    saved = [t.to_dict() for t in Timetable.select()]
    assert len(saved) == 2
    assert saved[0]["name"] == "Standard Commute Schedule"
    assert saved[0]["start_date"] == "2026-09-01"
    assert saved[0]["end_date"] == "2026-12-31"
    assert saved[0]["monday"] is True
    assert saved[0]["saturday"] is False
    assert saved[1]["name"] == "Weekend Service"
    assert saved[1]["start_date"] is None
    assert saved[1]["saturday"] is True

    # Follow redirect
    follow = client.get("/config/timetables")
    assert follow.status_code == 200
    assert b"Timetables saved successfully." in follow.data


def test_post_timetables_invalid_date_order(client: FlaskClient) -> None:
    """Test POST /config/timetables validates end_date is after start_date."""
    items = [
        {
            "name": "Invalid Date Schedule",
            "start_date": "2026-12-31",
            "end_date": "2026-01-01",
        }
    ]
    response = client.post(
        "/config/timetables",
        data={"timetables_json": json.dumps(items)},
    )
    assert response.status_code == 303
    follow = client.get("/config/timetables")
    assert follow.status_code == 200
    assert b"End date" in follow.data
    assert b"cannot be before start date" in follow.data


def test_post_timetables_invalid_date_format(client: FlaskClient) -> None:
    """Test POST /config/timetables rejects malformed date format."""
    items = [
        {
            "name": "Malformed Start Date Schedule",
            "start_date": "01-09-2026",
            "end_date": "2026-12-31",
        }
    ]
    response = client.post(
        "/config/timetables",
        data={"timetables_json": json.dumps(items)},
    )
    assert response.status_code == 303
    follow = client.get("/config/timetables")
    assert follow.status_code == 200
    assert b"Invalid start date format" in follow.data

    items_end = [
        {
            "name": "Malformed End Date Schedule",
            "start_date": "2026-09-01",
            "end_date": "31-12-2026",
        }
    ]
    response_end = client.post(
        "/config/timetables",
        data={"timetables_json": json.dumps(items_end)},
    )
    assert response_end.status_code == 303
    follow_end = client.get("/config/timetables")
    assert follow_end.status_code == 200
    assert b"Invalid end date format" in follow_end.data


def test_post_timetables_malformed_json(client: FlaskClient) -> None:
    """Test POST /config/timetables handles invalid JSON gracefully."""
    response = client.post(
        "/config/timetables",
        data={"timetables_json": "invalid-json-string{"},
    )
    assert response.status_code == 303
    follow = client.get("/config/timetables")
    assert follow.status_code == 200
    assert b"Failed to save timetables" in follow.data


def test_post_timetables_non_list_json(client: FlaskClient) -> None:
    """Test POST /config/timetables handles JSON that is not a list."""
    response = client.post(
        "/config/timetables",
        data={"timetables_json": '{"key": "not-a-list"}'},
    )
    assert response.status_code == 303
    follow = client.get("/config/timetables")
    assert follow.status_code == 200
    assert b"Failed to save timetables" in follow.data


def test_post_timetables_sanitises_entries(client: FlaskClient) -> None:
    """Test POST /config/timetables sanitises input and skips empty names."""
    items = [
        "not-a-dict",
        {
            "name": "Valid Route Schedule",
            "monday": True,
        },
        {
            "name": "",  # Empty name should be skipped
            "start_date": "2026-01-01",
        },
    ]

    response = client.post(
        "/config/timetables",
        data={"timetables_json": json.dumps(items)},
    )
    assert response.status_code == 303
    saved = [t.to_dict() for t in Timetable.select()]
    assert len(saved) == 1
    assert saved[0]["name"] == "Valid Route Schedule"
    assert saved[0]["monday"] is True


def test_search_places_endpoint(client: FlaskClient) -> None:
    """Test GET /config/search/places across rail, bus, HA, and custom location datasets."""
    from app.models import Location, Stop

    # 1. Test empty response when nothing cached
    res_all = client.get("/config/search/places")
    assert res_all.status_code == 200
    data_all = res_all.get_json()
    assert data_all["total"] == 0
    assert data_all["results"] == []

    # 2. Populate stops and locations
    Stop.bulk_upsert(
        [
            {
                "atco_code": "9100OXF",
                "naptan_code": "OXF",
                "stop_type": "rail",
                "name": "Oxford",
            },
            {
                "atco_code": "9100PAD",
                "naptan_code": None,
                "stop_type": "rail",
                "name": "London Paddington",
            },
            {
                "atco_code": "340000001",
                "naptan_code": None,
                "stop_type": "bus",
                "name": "High Street Stop T1",
                "locality": "Oxford",
                "indicator": "Stop T1",
            },
            {
                "atco_code": "340000002",
                "naptan_code": "oxf002",
                "stop_type": "bus",
                "name": "Blackbird Leys Leisure Centre",
                "locality": "Oxford",
                "indicator": "opp",
            },
        ]
    )

    Location.insert_many(
        [
            {
                "id": "ha:home",
                "name": "Home",
                "latitude": 51.7520,
                "longitude": -1.2577,
                "ha": True,
            },
            {
                "id": "custom:office",
                "name": "Office HQ",
                "latitude": 51.7500,
                "longitude": -1.2600,
                "ha": False,
            },
        ]
    ).execute()

    # 3. Test station search (with naptan prefix vs atco prefix)
    res_st = client.get("/config/search/places?type=station&q=Oxford")
    assert res_st.status_code == 200
    data_st = res_st.get_json()
    assert len(data_st["results"]) == 1
    assert data_st["results"][0]["id"] == "naptan:OXF"
    assert data_st["results"][0]["type"] == "station"
    assert data_st["results"][0]["icon"] == "train"

    res_pad = client.get("/config/search/places?type=train&q=Paddington")
    assert res_pad.status_code == 200
    data_pad = res_pad.get_json()
    assert len(data_pad["results"]) == 1
    assert data_pad["results"][0]["id"] == "atco:9100PAD"

    # 4. Test bus stop search
    res_bus = client.get("/config/search/places?type=bus_stop&q=High Street")
    assert res_bus.status_code == 200
    data_bus = res_bus.get_json()
    assert len(data_bus["results"]) == 1
    assert data_bus["results"][0]["id"] == "atco:340000001"
    assert data_bus["results"][0]["type"] == "bus_stop"
    assert data_bus["results"][0]["icon"] == "directions_bus"

    res_bus_naptan = client.get("/config/search/places?type=bus&q=Blackbird")
    assert res_bus_naptan.status_code == 200
    data_bus_naptan = res_bus_naptan.get_json()
    assert len(data_bus_naptan["results"]) == 1
    assert data_bus_naptan["results"][0]["id"] == "naptan:oxf002"

    # 5. Test HA and custom location search
    res_ha = client.get("/config/search/places?type=ha_location&q=Home")
    assert res_ha.status_code == 200
    data_ha = res_ha.get_json()
    assert len(data_ha["results"]) == 1
    assert data_ha["results"][0]["id"] == "ha:home"
    assert data_ha["results"][0]["type"] == "ha_location"
    assert data_ha["results"][0]["icon"] == "home"

    res_custom = client.get("/config/search/places?type=custom&q=Office")
    assert res_custom.status_code == 200
    data_custom = res_custom.get_json()
    assert len(data_custom["results"]) == 1
    assert data_custom["results"][0]["id"] == "custom:office"
    assert data_custom["results"][0]["type"] == "custom_location"
    assert data_custom["results"][0]["icon"] == "pin_drop"

    # 6. Test all locations search without type filter
    res_all_q = client.get("/config/search/places?limit=invalid")
    assert res_all_q.status_code == 200
    data_all_q = res_all_q.get_json()
    assert data_all_q["total"] >= 4


def test_timetables_ingress_header(client: FlaskClient) -> None:
    """Test that Ingress header is respected in timetables template."""
    response = client.get(
        "/config/timetables",
        headers={"X-Ingress-Path": "/api/hassio_ingress/token123"},
    )
    assert response.status_code == 200
    assert b'action="/api/hassio_ingress/token123/config/timetables"' in response.data
    assert b'href="/api/hassio_ingress/token123/config/credentials"' in response.data


def test_get_db_page_initial_render(client: FlaskClient) -> None:
    """Test GET /config/db renders database size card and tables grid."""
    response = client.get("/config/db")
    assert response.status_code == 200
    assert b"Database Size" in response.data
    assert b"stat-db-size" in response.data
    assert b"Database Tables" in response.data
    assert b"db-grid-wrapper" in response.data
    assert b"initial-db-stats" in response.data
    assert b"/static/js/db.js" in response.data
    assert b"nav-link-db" in response.data
    assert b"standard-action-bar" not in response.data
    assert b"refresh-stats-btn" not in response.data


def test_get_db_page_with_populated_tables(client: FlaskClient) -> None:
    """Test GET /config/db accurately displays database size metrics."""
    Setting.set_val("bus_key", "secret123", category="credentials")
    Setting.set_val("train_key", "secret456", category="credentials")

    Timetable.create(transport_type="bus", name="Route 1", identifier="R-01")
    Timetable.create(transport_type="train", name="Paddington", identifier="PAD")

    response = client.get("/config/db")
    assert response.status_code == 200
    assert b"Database Size" in response.data
    assert b"stat-db-size" in response.data
    assert b"Database Tables" in response.data
    assert b"db-grid-wrapper" in response.data


def test_db_page_ingress_header(client: FlaskClient) -> None:
    """Test that Ingress header is respected in db stats template."""
    response = client.get(
        "/config/db",
        headers={"X-Ingress-Path": "/api/hassio_ingress/test_token"},
    )
    assert response.status_code == 200
    assert b'href="/api/hassio_ingress/test_token/config/db"' in response.data
    assert b'href="/api/hassio_ingress/test_token/config/credentials"' in response.data
    assert b'href="/api/hassio_ingress/test_token/config/timetables"' in response.data
    assert b'href="/api/hassio_ingress/test_token/config/sync"' in response.data


def test_get_sync_page_initial_render(client: FlaskClient) -> None:
    """Test GET /config/sync renders transit datasets sync page with Grid.js."""
    response = client.get("/config/sync")
    assert response.status_code == 200
    assert b"Background Sync" in response.data
    assert b"Transit Datasets" in response.data
    assert b"sync-all-btn" not in response.data
    assert b"sync-grid-wrapper" in response.data
    assert b"initial-sync-stats" in response.data
    assert b"/static/js/sync.js" in response.data
    assert b"standard-action-bar" not in response.data

    # Verify locations table is marked as syncable in payload
    html = response.get_data(as_text=True)
    import re

    match = re.search(
        r'<script id="initial-sync-stats"[^>]*>(.*?)</script>', html, re.DOTALL
    )
    assert match is not None
    payload = json.loads(match.group(1))
    tables = payload.get("tables", [])
    loc_entry = next((t for t in tables if t["name"] == "locations"), None)
    assert loc_entry is not None
    assert loc_entry["syncable"] is True


def test_sync_db_table_endpoint_all_rejected(client: FlaskClient) -> None:
    """Test POST /config/db/sync/all returns 400 as bulk synchronisation is removed."""
    response = client.post("/config/db/sync/all")
    assert response.status_code == 400
    data = response.get_json()
    assert data["success"] is False
    assert data["status"] == "error"
    assert "Bulk dataset synchronisation is not supported" in data["message"]


def test_sync_db_table_endpoint_specific_success(
    client: FlaskClient, monkeypatch: MonkeyPatch
) -> None:
    """Test POST /config/db/sync/<table_name> triggers specific table sync."""
    from app.views import config

    mock_sync_table = MagicMock(
        return_value={
            "status": "success",
            "records": 25,
            "message": "Sync successful",
            "duration_seconds": 1.5,
        }
    )
    monkeypatch.setattr(config.sync, "sync_table", mock_sync_table)

    response = client.post("/config/db/sync/bus_routes")
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert data["records"] == 25
    assert data["table"] == "bus_routes"
    mock_sync_table.assert_called_once_with("bus_routes", force=True)


def test_sync_db_table_endpoint_specific_error(
    client: FlaskClient, monkeypatch: MonkeyPatch
) -> None:
    """Test POST /config/db/sync/<table_name> with failed sync returns 400."""
    from app.views import config

    mock_sync_table = MagicMock(
        return_value={
            "status": "error",
            "records": 0,
            "message": "Invalid API key",
            "duration_seconds": 0.5,
        }
    )
    monkeypatch.setattr(config.sync, "sync_table", mock_sync_table)

    response = client.post("/config/db/sync/stops")
    assert response.status_code == 400
    data = response.get_json()
    assert data["success"] is False
    assert data["status"] == "error"


def test_config_routes_disable_browser_caching(client: FlaskClient) -> None:
    """Test that all configuration endpoints return HTTP headers disabling browser caching."""
    endpoints = [
        "/config",
        "/config/",
        "/config/credentials",
        "/config/timetables",
        "/config/transfers",
        "/config/locations",
        "/config/journeys",
        "/config/sync",
        "/config/db",
        "/config/search/places?q=test",
    ]

    for endpoint in endpoints:
        response = client.get(endpoint)
        assert (
            response.headers.get("Cache-Control")
            == "no-cache, no-store, must-revalidate, max-age=0"
        ), f"Missing or incorrect Cache-Control header on {endpoint}"
        assert (
            response.headers.get("Pragma") == "no-cache"
        ), f"Missing Pragma header on {endpoint}"
        assert (
            response.headers.get("Expires") == "0"
        ), f"Missing Expires header on {endpoint}"


def test_config_pages_include_no_cache_meta_tags(client: FlaskClient) -> None:
    """Test that HTML configuration pages contain no-cache meta tags in head."""
    pages = [
        "/config/credentials",
        "/config/timetables",
        "/config/transfers",
        "/config/locations",
        "/config/journeys",
        "/config/sync",
        "/config/db",
    ]

    for page in pages:
        response = client.get(page)
        assert response.status_code == 200
        html = response.data.decode("utf-8")
        assert (
            '<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">'
            in html
        ), f"Missing Cache-Control meta tag in {page}"
        assert (
            '<meta http-equiv="Pragma" content="no-cache">' in html
        ), f"Missing Pragma meta tag in {page}"
        assert (
            '<meta http-equiv="Expires" content="0">' in html
        ), f"Missing Expires meta tag in {page}"
