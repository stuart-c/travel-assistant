"""Unit tests for Home Assistant location synchronisation workflow."""

import os
from unittest.mock import MagicMock, patch
from flask import Flask
from flask.testing import FlaskClient

from app.datasources.exceptions import (
    DataSourceAuthError,
    DataSourceConnectionError,
)
from app.models import Location, SyncMetadata
from app.sync.ha_sync import sync_ha_locations
from app.sync.transit_sync import sync_all, sync_table


def test_sync_ha_locations_skipped_no_credentials(app: Flask) -> None:
    """Test sync_ha_locations returns skipped status when no token is present."""
    with app.app_context(), patch.dict(os.environ, {}, clear=True):
        res = sync_ha_locations(app)
        assert res["status"] == "skipped_no_credentials"
        assert res["records"] == 0
        assert "not configured" in res["message"]

        meta = SyncMetadata.get_or_none(SyncMetadata.table_name == "ha_locations")
        assert meta is not None
        assert meta.status == "skipped"


@patch("app.sync.ha_sync.HomeAssistantClient.fetch_zones")
def test_sync_ha_locations_success_creates_updates_and_prunes(
    mock_fetch: MagicMock, app: Flask
) -> None:
    """Test sync_ha_locations creates, updates existing, and prunes removed HA zones."""
    with app.app_context(), patch.dict(os.environ, {"SUPERVISOR_TOKEN": "mock-token"}):
        # Seed initial locations: one custom, one existing HA location, one obsolete HA location
        Location.create(
            name="My Custom Café", latitude=51.51, longitude=-0.11, ha=False
        )
        Location.create(
            name="Home", latitude=51.0, longitude=0.0, ha=False
        )  # will be matched and converted to HA
        Location.create(
            name="Old HA Zone", latitude=52.0, longitude=0.5, ha=True
        )  # will be pruned

        mock_fetch.return_value = [
            {
                "entity_id": "zone.home",
                "name": "Home",
                "latitude": 51.7520,
                "longitude": -1.2577,
            },
            {
                "entity_id": "zone.office",
                "name": "Office",
                "latitude": 51.5074,
                "longitude": -0.1278,
            },
        ]

        res = sync_ha_locations(app)
        assert res["status"] == "success"
        assert res["records"] == 2
        assert "Successfully synchronised" in res["message"]

        # Check database records
        locations = list(Location.select())
        assert len(locations) == 3  # custom_loc + Home + Office

        names = {loc.name: loc for loc in locations}
        assert "My Custom Café" in names
        assert names["My Custom Café"].ha is False

        assert "Home" in names
        assert names["Home"].ha is True
        assert names["Home"].latitude == 51.7520
        assert names["Home"].longitude == -1.2577

        assert "Office" in names
        assert names["Office"].ha is True
        assert names["Office"].latitude == 51.5074

        assert "Old HA Zone" not in names

        meta = SyncMetadata.get_or_none(SyncMetadata.table_name == "ha_locations")
        assert meta is not None
        assert meta.status == "success"
        assert meta.records_count == 2


@patch("app.sync.ha_sync.HomeAssistantClient.fetch_zones")
def test_sync_ha_locations_auth_error(mock_fetch: MagicMock, app: Flask) -> None:
    """Test sync_ha_locations handles DataSourceAuthError."""
    with app.app_context(), patch.dict(os.environ, {"SUPERVISOR_TOKEN": "mock-token"}):
        mock_fetch.side_effect = DataSourceAuthError("Invalid token")
        res = sync_ha_locations(app)
        assert res["status"] == "error"
        assert "Invalid token" in res["message"]


@patch("app.sync.ha_sync.HomeAssistantClient.fetch_zones")
def test_sync_ha_locations_connection_error(mock_fetch: MagicMock, app: Flask) -> None:
    """Test sync_ha_locations handles DataSourceConnectionError."""
    with app.app_context(), patch.dict(os.environ, {"SUPERVISOR_TOKEN": "mock-token"}):
        mock_fetch.side_effect = DataSourceConnectionError("Network down")
        res = sync_ha_locations(app)
        assert res["status"] == "error"
        assert "Network or connection error" in res["message"]


@patch("app.sync.ha_sync.HomeAssistantClient.fetch_zones")
def test_sync_ha_locations_empty_zones_clears_all_ha(
    mock_fetch: MagicMock, app: Flask
) -> None:
    """Test sync_ha_locations removes all HA records when Home Assistant returns 0 zones."""
    with app.app_context(), patch.dict(os.environ, {"SUPERVISOR_TOKEN": "mock-token"}):
        Location.create(name="Custom Place", latitude=51.5, longitude=-0.1, ha=False)
        Location.create(name="Old HA Zone", latitude=51.6, longitude=-0.2, ha=True)

        mock_fetch.return_value = []
        res = sync_ha_locations(app)
        assert res["status"] == "success"
        assert res["records"] == 0

        remaining = list(Location.select())
        assert len(remaining) == 1
        assert remaining[0].name == "Custom Place"
        assert remaining[0].ha is False


@patch("app.sync.ha_sync.HomeAssistantClient.fetch_zones")
def test_sync_ha_locations_generic_exception(mock_fetch: MagicMock, app: Flask) -> None:
    """Test sync_ha_locations handles unexpected exceptions."""
    with app.app_context(), patch.dict(os.environ, {"SUPERVISOR_TOKEN": "mock-token"}):
        mock_fetch.side_effect = RuntimeError("Disk full")
        res = sync_ha_locations(app)
        assert res["status"] == "error"
        assert "Unexpected error" in res["message"]


@patch("app.sync.ha_sync.HomeAssistantClient.fetch_zones")
def test_sync_table_and_sync_all_with_ha(mock_fetch: MagicMock, app: Flask) -> None:
    """Test sync_table and sync_all dispatchers for ha_locations."""
    with app.app_context(), patch.dict(os.environ, {"SUPERVISOR_TOKEN": "mock-token"}):
        mock_fetch.return_value = [
            {
                "entity_id": "zone.home",
                "name": "Home",
                "latitude": 51.5,
                "longitude": -0.1,
            }
        ]

        res = sync_table("ha_locations", app=app)
        assert res["status"] == "success"
        assert res["records"] == 1

        all_res = sync_all(app=app)
        assert "ha_locations" in all_res["tables"]


@patch("app.sync.ha_sync.HomeAssistantClient.fetch_zones")
def test_sync_endpoints_ha_locations(
    mock_fetch: MagicMock, client: FlaskClient, app: Flask
) -> None:
    """Test POST /config/db/sync/ha_locations and POST /api/sync/ha_locations."""
    with patch.dict(os.environ, {"SUPERVISOR_TOKEN": "mock-token"}):
        mock_fetch.return_value = [
            {
                "entity_id": "zone.central",
                "name": "Central Hub",
                "latitude": 51.5,
                "longitude": -0.1,
            }
        ]

        # Config db sync route
        resp1 = client.post("/config/db/sync/ha_locations")
        assert resp1.status_code == 200
        data1 = resp1.get_json()
        assert data1["success"] is True
        assert data1["table"] == "ha_locations"
        assert data1["records"] == 1

        # API sync route
        resp2 = client.post("/api/sync/ha_locations")
        assert resp2.status_code == 200
        data2 = resp2.get_json()
        assert data2["status"] == "success"
        assert data2["records"] == 1
