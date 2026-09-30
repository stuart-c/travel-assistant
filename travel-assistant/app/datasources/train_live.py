"""Client library for National Rail Darwin Live Departure Boards (LDBWS)."""

import json
import os
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

import httpx

from app.datasources.base import BaseDataSource
from app.datasources.exceptions import (
    DataSourceAuthError,
    DataSourceConfigError,
    DataSourceConnectionError,
    DataSourceError,
)

DEFAULT_USER_AGENT = "TravelAssistant/1.0 (HomeAssistant; Linux)"
DEFAULT_BASE_URL = "https://realtime.nationalrail.co.uk/LDBWS"
DEFAULT_SWAGGER_SCHEMA_URL = (
    "https://realtime.nationalrail.co.uk/LDBWS/static/ldbws.json"
)

OPERATION_ROUTES: Dict[str, Tuple[str, List[str], List[str]]] = {
    "GetDepartureBoard": (
        "/api/20220120/GetDepartureBoard/{crs}",
        ["crs"],
        ["numRows", "filterCrs", "filterType", "timeOffset", "timeWindow"],
    ),
    "GetDepBoardWithDetails": (
        "/api/20220120/GetDepBoardWithDetails/{crs}",
        ["crs"],
        ["numRows", "filterCrs", "filterType", "timeOffset", "timeWindow"],
    ),
    "GetArrivalBoard": (
        "/api/20220120/GetArrivalBoard/{crs}",
        ["crs"],
        ["numRows", "filterCrs", "filterType", "timeOffset", "timeWindow"],
    ),
    "GetArrBoardWithDetails": (
        "/api/20220120/GetArrBoardWithDetails/{crs}",
        ["crs"],
        ["numRows", "filterCrs", "filterType", "timeOffset", "timeWindow"],
    ),
    "GetArrivalDepartureBoard": (
        "/api/20220120/GetArrivalDepartureBoard/{crs}",
        ["crs"],
        ["numRows", "filterCrs", "filterType", "timeOffset", "timeWindow"],
    ),
    "GetArrDepBoardWithDetails": (
        "/api/20220120/GetArrDepBoardWithDetails/{crs}",
        ["crs"],
        ["numRows", "filterCrs", "filterType", "timeOffset", "timeWindow"],
    ),
    "GetFastestDepartures": (
        "/api/20220120/GetFastestDepartures/{crs}/{filterList}",
        ["crs", "filterList"],
        ["timeOffset", "timeWindow"],
    ),
    "GetFastestDeparturesWithDetails": (
        "/api/20220120/GetFastestDeparturesWithDetails/{crs}/{filterList}",
        ["crs", "filterList"],
        ["timeOffset", "timeWindow"],
    ),
    "GetNextDepartures": (
        "/api/20220120/GetNextDepartures/{crs}/{filterList}",
        ["crs", "filterList"],
        ["timeOffset", "timeWindow"],
    ),
    "GetNextDeparturesWithDetails": (
        "/api/20220120/GetNextDeparturesWithDetails/{crs}/{filterList}",
        ["crs", "filterList"],
        ["timeOffset", "timeWindow"],
    ),
    "GetServiceDetails": (
        "/api/20220120/GetServiceDetails/{serviceId}",
        ["serviceId"],
        [],
    ),
}


def get_schema_path(filename: str = "ldbws_swagger.json") -> str:
    """Determine the local path to store swagger schemas, colocated with the database."""
    try:
        from app.db.core import get_db_path

        db_path = get_db_path()
        if db_path and db_path != ":memory:":
            db_dir = os.path.dirname(db_path)
            if db_dir:
                return os.path.join(db_dir, filename)
    except Exception:
        pass

    if os.path.exists("/data") and os.access("/data", os.W_OK):
        return os.path.join("/data", filename)

    return os.path.join(os.path.abspath("instance"), filename)


def sync_swagger_schema(
    schema_path: Optional[str] = None,
    url: str = DEFAULT_SWAGGER_SCHEMA_URL,
    timeout: float = 5.0,
) -> bool:
    """Download the latest Swagger schema from the live URL and cache locally.

    Returns True if a new schema was successfully downloaded and saved, False otherwise.
    """
    target_path = schema_path or get_schema_path()
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(
                url,
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Accept": "application/json",
                },
            )
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and "paths" in data and "swagger" in data:
                    parent_dir = os.path.dirname(target_path)
                    if parent_dir:
                        os.makedirs(parent_dir, exist_ok=True)
                    with open(target_path, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
                    return True
    except Exception:
        pass
    return False


def extract_live_services(raw_data: Any) -> List[Dict[str, Any]]:
    """Extract and normalise a list of train service dictionaries from Darwin LDBWS OpenAPI responses.

    Handles:
    - DeparturesBoard dict: {"departures": [{"crs": "...", "service": {...}}]}
    - DeparturesBoardWithDetails dict: {"departures": [{"crs": "...", "service": {...}}]}
    - StationBoard dict: {"trainServices": [{...}]}
    - Nested dict: {"departuresBoard": {"departures": [...]}}
    - Pre-extracted list of services: [{"std": "...", ...}]
    - Pre-extracted list of departure items: [{"service": {...}}]
    """
    if not raw_data:
        return []

    if isinstance(raw_data, list):
        services: List[Dict[str, Any]] = []
        for item in raw_data:
            if isinstance(item, dict):
                if "service" in item and isinstance(item["service"], dict):
                    services.append(item["service"])
                else:
                    services.append(item)
        return services

    if isinstance(raw_data, dict):
        if "departures" in raw_data and isinstance(raw_data["departures"], list):
            return extract_live_services(raw_data["departures"])
        if "trainServices" in raw_data and isinstance(raw_data["trainServices"], list):
            return extract_live_services(raw_data["trainServices"])
        if "departuresBoard" in raw_data and isinstance(
            raw_data["departuresBoard"], (dict, list)
        ):
            return extract_live_services(raw_data["departuresBoard"])

    return []


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
        self.endpoint = (endpoint or "").strip()
        self.timeout = float(timeout)

    @classmethod
    def from_settings(cls, settings: Optional[Any] = None) -> "TrainLiveClient":
        """Instantiate TrainLiveClient with credentials loaded from Setting model or provider."""
        getter = cls.get_setting_getter(settings)
        return cls(
            api_key=getter("train_live_api_key", ""),
            endpoint=getter("train_live_endpoint", ""),
        )

    def _parse_endpoint(
        self, endpoint_url: Optional[str] = None
    ) -> Tuple[str, str, str]:
        """Parse configured endpoint URL into (scheme, host, base_path)."""
        ep = (endpoint_url or "").strip()
        if not ep:
            return "", "", ""

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

    def get_base_url(self) -> str:
        """Return base URL for Darwin OpenAPI requests."""
        scheme, host, base_path = self._parse_endpoint(self.endpoint)
        if scheme and host:
            return f"{scheme}://{host}{base_path}"
        return DEFAULT_BASE_URL

    def _call_operation(self, op_name: str, **kwargs: Any) -> Any:
        """Dynamically invoke an OpenAPI operation using direct HTTP requests."""
        route_spec = OPERATION_ROUTES.get(op_name)
        if route_spec is None:
            raise DataSourceConfigError(
                f"Operation '{op_name}' not found in LDBWS spec.",
                provider=self.provider_name,
            )

        path_template, path_keys, query_keys = route_spec

        kw_map = {k.lower(): v for k, v in kwargs.items() if v is not None}
        path_kwargs = {}
        for pk in path_keys:
            val = kw_map.get(pk.lower())
            if val is not None:
                path_kwargs[pk] = val
            else:
                path_kwargs[pk] = ""

        query_params = {}
        for qk in query_keys:
            val = kw_map.get(qk.lower())
            if val is not None:
                query_params[qk] = val

        base_url = self.get_base_url().rstrip("/")
        path = path_template.format(**path_kwargs)
        url = f"{base_url}{path}"

        headers = {
            "x-apikey": self.api_key,
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "application/json",
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(url, params=query_params, headers=headers)
        except httpx.TimeoutException as e:
            raise DataSourceConnectionError(
                f"National Rail Darwin LDBWS request timed out after {self.timeout}s.",
                provider=self.provider_name,
            ) from e
        except httpx.RequestError as e:
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

        if response.status_code in (401, 403):
            raise DataSourceAuthError(
                f"Unauthorised access ({response.status_code}): Invalid token.",
                provider=self.provider_name,
            )
        if response.status_code >= 400:
            raise DataSourceError(
                f"National Rail LDBWS returned HTTP {response.status_code}: {response.text}",
                provider=self.provider_name,
            )

        try:
            return response.json()
        except Exception as e:
            raise DataSourceError(
                f"Failed to parse Darwin LDBWS JSON response: {str(e)}",
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
        """Fetch arrival board for a station via OpenAPI GetArrivalBoard, falling back on error."""
        try:
            return self._call_operation(
                "GetArrivalBoard",
                crs=crs.upper().strip(),
                numRows=int(num_rows),
                filterCrs=filter_crs.upper().strip() if filter_crs else None,
                filterType=filter_type,
                timeOffset=time_offset,
                timeWindow=time_window,
            )
        except Exception:
            return self._call_operation(
                "GetDepartureBoard",
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
        self, crs: str, filter_list: Optional[Union[str, List[str]]] = None
    ) -> Dict[str, Any]:
        """Fetch fastest departures to a list of destinations, falling back to GetDepartureBoard on error."""
        clean_filter = ""
        if isinstance(filter_list, (list, tuple, set)):
            clean_filter = ",".join(str(f).upper().strip() for f in filter_list if f)
        elif filter_list is not None:
            clean_filter = str(filter_list).upper().strip()

        try:
            return self._call_operation(
                "GetFastestDepartures",
                crs=crs.upper().strip(),
                filterList=clean_filter,
            )
        except Exception:
            first_filter = clean_filter.split(",")[0].strip() if clean_filter else None
            return self._call_operation(
                "GetDepartureBoard",
                crs=crs.upper().strip(),
                numRows=10,
                filterCrs=first_filter if first_filter else None,
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
