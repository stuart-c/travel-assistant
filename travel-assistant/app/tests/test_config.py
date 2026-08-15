"""Unit tests for configuration views and credentials management."""

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
    """Test GET /config/credentials renders empty form fields initially."""
    response = client.get("/config/credentials")
    assert response.status_code == 200
    assert b"1. Bus API Key" in response.data
    assert b"2. Train S3 Bucket Details" in response.data
    assert b"3. Train Live Credentials" in response.data
    assert b"4. Open API Credentials" in response.data
    assert b'name="bus_api_key"' in response.data
    assert b'name="train_s3_bucket"' in response.data
    assert b'name="train_s3_access_key"' in response.data
    assert b'name="train_s3_secret_key"' in response.data
    assert b'name="train_s3_region"' in response.data
    assert b'name="train_live_api_key"' in response.data
    assert b'name="train_live_endpoint"' in response.data
    assert b'name="open_api_key"' in response.data
    assert b'name="open_api_base_url"' in response.data


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
