"""Client library for National Rail Darwin Live Departure Boards (LDBWS)."""

import json
import os
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from bravado.client import SwaggerClient
from bravado.requests_client import RequestsClient
import requests

from app.datasources.base import BaseDataSource
from app.datasources.exceptions import (
    DataSourceAuthError,
    DataSourceConfigError,
    DataSourceConnectionError,
    DataSourceError,
)
from app.models.setting import Setting

DEFAULT_DARWIN_OPENAPI_ENDPOINT = "https://realtime.nationalrail.co.uk/LDBWS"
DEFAULT_DARWIN_ENDPOINT = DEFAULT_DARWIN_OPENAPI_ENDPOINT
DEFAULT_USER_AGENT = "TravelAssistant/1.0 (HomeAssistant; Linux)"
DEFAULT_SWAGGER_SCHEMA_URL = (
    "https://realtime.nationalrail.co.uk/LDBWS/static/ldbws.json"
)

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schemas", "ldbws_swagger.json")


def sync_swagger_schema(
    schema_path: str = SCHEMA_PATH,
    url: str = DEFAULT_SWAGGER_SCHEMA_URL,
    timeout: float = 5.0,
) -> bool:
    """Download the latest Swagger schema from the live URL and cache locally.

    Returns True if a new schema was successfully downloaded and saved, False otherwise.
    """
    try:
        response = requests.get(
            url,
            headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"},
            timeout=timeout,
        )
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, dict) and "paths" in data and "swagger" in data:
                os.makedirs(os.path.dirname(schema_path), exist_ok=True)
                with open(schema_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                return True
    except Exception:
        pass
    return False


class TrainLiveClient(BaseDataSource):
    """Datasource client for National Rail Darwin live train departure boards."""

    provider_name: str = "train_live"

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        timeout: float = 5.0,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.endpoint = (endpoint or DEFAULT_DARWIN_ENDPOINT).strip()
        self.timeout = float(timeout)
        self._swagger_client: Optional[SwaggerClient] = None

    @classmethod
    def from_settings(cls, settings: Optional[Any] = None) -> "TrainLiveClient":
        """Instantiate TrainLiveClient with credentials loaded from Setting model or provider."""
        getter = (
            settings.get_val
            if hasattr(settings, "get_val")
            else (settings.get if hasattr(settings, "get") else Setting.get_val)
        )
        return cls(
            api_key=getter("train_live_api_key", ""),
            endpoint=getter("train_live_endpoint", DEFAULT_DARWIN_ENDPOINT),
        )

    def _parse_endpoint(self, endpoint_url: str) -> Tuple[str, str, str]:
        """Parse configured endpoint URL into (scheme, host, base_path)."""
        ep = (endpoint_url or "").strip()
        parsed = urlparse(ep)
        scheme = parsed.scheme or "https"
        host = parsed.netloc
        base_path = parsed.path.rstrip("/")

        # Strip operation sub-paths if a specific operation URL was supplied as base URL
        changed = True
        while changed:
            changed = False
            for suffix in (
                "/GetDepartureBoard",
                "/GetDepBoardWithDetails",
                "/GetArrivalBoard",
                "/GetArrBoardWithDetails",
                "/GetArrDepBoardWithDetails",
                "/GetServiceDetails",
                "/api/20220120",
                "/api",
            ):
                if base_path.endswith(suffix):
                    base_path = base_path[: -len(suffix)].rstrip("/")
                    changed = True

        return scheme, host, base_path

    def get_swagger_client(self) -> SwaggerClient:
        """Build and cache a Bravado SwaggerClient configured with host/basePath overrides."""
        if self._swagger_client is not None:
            return self._swagger_client

        scheme, host, base_path = self._parse_endpoint(self.endpoint)

        if not os.path.exists(SCHEMA_PATH):
            sync_swagger_schema(SCHEMA_PATH)

        if not os.path.exists(SCHEMA_PATH):
            raise DataSourceConfigError(
                f"Swagger schema file not found at {SCHEMA_PATH}",
                provider=self.provider_name,
            )

        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            spec_dict = json.load(f)

        if host:
            spec_dict["host"] = host
        if base_path:
            spec_dict["basePath"] = base_path
        if scheme:
            spec_dict["schemes"] = [scheme]

        http_client = RequestsClient()
        http_client.session.headers.update(
            {
                "x-apikey": self.api_key,
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept": "application/json",
            }
        )

        self._swagger_client = SwaggerClient.from_spec(
            spec_dict,
            http_client=http_client,
            config={
                "validate_responses": False,
                "use_models": False,
                "validate_requests": False,
            },
        )
        return self._swagger_client

    def _call_operation(self, op_name: str, **kwargs: Any) -> Any:
        """Dynamically invoke a Swagger operation on the client."""
        client = self.get_swagger_client()
        clean_kwargs = {k: v for k, v in kwargs.items() if v is not None}

        operation = None
        # Check direct attribute or method on client
        if hasattr(client, op_name):
            candidate = getattr(client, op_name)
            if callable(candidate):
                operation = candidate

        # Check resource namespaces (e.g. client._20220120 or client.ldbws)
        if operation is None:
            for attr in dir(client):
                if attr.startswith("__") or attr in (
                    "swagger_spec",
                    "get_model",
                    "get_operation",
                ):
                    continue
                try:
                    namespace = getattr(client, attr)
                    if hasattr(namespace, op_name):
                        candidate = getattr(namespace, op_name)
                        if callable(candidate):
                            operation = candidate
                            break
                except Exception:
                    continue

        if operation is None:
            raise DataSourceConfigError(
                f"Swagger operation '{op_name}' not found in LDBWS spec.",
                provider=self.provider_name,
            )

        try:
            future = operation(**clean_kwargs)
            response = future.response(timeout=self.timeout)
            return response.result
        except requests.exceptions.Timeout as e:
            raise DataSourceConnectionError(
                f"National Rail Darwin LDBWS request timed out after {self.timeout}s.",
                provider=self.provider_name,
            ) from e
        except requests.exceptions.RequestException as e:
            resp = getattr(e, "response", None)
            if resp is not None:
                if resp.status_code in (401, 403):
                    raise DataSourceAuthError(
                        f"Unauthorised access ({resp.status_code}): Invalid token.",
                        provider=self.provider_name,
                    ) from e
                raise DataSourceError(
                    f"National Rail LDBWS returned HTTP {resp.status_code}: {resp.text}",
                    provider=self.provider_name,
                ) from e
            raise DataSourceConnectionError(
                f"Network error connecting to Darwin LDBWS: {str(e)}",
                provider=self.provider_name,
            ) from e
        except Exception as e:
            err_str = str(e)
            if "401" in err_str or "403" in err_str or "Unauthorized" in err_str:
                raise DataSourceAuthError(
                    f"Darwin LDBWS authentication error: {err_str}",
                    provider=self.provider_name,
                ) from e
            if "timed out" in err_str.lower():
                raise DataSourceConnectionError(
                    f"Darwin LDBWS timed out: {err_str}",
                    provider=self.provider_name,
                ) from e
            raise DataSourceError(
                f"Darwin LDBWS error: {err_str}",
                provider=self.provider_name,
            ) from e

    def get_departure_board(
        self,
        crs: str,
        num_rows: int = 10,
        filter_crs: Optional[str] = None,
        filter_type: Optional[str] = None,
        time_offset: Optional[int] = None,
        time_window: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Fetch departure board for a station via OpenAPI GetDepartureBoard."""
        return self._call_operation(
            "GetDepartureBoard",
            crs=crs.upper().strip(),
            numRows=int(num_rows),
            filterCrs=filter_crs.upper().strip() if filter_crs else None,
            filterType=filter_type,
            timeOffset=time_offset,
            timeWindow=time_window,
        )

    def get_dep_board_with_details(
        self,
        crs: str,
        num_rows: int = 10,
        filter_crs: Optional[str] = None,
        filter_type: Optional[str] = None,
        time_offset: Optional[int] = None,
        time_window: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Fetch departure board with service details and calling points."""
        return self._call_operation(
            "GetDepBoardWithDetails",
            crs=crs.upper().strip(),
            numRows=int(num_rows),
            filterCrs=filter_crs.upper().strip() if filter_crs else None,
            filterType=filter_type,
            timeOffset=time_offset,
            timeWindow=time_window,
        )

    def get_arrival_board(
        self,
        crs: str,
        num_rows: int = 10,
        filter_crs: Optional[str] = None,
        filter_type: Optional[str] = None,
        time_offset: Optional[int] = None,
        time_window: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Fetch arrival board for a station via OpenAPI GetArrivalBoard."""
        return self._call_operation(
            "GetArrivalBoard",
            crs=crs.upper().strip(),
            numRows=int(num_rows),
            filterCrs=filter_crs.upper().strip() if filter_crs else None,
            filterType=filter_type,
            timeOffset=time_offset,
            timeWindow=time_window,
        )

    def get_service_details(self, service_id: str) -> Dict[str, Any]:
        """Fetch detailed service information for a specific train service ID."""
        return self._call_operation(
            "GetServiceDetails",
            serviceid=service_id.strip(),
        )

    def get_fastest_departures(
        self, crs: str, filter_list: Optional[str] = None
    ) -> Dict[str, Any]:
        """Fetch fastest departures to a list of destinations."""
        return self._call_operation(
            "GetFastestDepartures",
            crs=crs.upper().strip(),
            filterList=filter_list,
        )

    def validate_credentials(self) -> Dict[str, Any]:
        """Validate live train departure board credentials against Darwin/LDBWS."""
        valid, message = self.validate_tuple()
        return {"valid": valid, "message": message}

    def validate_tuple(self) -> Tuple[bool, str]:
        """Validate live train credentials returning a (valid, message) tuple."""
        if not self.api_key:
            return False, "Train live API token is empty. Please enter a valid token."

        return self._validate_openapi(self.endpoint)

    def _validate_openapi(self, endpoint_url: str) -> Tuple[bool, str]:
        """Validate against a REST/OpenAPI endpoint using Swagger operation."""
        try:
            res = self.get_departure_board(crs="CBG", num_rows=1)
            if isinstance(res, dict) and (
                "locationName" in res or "trainServices" in res or "crs" in res
            ):
                return (
                    True,
                    "Train live token and base URL are valid and active (OpenAPI).",
                )
            return True, "Train live token is valid and active (OpenAPI)."
        except DataSourceAuthError:
            return (
                False,
                "Invalid train live token or unauthorised access (HTTP 401/403).",
            )
        except DataSourceConnectionError as e:
            if "timed out" in str(e).lower():
                return (
                    False,
                    f"Train live validation request timed out after {self.timeout}s.",
                )
            return (
                False,
                f"Network error during train live validation: {str(e)}",
            )
        except Exception as e:
            err_str = str(e)
            if "404" in err_str:
                return (
                    False,
                    "OpenAPI endpoint not found (HTTP 404). Please check the base URL.",
                )
            return (
                False,
                f"Unexpected error during train live validation: {err_str}",
            )

    def fetch_departures(self, crs_code: str, num_rows: int = 10) -> Dict[str, Any]:
        """Fetch live train departures for a given CRS station code."""
        if not self.api_key:
            raise DataSourceConfigError(
                "Train live API token is not configured.", provider=self.provider_name
            )

        try:
            data = self.get_dep_board_with_details(crs=crs_code, num_rows=num_rows)
            return {
                "crs": crs_code.upper().strip(),
                "location_name": data.get("locationName") or crs_code.upper().strip(),
                "train_services": data.get("trainServices") or [],
                "raw_data": data,
                "status": "success",
            }
        except DataSourceError:
            raise
        except Exception as e:
            raise DataSourceError(
                f"Failed to fetch departures via OpenAPI: {str(e)}",
                provider=self.provider_name,
            ) from e
