"""Unit tests for the Travel Assistant Flask application."""

from unittest.mock import patch
from flask.testing import FlaskClient


def test_index_page(client: FlaskClient) -> None:
    """Test that the index single page returns 200 and expected content."""
    response = client.get("/")
    assert response.status_code == 200
    assert b"Travel Assistant" in response.data
    assert b"Online &amp; Operational" in response.data
    assert b"https://unpkg.com/@tailwindcss/browser@4" in response.data


def test_ping_endpoint(client: FlaskClient) -> None:
    """Test that /api/ping returns status ok."""
    response = client.get("/api/ping")
    assert response.status_code == 200
    data = response.get_json()
    assert data == {"status": "ok"}


def test_info_endpoint(client: FlaskClient) -> None:
    """Test that /api/info returns metadata."""
    response = client.get("/api/info")
    assert response.status_code == 200
    data = response.get_json()
    assert data["name"] == "Travel Assistant Test"
    assert data["version"] == "0.1.0-test"
    assert data["ingress_enabled"] is True


def test_ingress_header_handling(client: FlaskClient) -> None:
    """Test that X-Ingress-Path header is processed in templates."""
    response = client.get(
        "/", headers={"X-Ingress-Path": "/api/hassio_ingress/token123"}
    )
    assert response.status_code == 200
    assert b"/api/hassio_ingress/token123/api/ping" in response.data
    assert b"Active" in response.data


def test_api_404_json_response(client: FlaskClient) -> None:
    """Test that unknown /api/ route returns JSON 404."""
    response = client.get("/api/nonexistent")
    assert response.status_code == 404
    data = response.get_json()
    assert data["status"] == 404
    assert data["error"] == "Not Found"


def test_page_404_html_response(client: FlaskClient) -> None:
    """Test that unknown non-API route returns HTML 404."""
    response = client.get("/unknown-page")
    assert response.status_code == 404
    assert b"Page not found" in response.data


def test_api_sync_endpoints(client: FlaskClient) -> None:
    """Test POST /api/sync and POST /api/sync/<table_name> endpoints."""
    # 1. Sync all tables
    with patch(
        "app.main.sync_all", return_value={"success": True, "total_records": 10}
    ):
        res_all = client.post("/api/sync")
        assert res_all.status_code == 200
        data_all = res_all.get_json()
        assert "success" in data_all

    # 2. Sync specific valid table
    with patch(
        "app.main.sync_table",
        return_value={"status": "success", "table": "bus_routes", "records": 5},
    ):
        res_table = client.post("/api/sync/bus_routes")
        assert res_table.status_code == 200
        data_table = res_table.get_json()
        assert data_table["table"] == "bus_routes"

    # 3. Sync invalid table
    res_invalid = client.post("/api/sync/unknown_table_xyz")
    assert res_invalid.status_code == 400
    data_invalid = res_invalid.get_json()
    assert data_invalid["status"] == "error"


def test_static_assets_served(client: FlaskClient) -> None:
    """Test that extracted static JS and CSS files are served successfully."""
    assets = [
        "/static/js/dirty-manager.js",
        "/static/js/credentials.js",
        "/static/js/timetables.js",
        "/static/js/transfers.js",
        "/static/js/db.js",
        "/static/css/tables.css",
        "/static/css/timetables.css",
    ]
    for asset_path in assets:
        response = client.get(asset_path)
        assert response.status_code == 200, f"Failed to load static asset: {asset_path}"
        assert len(response.data) > 0


def test_timetables_js_action_button_handlers(client: FlaskClient) -> None:
    """Test that timetables.js contains matching action button classes and click delegation."""
    response = client.get("/static/js/timetables.js")
    assert response.status_code == 200
    content = response.data.decode("utf-8")
    assert "edit-matrix-btn" in content
    assert "open-editor-btn" in content
    assert "edit-timetable-btn" in content
    assert "delete-timetable-btn" in content
    assert "openEditor(idx)" in content
