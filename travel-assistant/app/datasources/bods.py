"""Client library for UK Bus Open Data Service (BODS) REST API."""

from typing import Any, Dict, List, Optional, Tuple
import requests

from app.datasources.base import BaseDataSource
from app.datasources.exceptions import (
    DataSourceAuthError,
    DataSourceConfigError,
    DataSourceConnectionError,
    DataSourceError,
    DataSourceRateLimitError,
)
from app.models.setting import Setting

DEFAULT_BODS_BASE_URL = "https://data.bus-data.dft.gov.uk/api/v1/dataset"


class BodsClient(BaseDataSource):
    """Datasource client for the UK Bus Open Data Service (BODS)."""

    provider_name: str = "bods"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BODS_BASE_URL,
        timeout: float = 5.0,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.base_url = base_url.rstrip("/") if base_url else DEFAULT_BODS_BASE_URL
        self.timeout = float(timeout)

    @classmethod
    def from_settings(cls, settings: Optional[Any] = None) -> "BodsClient":
        """Instantiate BodsClient with credentials loaded from Setting model or provider."""
        getter = (
            settings.get_val
            if hasattr(settings, "get_val")
            else (settings.get if hasattr(settings, "get") else Setting.get_val)
        )
        return cls(api_key=getter("bus_api_key", ""))

    def validate_credentials(self) -> Dict[str, Any]:
        """Validate the BODS API key against the dataset endpoint."""
        valid, message = self.validate_tuple()
        return {"valid": valid, "message": message}

    def validate_tuple(self) -> Tuple[bool, str]:
        """Validate BODS API key returning a (valid, message) tuple."""
        if not self.api_key:
            return False, "Bus API key is empty. Please enter a valid API key."

        endpoint = (
            self.base_url
            if "/dataset" in self.base_url
            else f"{self.base_url}/dataset/"
        )
        params = {"api_key": self.api_key, "limit": 1}

        try:
            response = requests.get(endpoint, params=params, timeout=self.timeout)

            if response.status_code == 200:
                return True, "Bus API key is valid and active."
            elif response.status_code in (401, 403):
                return (
                    False,
                    f"Invalid Bus API key or unauthorised access (HTTP {response.status_code}).",
                )
            elif response.status_code == 429:
                return False, "BODS rate limit exceeded. Please try again later."
            else:
                return (
                    False,
                    f"Bus API returned unexpected status code {response.status_code}.",
                )
        except requests.exceptions.Timeout:
            return (
                False,
                f"Bus API validation request timed out after {self.timeout}s.",
            )
        except requests.exceptions.RequestException as e:
            return False, f"Network error during Bus API validation: {str(e)}"
        except Exception as e:
            return False, f"Unexpected error during Bus API validation: {str(e)}"

    def fetch_routes(self, limit: int = 25) -> List[Dict[str, Any]]:
        """Fetch active bus routes from BODS datasets."""
        if not self.api_key:
            raise DataSourceConfigError(
                "Bus API key is not configured.", provider=self.provider_name
            )

        url = (
            self.base_url
            if "/dataset" in self.base_url
            else f"{self.base_url}/dataset/"
        )
        params = {"api_key": self.api_key, "limit": limit, "status": "published"}

        try:
            response = requests.get(url, params=params, timeout=self.timeout)
            if response.status_code in (401, 403):
                raise DataSourceAuthError(
                    f"BODS authentication failed (HTTP {response.status_code}): "
                    "Invalid Bus API key.",
                    provider=self.provider_name,
                )
            elif response.status_code == 429:
                raise DataSourceRateLimitError(
                    "BODS rate limit exceeded.", provider=self.provider_name
                )
            response.raise_for_status()

            data = response.json()
            results = data.get("results", [])
            routes: List[Dict[str, Any]] = []

            for item in results:
                name = item.get("name", "").strip()
                nocs = item.get("noc", [])
                operator_code = nocs[0] if nocs and isinstance(nocs, list) else None
                description = item.get("description", "") or item.get("comment", "")
                operator_name = item.get("operator_name")

                lines = item.get("lines", [])
                if lines and isinstance(lines, list):
                    for line in lines:
                        line_name = (
                            line if isinstance(line, str) else str(line)
                        ).strip()
                        if not line_name:
                            continue
                        routes.append(
                            {
                                "route_number": line_name,
                                "operator_name": operator_name or name,
                                "operator_code": operator_code,
                                "origin": item.get("origin"),
                                "destination": item.get("destination"),
                                "description": description,
                            }
                        )
            return routes

        except requests.exceptions.Timeout as e:
            raise DataSourceConnectionError(
                f"BODS connection timed out: {str(e)}", provider=self.provider_name
            ) from e
        except requests.exceptions.RequestException as e:
            raise DataSourceConnectionError(
                f"Network error connecting to BODS: {str(e)}",
                provider=self.provider_name,
            ) from e
        except DataSourceError:
            raise
        except Exception as e:
            raise DataSourceError(
                f"Unexpected error fetching routes from BODS: {str(e)}",
                provider=self.provider_name,
            ) from e
