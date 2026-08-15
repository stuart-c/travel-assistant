"""Unit tests for configuration views and credentials management."""

from pytest import MonkeyPatch
from flask.testing import FlaskClient
from app.db import SettingsRepository


def test_config_index_redirect(client: FlaskClient) -> None:
    """Test that /config redirects to /config/credentials."""
    response = client.get("/config")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/config/credentials")

    response_slash = client.get("/config/")
    assert response_slash.status_code == 302
    assert response_slash.headers["Location"].endswith("/config/credentials")


def test_get_credentials_page_initial_empty(client: FlaskClient) -> None:
    """Test GET /config/credentials renders empty form fields initially with default model."""
    response = client.get("/config/credentials")
    assert response.status_code == 200
    assert b"1. Bus API Key" in response.data
    assert b"2. Train S3 Bucket Details" in response.data
    assert b"3. Train Live Credentials" in response.data
    assert b"4. OpenAI &amp; LLM Credentials" in response.data
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
    assert b'href="https://developers.openai.com/api/docs/pricing"' in response.data
    assert b'value="gpt-4o-mini"' in response.data


def test_post_credentials_saves_and_redirects(
    client: FlaskClient, repo: SettingsRepository
) -> None:
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
    }

    response = client.post(
        "/config/credentials",
        data=post_data,
    )
    # Verify Post/Redirect/Get pattern (303 See Other redirect)
    assert response.status_code == 303
    assert response.headers["Location"].endswith("/config/credentials")

    # Verify data in database
    saved = repo.get_all(category="credentials")
    for key, expected_val in post_data.items():
        assert saved.get(key) == expected_val

    # Follow redirect to verify flash message and populated values
    follow_response = client.get("/config/credentials")
    assert follow_response.status_code == 200
    assert b"API credentials saved successfully." in follow_response.data
    assert b"test_bus_key_123" in follow_response.data
    assert b"my-train-bucket" in follow_response.data
    assert b"AKIA1234567890" in follow_response.data
    assert b"supersecretkey999" in follow_response.data
    assert b"eu-west-2" in follow_response.data
    assert b"train_live_token_abc" in follow_response.data
    assert b"https://darwin.live.trains.api" in follow_response.data
    assert b"sk-openai-key-test" in follow_response.data
    assert b"https://api.openai.com/v1" in follow_response.data
    assert b'value="gpt-4o" selected' in follow_response.data


def test_credentials_ingress_header(client: FlaskClient) -> None:
    """Test that Ingress header is respected in form action and links."""
    response = client.get(
        "/config/credentials",
        headers={"X-Ingress-Path": "/api/hassio_ingress/token123"},
    )
    assert response.status_code == 200
    assert b'action="/api/hassio_ingress/token123/config/credentials"' in response.data
    assert b'href="/api/hassio_ingress/token123/config/credentials"' in response.data
    assert b'href="/api/hassio_ingress/token123/"' in response.data


def test_validate_credentials_missing_service(client: FlaskClient) -> None:
    """Test POST /config/credentials/validate with missing service parameter."""
    response = client.post("/config/credentials/validate", json={})
    assert response.status_code == 400
    data = response.get_json()
    assert not data["valid"]
    assert "Service name is required" in data["message"]


def test_validate_credentials_unknown_service(client: FlaskClient) -> None:
    """Test POST /config/credentials/validate with unknown service."""
    response = client.post(
        "/config/credentials/validate",
        json={"service": "unsupported_service_xyz"},
    )
    assert response.status_code == 400
    data = response.get_json()
    assert not data["valid"]
    assert "Unknown service" in data["message"]


def test_validate_credentials_success(
    client: FlaskClient, monkeypatch: MonkeyPatch
) -> None:
    """Test POST /config/credentials/validate success response."""
    from unittest.mock import MagicMock
    from app import views

    mock_validate = MagicMock(
        return_value=(True, "Bus API key is valid and active.", {})
    )
    monkeypatch.setattr(views.config, "validate_service_credentials", mock_validate)

    response = client.post(
        "/config/credentials/validate",
        json={"service": "bus", "bus_api_key": "my_bus_token"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["valid"] is True
    assert "valid and active" in data["message"]
    assert data["service"] == "bus"
    mock_validate.assert_called_once_with(
        "bus",
        {"service": "bus", "bus_api_key": "my_bus_token"},
    )


def test_validate_credentials_fallback_to_repo(
    client: FlaskClient, repo: SettingsRepository, monkeypatch: MonkeyPatch
) -> None:
    """Test POST /config/credentials/validate merges saved DB credentials."""
    from unittest.mock import MagicMock
    from app import views

    repo.set("train_s3_bucket", "saved-bucket-name", category="credentials")
    repo.set("train_s3_region", "eu-west-1", category="credentials")

    mock_validate = MagicMock(return_value=(True, "S3 bucket is valid.", {}))
    monkeypatch.setattr(views.config, "validate_service_credentials", mock_validate)

    response = client.post(
        "/config/credentials/validate",
        json={"service": "train_s3"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["valid"] is True
    call_payload = mock_validate.call_args[0][1]
    assert call_payload["train_s3_bucket"] == "saved-bucket-name"
    assert call_payload["train_s3_region"] == "eu-west-1"


def test_validate_credentials_form_encoded(
    client: FlaskClient, monkeypatch: MonkeyPatch
) -> None:
    """Test POST /config/credentials/validate with form-encoded data."""
    from unittest.mock import MagicMock
    from app import views

    mock_validate = MagicMock(return_value=(False, "Invalid Open API key.", {}))
    monkeypatch.setattr(views.config, "validate_service_credentials", mock_validate)

    response = client.post(
        "/config/credentials/validate",
        data={"service": "open_api", "open_api_key": "bad_key"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["valid"] is False
    assert data["message"] == "Invalid Open API key."


def test_validate_credentials_openai_returns_models(
    client: FlaskClient, monkeypatch: MonkeyPatch
) -> None:
    """Test POST /config/credentials/validate for open_api returns model list."""
    from unittest.mock import MagicMock
    from app import views

    mock_validate = MagicMock(
        return_value=(
            True,
            "Open API credentials are valid and active.",
            {"models": ["gpt-4o-mini", "gpt-4o", "o3-mini"]},
        )
    )
    monkeypatch.setattr(views.config, "validate_service_credentials", mock_validate)

    response = client.post(
        "/config/credentials/validate",
        json={"service": "open_api", "open_api_key": "sk-test-123"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["valid"] is True
    assert data["models"] == ["gpt-4o-mini", "gpt-4o", "o3-mini"]
    assert data["service"] == "open_api"


def test_get_timetables_page(client: FlaskClient) -> None:
    """Test GET /config/timetables renders page with Grid.js and action bar."""
    response = client.get("/config/timetables")
    assert response.status_code == 200
    assert b"Active Timetables" in response.data
    assert b"gridjs" in response.data
    assert b"Add Timetable" in response.data
    assert b"Save Changes" in response.data
    assert b"Discard Changes" in response.data
    assert b"timetables_json" in response.data


def test_post_timetables_save_and_redirect(client: FlaskClient) -> None:
    """Test POST /config/timetables saves entries to database and redirects."""
    import json
    from app.db import TimetableRepository

    items = [
        {
            "transport_type": "bus",
            "name": "Oxford Tube",
            "identifier": "OX-TUBE",
            "status": "active",
        },
        {
            "transport_type": "train",
            "name": "London Paddington",
            "identifier": "PAD",
            "status": "inactive",
        },
    ]

    response = client.post(
        "/config/timetables",
        data={"timetables_json": json.dumps(items)},
    )
    assert response.status_code == 303
    assert response.headers["Location"].endswith("/config/timetables")

    # Verify repository has items
    repo = TimetableRepository()
    saved = repo.get_all()
    assert len(saved) == 2
    assert saved[0]["name"] == "Oxford Tube"
    assert saved[0]["transport_type"] == "bus"
    assert saved[1]["name"] == "London Paddington"
    assert saved[1]["status"] == "inactive"

    # Follow redirect
    follow = client.get("/config/timetables")
    assert follow.status_code == 200
    assert b"Timetables saved successfully." in follow.data


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
    import json
    from app.db import TimetableRepository

    items = [
        "not-a-dict",
        {
            "transport_type": "plane",  # Unknown type should fallback to bus
            "name": "Valid Route",
            "identifier": "VR-1",
            "status": "unknown_status",  # Should fallback to active
        },
        {
            "transport_type": "bus",
            "name": "",  # Empty name should be skipped
            "identifier": "NO-NAME",
        },
    ]

    response = client.post(
        "/config/timetables",
        data={"timetables_json": json.dumps(items)},
    )
    assert response.status_code == 303
    repo = TimetableRepository()
    saved = repo.get_all()
    assert len(saved) == 1
    assert saved[0]["transport_type"] == "bus"
    assert saved[0]["name"] == "Valid Route"
    assert saved[0]["status"] == "active"


def test_search_timetables_endpoint(client: FlaskClient) -> None:
    """Test GET /config/timetables/search filters results."""
    # Test all results
    res_all = client.get("/config/timetables/search")
    assert res_all.status_code == 200
    data_all = res_all.get_json()
    assert data_all["total"] > 0

    # Test bus filter
    res_bus = client.get("/config/timetables/search?type=bus")
    assert res_bus.status_code == 200
    data_bus = res_bus.get_json()
    assert all(item["transport_type"] == "bus" for item in data_bus["results"])

    # Test train filter
    res_train = client.get("/config/timetables/search?type=train")
    assert res_train.status_code == 200
    data_train = res_train.get_json()
    assert all(item["transport_type"] == "train" for item in data_train["results"])

    # Test search query
    res_query = client.get("/config/timetables/search?q=Oxford")
    assert res_query.status_code == 200
    data_query = res_query.get_json()
    assert any("Oxford" in item["name"] for item in data_query["results"])


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
    """Test GET /config/db renders database stats page correctly."""
    response = client.get("/config/db")
    assert response.status_code == 200
    assert b"Database Storage Overview" in response.data
    assert b"Database Size" in response.data
    assert b"User Tables" in response.data
    assert b"Total Records" in response.data
    assert b"Database Tables" in response.data
    assert b"settings" in response.data
    assert b"timetables" in response.data
    assert b"nav-link-db" in response.data
    assert b"refresh-stats-btn" in response.data


def test_get_db_page_with_populated_tables(
    client: FlaskClient, repo: SettingsRepository
) -> None:
    """Test GET /config/db accurately displays table row counts."""
    from app.db import TimetableRepository

    repo.set("bus_key", "secret123", category="credentials")
    repo.set("train_key", "secret456", category="credentials")

    timetable_repo = TimetableRepository()
    timetable_repo.add("bus", "Route 1", "R-01")
    timetable_repo.add("train", "Paddington", "PAD")

    response = client.get("/config/db")
    assert response.status_code == 200
    assert b"settings" in response.data
    assert b"timetables" in response.data
    assert b"stat-total-rows" in response.data
    assert b"initial-db-stats" in response.data


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


def test_db_page_renders_sync_buttons_and_headers(client: FlaskClient) -> None:
    """Test GET /config/db renders headers, Grid.js, and no Columns column."""
    response = client.get("/config/db")
    assert response.status_code == 200
    assert b"Database Tables" in response.data
    assert b"Database Storage Overview" in response.data
    assert b">Columns<" not in response.data
    assert b" cols<" not in response.data
    assert b"sync-all-btn" in response.data
    assert b"db-grid-wrapper" in response.data
    assert b"/static/js/db.js" in response.data
    assert b"/static/css/tables.css" in response.data
    assert b"bus_routes" in response.data
    assert b"bus_stops" in response.data
    assert b"stations" in response.data


def test_post_config_db_sync_table(client: FlaskClient) -> None:
    """Test POST /config/db/sync/<table_name> triggers synchronisation."""
    # When credentials are not configured, it returns skipped_no_credentials with 200
    response = client.post("/config/db/sync/bus_routes")
    assert response.status_code == 200
    data = response.get_json()
    assert data["table"] == "bus_routes"
    assert data["status"] == "skipped_no_credentials"
    assert "stats" in data

    # Invalid table name returns 400
    res_bad = client.post("/config/db/sync/nonexistent_tbl")
    assert res_bad.status_code == 400
    data_bad = res_bad.get_json()
    assert data_bad["status"] == "error"


def test_post_config_db_sync_all(client: FlaskClient) -> None:
    """Test POST /config/db/sync triggers sync_all."""
    response = client.post("/config/db/sync/all")
    assert response.status_code == 200
    data = response.get_json()
    assert data["table"] == "all"
    assert "tables" in data
    assert "bus_routes" in data["tables"]
    assert "bus_stops" in data["tables"]
    assert "stations" in data["tables"]

    # Default route without table_name parameter
    response_default = client.post("/config/db/sync")
    assert response_default.status_code == 200
    data_def = response_default.get_json()
    assert data_def["table"] == "all"
