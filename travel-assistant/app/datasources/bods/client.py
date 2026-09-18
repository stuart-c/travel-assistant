"""Client library for UK Bus Open Data Service (BODS) REST API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple
import requests

from app.datasources.base import BaseDataSource
from app.datasources.bods.corridor_builder import merge_timetable_into_collection
from app.datasources.bods.transxchange_parser import (
    parse_transxchange_dataset,
    parse_transxchange_xml,
)
from app.datasources.exceptions import (
    DataSourceAuthError,
    DataSourceConfigError,
    DataSourceConnectionError,
    DataSourceError,
    DataSourceRateLimitError,
)

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
        getter = cls.get_setting_getter(settings)
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

    def fetch_routes(
        self,
        limit: Optional[int] = 25,
        page_size: int = 50,
    ) -> List[Dict[str, Any]]:
        """Fetch active bus routes from BODS datasets with pagination support."""
        if not self.api_key:
            raise DataSourceConfigError(
                "Bus API key is not configured.", provider=self.provider_name
            )

        url = (
            self.base_url
            if "/dataset" in self.base_url
            else f"{self.base_url}/dataset/"
        )
        offset = 0
        batch_limit = min(limit, page_size) if limit is not None else page_size
        results: List[Dict[str, Any]] = []

        try:
            while True:
                params: Dict[str, Any] = {
                    "api_key": self.api_key,
                    "status": "published",
                    "limit": batch_limit,
                    "offset": offset,
                }
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
                page_results = data.get("results", [])
                if not page_results:
                    break

                results.extend(page_results)
                offset += len(page_results)

                if limit is not None and len(results) >= limit:
                    results = results[:limit]
                    break

                if not data.get("next"):
                    break

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
                f"BODS connection timed out: {str(e)}",
                provider=self.provider_name,
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

    def download_dataset_file(self, download_url: str) -> bytes:
        """Download raw dataset file content (TransXChange XML or ZIP archive)."""
        if not self.api_key:
            raise DataSourceConfigError(
                "Bus API key is not configured.", provider=self.provider_name
            )
        if not download_url:
            raise DataSourceError(
                "Dataset download URL is empty.", provider=self.provider_name
            )

        try:
            params = {}
            if "api_key" not in download_url and "?" not in download_url:
                params["api_key"] = self.api_key

            response = requests.get(download_url, params=params, timeout=self.timeout)
            if response.status_code in (401, 403):
                raise DataSourceAuthError(
                    f"BODS authentication failed (HTTP {response.status_code}) "
                    "downloading dataset.",
                    provider=self.provider_name,
                )
            elif response.status_code == 429:
                raise DataSourceRateLimitError(
                    "BODS rate limit exceeded downloading dataset.",
                    provider=self.provider_name,
                )
            response.raise_for_status()
            return response.content

        except requests.exceptions.Timeout as e:
            raise DataSourceConnectionError(
                f"BODS download timed out: {str(e)}",
                provider=self.provider_name,
            ) from e
        except requests.exceptions.RequestException as e:
            raise DataSourceConnectionError(
                f"Network error downloading dataset from BODS: {str(e)}",
                provider=self.provider_name,
            ) from e
        except DataSourceError:
            raise
        except Exception as e:
            raise DataSourceError(
                f"Unexpected error downloading dataset from BODS: {str(e)}",
                provider=self.provider_name,
            ) from e

    parse_transxchange_xml = staticmethod(parse_transxchange_xml)
    parse_transxchange_dataset = staticmethod(parse_transxchange_dataset)

    def fetch_timetables(
        self,
        target_stop_codes: Optional[Set[str]] = None,
        admin_areas: Optional[List[str]] = None,
        stop_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
        limit: Optional[int] = None,
        page_size: int = 50,
    ) -> List[Dict[str, Any]]:
        """Fetch and parse published bus timetables covering target stops from BODS.

        Supports multi-page pagination across all available datasets and merges
        trips for identical routes and operating day profiles.
        """
        if not self.api_key:
            raise DataSourceConfigError(
                "Bus API key is not configured.", provider=self.provider_name
            )

        url = (
            self.base_url
            if "/dataset" in self.base_url
            else f"{self.base_url}/dataset/"
        )
        offset = 0
        batch_limit = min(limit, page_size) if limit is not None else page_size
        results: List[Dict[str, Any]] = []

        try:
            while True:
                params: Dict[str, Any] = {
                    "api_key": self.api_key,
                    "status": "published",
                    "limit": batch_limit,
                    "offset": offset,
                }
                if admin_areas:
                    clean_areas = [
                        str(a).strip() for a in admin_areas if str(a).strip()
                    ]
                    if clean_areas:
                        params["adminArea"] = ",".join(clean_areas)

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
                page_results = data.get("results", [])
                if not page_results:
                    break

                results.extend(page_results)
                offset += len(page_results)

                if limit is not None and len(results) >= limit:
                    results = results[:limit]
                    break

                if not data.get("next"):
                    break

            timetables_by_key: Dict[Tuple[str, Tuple[bool, ...]], Dict[str, Any]] = {}

            for item in results:
                dl_url = item.get("url")
                if not dl_url:
                    continue

                try:
                    file_bytes = self.download_dataset_file(dl_url)
                    parsed_tt = self.parse_transxchange_dataset(
                        file_bytes,
                        target_stop_codes=target_stop_codes,
                        stop_lookup=stop_lookup,
                    )
                    merge_timetable_into_collection(timetables_by_key, parsed_tt)
                except (
                    DataSourceAuthError,
                    DataSourceConfigError,
                    DataSourceRateLimitError,
                ):
                    raise
                except Exception:
                    continue

            return list(timetables_by_key.values())

        except requests.exceptions.Timeout as e:
            raise DataSourceConnectionError(
                f"BODS connection timed out: {str(e)}",
                provider=self.provider_name,
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
                f"Unexpected error fetching timetables from BODS: {str(e)}",
                provider=self.provider_name,
            ) from e
