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
    # 1. Queue all tables
    with patch("app.main.request_sync") as mock_req:
        res_all = client.post("/api/sync")
        assert res_all.status_code == 200
        data_all = res_all.get_json()
        assert data_all["success"] is True
        assert data_all["status"] == "queued"
        assert "tables" in data_all
        assert mock_req.call_count == 7  # one call per SYNC_REGISTRY entry

    # 2. Queue specific valid table
    with patch("app.main.request_sync") as mock_req2:
        res_table = client.post("/api/sync/bus_routes")
        assert res_table.status_code == 200
        data_table = res_table.get_json()
        assert data_table["table"] == "bus_routes"
        assert data_table["status"] == "queued"
        mock_req2.assert_called_once_with("bus_routes")

    # 3. Invalid table returns 400
    res_invalid = client.post("/api/sync/unknown_table_xyz")
    assert res_invalid.status_code == 400
    data_invalid = res_invalid.get_json()
    assert data_invalid["status"] == "error"


def test_static_assets_served(client: FlaskClient) -> None:
    """Test that extracted static JS and CSS files are served successfully."""
    assets = [
        "/static/js/dirty-manager.js",
        "/static/js/credentials.js",
        "/static/js/grid_loader.js",
        "/static/js/timetables.js",
        "/static/js/transfers.js",
        "/static/js/locations.js",
        "/static/js/journeys.js",
        "/static/js/walking.js",
        "/static/js/place-autocomplete.js",
        "/static/js/db.js",
        "/static/js/transit-ui.js",
        "/static/js/day-selector.js",
        "/static/css/tables.css",
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


def test_grid_loader_js_exposes_window_namespace(client: FlaskClient) -> None:
    """Test that grid_loader.js defines window.GridLoader with the expected API."""
    response = client.get("/static/js/grid_loader.js")
    assert response.status_code == 200
    content = response.data.decode("utf-8")
    assert "window.GridLoader" in content
    assert "showLoading" in content
    assert "showError" in content
    assert "async function load" in content
    assert "progress_activity" in content


def test_grid_loader_js_included_in_config_pages(client: FlaskClient) -> None:
    """Test that grid_loader.js is loaded before each config page controller script."""
    pages = [
        ("/config/journeys", "journeys.js"),
        ("/config/locations", "locations.js"),
        ("/config/timetables", "timetables.js"),
        ("/config/transfers", "transfers.js"),
        ("/config/walking", "walking.js"),
        ("/config/db", "db.js"),
        ("/config/sync", "sync.js"),
    ]
    for url, page_js in pages:
        response = client.get(url)
        assert response.status_code == 200, f"GET {url} failed"
        html = response.data.decode("utf-8")
        # Search for the <script src="..."> tags specifically to avoid false positives
        # from HTML comments that may also reference the JS file name
        loader_tag = "/static/js/grid_loader.js"
        page_tag = f"/static/js/{page_js}"
        assert loader_tag in html, f"grid_loader.js missing from {url}"
        loader_pos = html.find(loader_tag)
        page_pos = html.find(page_tag)
        assert (
            loader_pos < page_pos
        ), f"grid_loader.js must appear before {page_js} script tag on {url}"


def test_transit_ui_js_exports_and_syntax(client: FlaskClient) -> None:
    """Test that transit-ui.js exports all required helpers without reference errors."""
    response = client.get("/static/js/transit-ui.js")
    assert response.status_code == 200
    content = response.data.decode("utf-8")
    assert "createChangesetTracker" in content
    assert "function createChangesetTracker" in content
    assert "ChangesetTracker" in content
    assert "class ChangesetTracker" in content
    assert "createStagedChangesetManager" in content
    assert "function createStagedChangesetManager" in content
    assert "StagedChangesetManager" in content
    assert "class StagedChangesetManager" in content
    assert "computeChangeset" in content
    assert "window.TransitUI" in content


def test_configure_logging() -> None:
    """Test configure_logging maps log levels correctly from LOG_LEVEL environment variable."""
    import logging
    import os
    from app.main import configure_logging

    with patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"}):
        configure_logging()
        assert logging.getLogger().level == logging.DEBUG

    with patch.dict(os.environ, {"LOG_LEVEL": "WARNING"}):
        configure_logging()
        assert logging.getLogger().level == logging.WARNING

    with patch.dict(os.environ, {"LOG_LEVEL": "ERROR"}):
        configure_logging()
        assert logging.getLogger().level == logging.ERROR

    with patch.dict(os.environ, {"LOG_LEVEL": "TRACE"}):
        configure_logging()
        assert logging.getLogger().level == logging.DEBUG

    with patch.dict(os.environ, {"LOG_LEVEL": "INFO"}):
        configure_logging()
        assert logging.getLogger().level == logging.INFO
