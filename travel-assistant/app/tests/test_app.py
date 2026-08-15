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
    """Test that /api/timetables/search returns search results."""
    response = client.get("/api/timetables/search?type=bus")
    assert response.status_code == 200
    data = response.get_json()
    assert "results" in data
    assert len(data["results"]) > 0


def test_api_sync_endpoints(client: FlaskClient) -> None:
    """Test /api/sync and /api/sync/<table_name> endpoints."""
    # Specific table
    res = client.post("/api/sync/bus_routes")
    assert res.status_code == 200
    data = res.get_json()
    assert data["table"] == "bus_routes"

    # All tables
    res_all = client.post("/api/sync")
    assert res_all.status_code == 200
    data_all = res_all.get_json()
    assert "tables" in data_all

    # Invalid table
    res_bad = client.post("/api/sync/invalid_table_name")
    assert res_bad.status_code == 400
    data_bad = res_bad.get_json()
    assert data_bad["status"] == "error"
