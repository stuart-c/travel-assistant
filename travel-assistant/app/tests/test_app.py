"""Unit tests for the Travel Assistant Flask application."""

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


def test_api_timetables_search_endpoint(client: FlaskClient) -> None:
    """Test that /api/timetables/search returns search results and cache state."""
    from app.db import BusRouteRepository

    # When uncached
    response_empty = client.get("/api/timetables/search?type=bus_route")
    assert response_empty.status_code == 200
    data_empty = response_empty.get_json()
    assert data_empty["is_cached"] is False
    assert data_empty["results"] == []

    # When cached
    route_repo = BusRouteRepository()
    route_repo.bulk_upsert(
        [
            {
                "route_number": "1",
                "operator_name": "Oxford Bus Company",
                "origin": "Blackbird Leys",
                "destination": "Oxford City Centre",
            }
        ]
    )
    response_cached = client.get("/api/timetables/search?type=bus_route&q=1")
    assert response_cached.status_code == 200
    data_cached = response_cached.get_json()
    assert data_cached["is_cached"] is True
    assert len(data_cached["results"]) == 1
    assert data_cached["results"][0]["route_number"] == "1"


def test_api_sync_endpoints(client: FlaskClient) -> None:
    """Test that /api/sync and /api/sync/<table_name> trigger sync operations."""
    # Test sync all
    res_all = client.post("/api/sync")
    assert res_all.status_code == 200
    data_all = res_all.get_json()
    assert "tables" in data_all

    # Test sync specific table
    res_table = client.post("/api/sync/stations")
    assert res_table.status_code == 200
    data_table = res_table.get_json()
    assert data_table["table"] == "stations"

    # Test invalid table
    res_invalid = client.post("/api/sync/invalid_table")
    assert res_invalid.status_code == 400


def test_static_assets_served(client: FlaskClient) -> None:
    """Test that extracted static JS and CSS files are served successfully."""
    assets = [
        "/static/js/dirty-manager.js",
        "/static/js/credentials.js",
        "/static/js/timetables.js",
        "/static/css/timetables.css",
    ]
    for asset_path in assets:
        response = client.get(asset_path)
        assert response.status_code == 200, f"Failed to load static asset: {asset_path}"
        assert len(response.data) > 0
