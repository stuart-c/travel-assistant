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
DEFAULT_DARWIN_SOAP_ENDPOINT = (
    "https://lite.realtime.nationalrail.co.uk/OpenLDBWS/ldb11.asmx"
)
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

    def _parse_endpoint(self, endpoint_url: str) -> Tuple[str, str, str, bool]:
        """Parse configured endpoint URL into (scheme, host, base_path, is_soap)."""
        ep = (endpoint_url or "").strip()
        is_soap = "asmx" in ep.lower() or "soap" in ep.lower()
        if is_soap:
            return "", "", ep, True

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

        return scheme, host, base_path, False

    def get_swagger_client(self) -> SwaggerClient:
        """Build and cache a Bravado SwaggerClient configured with host/basePath overrides."""
        if self._swagger_client is not None:
            return self._swagger_client

        scheme, host, base_path, is_soap = self._parse_endpoint(self.endpoint)
        if is_soap:
            raise DataSourceConfigError(
                "SOAP endpoint cannot be used with SwaggerClient.",
                provider=self.provider_name,
            )

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

    def get_departure_board(
        self,
        crs: str,
        num_rows: int = 10,
        filter_crs: Optional[str] = None,
        filter_type: Optional[str] = None,
        time_offset: Optional[int] = None,
        time_window: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Fetch station departure board via OpenAPI."""
        params: Dict[str, Any] = {"crs": crs.upper().strip(), "numRows": int(num_rows)}
        if filter_crs:
            params["filterCrs"] = filter_crs.upper().strip()
        if filter_type:
            params["filterType"] = filter_type
        if time_offset is not None:
            params["timeOffset"] = int(time_offset)
        if time_window is not None:
            params["timeWindow"] = int(time_window)

        client = self.get_swagger_client()
        return self._execute_operation(client._20220120.GetDepartureBoard, **params)

    def get_dep_board_with_details(
        self,
        crs: str,
        num_rows: int = 10,
        filter_crs: Optional[str] = None,
        filter_type: Optional[str] = None,
        time_offset: Optional[int] = None,
        time_window: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Fetch station departure board with calling points via OpenAPI."""
        params: Dict[str, Any] = {"crs": crs.upper().strip(), "numRows": int(num_rows)}
        if filter_crs:
            params["filterCrs"] = filter_crs.upper().strip()
        if filter_type:
            params["filterType"] = filter_type
        if time_offset is not None:
            params["timeOffset"] = int(time_offset)
        if time_window is not None:
            params["timeWindow"] = int(time_window)

        client = self.get_swagger_client()
        return self._execute_operation(
            client._20220120.GetDepBoardWithDetails, **params
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
        """Fetch station arrival board via OpenAPI."""
        params: Dict[str, Any] = {"crs": crs.upper().strip(), "numRows": int(num_rows)}
        if filter_crs:
            params["filterCrs"] = filter_crs.upper().strip()
        if filter_type:
            params["filterType"] = filter_type
        if time_offset is not None:
            params["timeOffset"] = int(time_offset)
        if time_window is not None:
            params["timeWindow"] = int(time_window)

        client = self.get_swagger_client()
        return self._execute_operation(client._20220120.GetArrivalBoard, **params)

    def get_service_details(self, service_id: str) -> Dict[str, Any]:
        """Fetch full service details by Darwin service ID via OpenAPI."""
        client = self.get_swagger_client()
        return self._execute_operation(
            client._20220120.GetServiceDetails, serviceid=service_id
        )

    def _execute_operation(self, operation: Any, **kwargs: Any) -> Dict[str, Any]:
        """Execute a Bravado operation and map exceptions to domain exceptions."""
        try:
            call = operation(**kwargs)
            res = call.response(timeout=self.timeout)
            return res.result or {}
        except Exception as e:
            err_str = str(e)
            status_code = getattr(getattr(e, "response", None), "status_code", None)
            if status_code in (401, 403) or "401" in err_str or "403" in err_str:
                raise DataSourceAuthError(
                    f"National Rail LDBWS token rejected or unauthorised ({err_str}).",
                    provider=self.provider_name,
                ) from e
            if "timeout" in err_str.lower() or "timed out" in err_str.lower():
                raise DataSourceConnectionError(
                    f"Darwin service timed out: {err_str}",
                    provider=self.provider_name,
                ) from e
            if (
                "connection" in err_str.lower()
                or "network" in err_str.lower()
                or "failed" in err_str.lower()
            ):
                raise DataSourceConnectionError(
                    f"Network error connecting to Darwin LDBWS: {err_str}",
                    provider=self.provider_name,
                ) from e
            raise DataSourceError(
                f"Darwin LDBWS error: {err_str}",
                provider=self.provider_name,
            ) from e

    def validate_credentials(self) -> Dict[str, Any]:
        """Validate live train departure board credentials against Darwin/LDBWS."""
        valid, message = self.validate_tuple()
        return {"valid": valid, "message": message}

    def validate_tuple(self) -> Tuple[bool, str]:
        """Validate live train credentials returning a (valid, message) tuple."""
        if not self.api_key:
            return False, "Train live API token is empty. Please enter a valid token."

        scheme, host, base_path, is_soap = self._parse_endpoint(self.endpoint)
        if is_soap:
            return self._validate_soap(self.endpoint)

        valid, msg = self._validate_openapi(self.endpoint)
        if not valid and "404" in msg:
            # Fallback to SOAP
            soap_valid, soap_msg = self._validate_soap(DEFAULT_DARWIN_SOAP_ENDPOINT)
            if soap_valid:
                return True, soap_msg
        return valid, msg

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
                    "OpenAPI endpoint not found (404). Falling back to SOAP or check URL.",
                )
            return (
                False,
                f"Unexpected error during train live validation: {err_str}",
            )

    def _validate_soap(self, soap_url: str) -> Tuple[bool, str]:
        """Validate directly via Darwin SOAP protocol."""
        soap_envelope = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
               xmlns:typ="http://thalesgroup.com/RTTI/2013-11-28/Token/types"
               xmlns:ldb="http://thalesgroup.com/RTTI/2017-10-01/ldb/">
  <soap:Header>
    <typ:AccessToken>
      <typ:TokenValue>{self.api_key}</typ:TokenValue>
    </typ:AccessToken>
  </soap:Header>
  <soap:Body>
    <ldb:GetDepartureBoardRequest>
      <ldb:numRows>1</ldb:numRows>
      <ldb:crs>PAD</ldb:crs>
    </ldb:GetDepartureBoardRequest>
  </soap:Body>
</soap:Envelope>"""

        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "http://thalesgroup.com/RTTI/2012-01-13/ldb/GetDepartureBoard",
            "User-Agent": DEFAULT_USER_AGENT,
        }

        try:
            response = requests.post(
                soap_url,
                data=soap_envelope.encode("utf-8"),
                headers=headers,
                timeout=self.timeout,
            )

            if response.status_code == 200 and "GetStationBoardResult" in response.text:
                return True, "Train live token is valid and active (SOAP)."
            elif (
                "Invalid token" in response.text
                or "faultstring" in response.text
                or "Unauthorized" in response.text
            ):
                return (
                    False,
                    "Invalid train live token (SOAP authentication failed).",
                )
            elif response.status_code in (401, 403):
                return (
                    False,
                    f"Train live SOAP endpoint returned HTTP {response.status_code}.",
                )
            else:
                return (
                    False,
                    "Train live SOAP endpoint returned unexpected status code "
                    f"{response.status_code}.",
                )
        except requests.exceptions.Timeout:
            return (
                False,
                f"Train live SOAP request timed out after {self.timeout}s.",
            )
        except requests.exceptions.RequestException as e:
            return (
                False,
                f"Network error during train live SOAP validation: {str(e)}",
            )
        except Exception as e:
            return (
                False,
                f"Unexpected error during train live SOAP validation: {str(e)}",
            )

    def fetch_departures(self, crs_code: str, num_rows: int = 10) -> Dict[str, Any]:
        """Fetch live train departures for a given CRS station code."""
        if not self.api_key:
            raise DataSourceConfigError(
                "Train live API token is not configured.", provider=self.provider_name
            )

        scheme, host, base_path, is_soap = self._parse_endpoint(self.endpoint)
        if not is_soap:
            try:
                data = self.get_dep_board_with_details(crs=crs_code, num_rows=num_rows)
                return {
                    "crs": crs_code.upper().strip(),
                    "location_name": data.get("locationName")
                    or crs_code.upper().strip(),
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

        # Legacy Darwin SOAP protocol
        soap_envelope = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
               xmlns:typ="http://thalesgroup.com/RTTI/2013-11-28/Token/types"
               xmlns:ldb="http://thalesgroup.com/RTTI/2017-10-01/ldb/">
  <soap:Header>
    <typ:AccessToken>
      <typ:TokenValue>{self.api_key}</typ:TokenValue>
    </typ:AccessToken>
  </soap:Header>
  <soap:Body>
    <ldb:GetDepartureBoardRequest>
      <ldb:numRows>{num_rows}</ldb:numRows>
      <ldb:crs>{crs_code.upper().strip()}</ldb:crs>
    </ldb:GetDepartureBoardRequest>
  </soap:Body>
</soap:Envelope>"""

        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "http://thalesgroup.com/RTTI/2012-01-13/ldb/GetDepartureBoard",
            "User-Agent": DEFAULT_USER_AGENT,
        }

        endpoint_url = (
            self.endpoint
            if "asmx" in self.endpoint.lower() or "soap" in self.endpoint.lower()
            else DEFAULT_DARWIN_SOAP_ENDPOINT
        )

        try:
            response = requests.post(
                endpoint_url,
                data=soap_envelope.encode("utf-8"),
                headers=headers,
                timeout=self.timeout,
            )

            if response.status_code == 200 and "GetStationBoardResult" in response.text:
                return {
                    "crs": crs_code.upper().strip(),
                    "raw_xml": response.text,
                    "status": "success",
                }
            elif "Invalid token" in response.text or response.status_code in (401, 403):
                raise DataSourceAuthError(
                    "National Rail LDBWS token rejected or unauthorised.",
                    provider=self.provider_name,
                )
            else:
                raise DataSourceError(
                    f"Failed to fetch departures: HTTP {response.status_code}",
                    provider=self.provider_name,
                )
        except requests.exceptions.Timeout as e:
            raise DataSourceConnectionError(
                f"Darwin service timed out: {str(e)}", provider=self.provider_name
            ) from e
        except requests.exceptions.RequestException as e:
            raise DataSourceConnectionError(
                f"Network error connecting to Darwin: {str(e)}",
                provider=self.provider_name,
            ) from e
        except DataSourceError:
            raise
        except Exception as e:
            raise DataSourceError(
                f"Unexpected error fetching departures: {str(e)}",
                provider=self.provider_name,
            ) from e
