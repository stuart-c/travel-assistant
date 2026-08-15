"""Client library for National Rail Darwin Live Departure Boards (LDBWS)."""

from typing import Any, Dict, Optional, Tuple
import requests

from app.datasources.base import BaseDataSource
from app.datasources.exceptions import (
    DataSourceAuthError,
    DataSourceConfigError,
    DataSourceConnectionError,
    DataSourceError,
)
from app.db.settings import SettingsRepository

DEFAULT_DARWIN_OPENAPI_ENDPOINT = (
    "https://api.nationalrail.co.uk/OpenLDBWS/api/20220120"
)
DEFAULT_DARWIN_SOAP_ENDPOINT = (
    "https://lite.realtime.nationalrail.co.uk/OpenLDBWS/ldb11.asmx"
)
DEFAULT_DARWIN_ENDPOINT = DEFAULT_DARWIN_OPENAPI_ENDPOINT


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

    @classmethod
    def from_settings(
        cls, settings_repo: Optional[SettingsRepository] = None
    ) -> "TrainLiveClient":
        """Instantiate TrainLiveClient with credentials loaded from SettingsRepository."""
        repo = settings_repo or SettingsRepository()
        return cls(
            api_key=repo.get("train_live_api_key", ""),
            endpoint=repo.get("train_live_endpoint", DEFAULT_DARWIN_ENDPOINT),
        )

    def validate_credentials(self) -> Dict[str, Any]:
        """Validate live train departure board credentials against Darwin/LDBWS."""
        valid, message = self.validate_tuple()
        return {"valid": valid, "message": message}

    def validate_tuple(self) -> Tuple[bool, str]:
        """Validate live train credentials returning a (valid, message) tuple."""
        if not self.api_key:
            return False, "Train live API token is empty. Please enter a valid token."

        is_soap = "asmx" in self.endpoint.lower() or "soap" in self.endpoint.lower()
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
        """Validate against a REST/OpenAPI proxy endpoint."""
        url = (
            endpoint_url
            if "/GetDepartureBoard" in endpoint_url
            else f"{endpoint_url.rstrip('/')}/GetDepartureBoard/WAT"
        )
        headers = {
            "x-apikey": self.api_key,
            "Accept": "application/json",
        }

        try:
            response = requests.get(
                url, headers=headers, params={"numRows": 1}, timeout=self.timeout
            )

            if response.status_code == 200:
                return True, "Train live token is valid and active (OpenAPI)."
            elif response.status_code in (401, 403):
                return (
                    False,
                    "Invalid train live token or unauthorised access "
                    f"(HTTP {response.status_code}).",
                )
            elif response.status_code == 404:
                return (
                    False,
                    "OpenAPI endpoint not found (404). Falling back to SOAP or check URL.",
                )
            else:
                return (
                    False,
                    f"Train live API returned unexpected status code {response.status_code}.",
                )
        except requests.exceptions.Timeout:
            return (
                False,
                f"Train live validation request timed out after {self.timeout}s.",
            )
        except requests.exceptions.RequestException as e:
            return (
                False,
                f"Network error during train live validation: {str(e)}",
            )
        except Exception as e:
            return (
                False,
                f"Unexpected error during train live validation: {str(e)}",
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
                    "crs": crs_code.upper(),
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
