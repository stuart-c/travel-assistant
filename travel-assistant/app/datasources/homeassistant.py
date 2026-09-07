"""Home Assistant REST API datasource client for discovering and synchronising zones."""

import os
from typing import Any, Dict, List, Optional
import requests

from app.datasources.base import BaseDataSource
from app.datasources.exceptions import (
    DataSourceAuthError,
    DataSourceConfigError,
    DataSourceConnectionError,
    DataSourceError,
)


class HomeAssistantClient(BaseDataSource):
    """Datasource client for communicating with Home Assistant Core API."""

    provider_name: str = "homeassistant"

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.token = (
            token
            or os.environ.get("SUPERVISOR_TOKEN")
            or os.environ.get("HA_TOKEN")
            or ""
        ).strip()

        # Determine base API URL
        raw_url = (
            base_url
            or os.environ.get("SUPERVISOR_URL")
            or os.environ.get("HA_URL")
            or "http://supervisor/core/api"
        ).strip()

        # Normalise URL to ensure it points to the API endpoint
        clean_url = raw_url.rstrip("/")
        if not clean_url.endswith("/api"):
            if "supervisor" in clean_url and not clean_url.endswith("/core"):
                clean_url = f"{clean_url}/core/api"
            else:
                clean_url = f"{clean_url}/api"

        self.base_url = clean_url
        self.timeout_seconds = max(1.0, timeout_seconds)

    @classmethod
    def from_settings(cls, settings: Optional[Any] = None) -> "HomeAssistantClient":
        """Initialise HomeAssistantClient from Setting model or environment."""
        getter = cls.get_setting_getter(settings)
        ha_url = None
        ha_token = None
        try:
            ha_url = getter("ha_url")
            ha_token = getter("ha_token")
        except Exception:
            pass

        return cls(base_url=ha_url, token=ha_token)

    def _get_headers(self) -> Dict[str, str]:
        """Generate HTTP headers for Home Assistant API requests."""
        if not self.token:
            raise DataSourceConfigError(
                "Home Assistant Supervisor token (SUPERVISOR_TOKEN) or HA_TOKEN not configured.",
                provider=self.provider_name,
            )
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def validate_credentials(self) -> Dict[str, Any]:
        """Validate connectivity and authentication against Home Assistant Core API."""
        headers = self._get_headers()
        try:
            url = f"{self.base_url}/config"
            resp = requests.get(url, headers=headers, timeout=self.timeout_seconds)
            if resp.status_code in (401, 403):
                raise DataSourceAuthError(
                    f"Authentication failed for Home Assistant ({resp.status_code}): {resp.text}",
                    provider=self.provider_name,
                )
            if resp.status_code != 200:
                raise DataSourceError(
                    f"Home Assistant API returned HTTP {resp.status_code}: {resp.text}",
                    provider=self.provider_name,
                )

            data = resp.json()
            location_name = data.get("location_name", "Home Assistant")
            return {
                "valid": True,
                "message": f"Successfully connected to Home Assistant ({location_name}).",
                "location_name": location_name,
                "version": data.get("version"),
                "time_zone": data.get("time_zone"),
            }
        except requests.exceptions.Timeout as exc:
            raise DataSourceConnectionError(
                f"Connection timed out contacting Home Assistant at {self.base_url}: {exc}",
                provider=self.provider_name,
            )
        except requests.exceptions.RequestException as exc:
            raise DataSourceConnectionError(
                f"Network error contacting Home Assistant at {self.base_url}: {exc}",
                provider=self.provider_name,
            )

    def fetch_zones(self) -> List[Dict[str, Any]]:
        """Query all Home Assistant zone.* entities and extract location details."""
        headers = self._get_headers()
        try:
            url = f"{self.base_url}/states"
            resp = requests.get(url, headers=headers, timeout=self.timeout_seconds)
            if resp.status_code in (401, 403):
                raise DataSourceAuthError(
                    f"Authentication failed for Home Assistant ({resp.status_code}): {resp.text}",
                    provider=self.provider_name,
                )
            if resp.status_code != 200:
                raise DataSourceError(
                    f"Home Assistant API returned HTTP {resp.status_code}: {resp.text}",
                    provider=self.provider_name,
                )

            items = resp.json()
            if not isinstance(items, list):
                raise DataSourceError(
                    "Unexpected payload format returned by Home Assistant /states endpoint.",
                    provider=self.provider_name,
                )

            zones: List[Dict[str, Any]] = []
            for entity in items:
                entity_id = entity.get("entity_id", "")
                if not entity_id.startswith("zone."):
                    continue

                attrs = entity.get("attributes", {})
                raw_lat = attrs.get("latitude")
                raw_lon = attrs.get("longitude")

                if raw_lat is None or raw_lon is None:
                    continue

                try:
                    lat = float(raw_lat)
                    lon = float(raw_lon)
                except (ValueError, TypeError):
                    continue

                if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
                    continue

                # Determine friendly display name
                name = (
                    attrs.get("friendly_name")
                    or entity.get("name")
                    or entity_id.replace("zone.", "").replace("_", " ").title()
                ).strip()

                if not name:
                    continue

                zones.append(
                    {
                        "entity_id": entity_id,
                        "name": name,
                        "latitude": lat,
                        "longitude": lon,
                        "radius": attrs.get("radius"),
                        "icon": attrs.get("icon"),
                        "passive": attrs.get("passive", False),
                    }
                )

            return zones

        except requests.exceptions.Timeout as exc:
            raise DataSourceConnectionError(
                f"Connection timed out fetching zones from Home Assistant: {exc}",
                provider=self.provider_name,
            )
        except requests.exceptions.RequestException as exc:
            raise DataSourceConnectionError(
                f"Network error fetching zones from Home Assistant: {exc}",
                provider=self.provider_name,
            )

    def get_entity_state(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve state and attributes of a Home Assistant entity by entity_id."""
        headers = self._get_headers()
        try:
            url = f"{self.base_url}/states/{entity_id.strip()}"
            resp = requests.get(url, headers=headers, timeout=self.timeout_seconds)
            if resp.status_code == 404:
                return None
            if resp.status_code in (401, 403):
                raise DataSourceAuthError(
                    f"Authentication failed for Home Assistant ({resp.status_code}): {resp.text}",
                    provider=self.provider_name,
                )
            if resp.status_code != 200:
                raise DataSourceError(
                    f"Home Assistant API returned HTTP {resp.status_code}: {resp.text}",
                    provider=self.provider_name,
                )
            return resp.json()
        except requests.exceptions.Timeout as exc:
            raise DataSourceConnectionError(
                f"Connection timed out fetching entity state for {entity_id} from Home Assistant: {exc}",
                provider=self.provider_name,
            )
        except requests.exceptions.RequestException as exc:
            raise DataSourceConnectionError(
                f"Network error fetching entity state for {entity_id} from Home Assistant: {exc}",
                provider=self.provider_name,
            )

    def call_service(
        self,
        domain: str,
        service: str,
        service_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Execute a service call against the Home Assistant Core API."""
        headers = self._get_headers()
        payload = service_data or {}
        try:
            url = f"{self.base_url}/services/{domain.strip()}/{service.strip()}"
            resp = requests.post(
                url, headers=headers, json=payload, timeout=self.timeout_seconds
            )
            if resp.status_code in (401, 403):
                raise DataSourceAuthError(
                    f"Authentication failed calling service {domain}.{service} ({resp.status_code}): {resp.text}",
                    provider=self.provider_name,
                )
            if resp.status_code not in (200, 201):
                raise DataSourceError(
                    f"Home Assistant service {domain}.{service} returned HTTP {resp.status_code}: {resp.text}",
                    provider=self.provider_name,
                )
            return True
        except requests.exceptions.Timeout as exc:
            raise DataSourceConnectionError(
                f"Connection timed out calling service {domain}.{service}: {exc}",
                provider=self.provider_name,
            )
        except requests.exceptions.RequestException as exc:
            raise DataSourceConnectionError(
                f"Network error calling service {domain}.{service}: {exc}",
                provider=self.provider_name,
            )

    def send_mobile_notification(
        self,
        title: str,
        message: str,
        service_name: str = "mobile_app_stuart_mobile",
        data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Dispatch a push notification to Stuart's mobile device with no fallback."""
        payload: Dict[str, Any] = {"message": message}
        if title:
            payload["title"] = title
        if data:
            payload["data"] = data
        return self.call_service("notify", service_name, payload)
