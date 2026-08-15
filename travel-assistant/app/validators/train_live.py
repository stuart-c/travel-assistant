"""National Rail Darwin / LDBWS live train API token validator."""

from typing import Optional, Tuple
import requests

from app.validators.constants import DEFAULT_LDBWS_BASE


def validate_train_live_token(
    api_key: str,
    endpoint: Optional[str] = None,
    timeout: float = 5.0,
) -> Tuple[bool, str]:
    """Validate Live Train API token against National Rail LDBWS OpenAPI / SOAP.

    Args:
        api_key: Darwin or National Rail token/key.
        endpoint: Custom endpoint or service URL.
        timeout: Network timeout in seconds.

    Returns:
        A tuple of (is_valid, message).
    """
    cleaned_key = (api_key or "").strip()
    if not cleaned_key:
        return False, "Live train API key / token is empty."

    cleaned_endpoint = (endpoint or "").strip()

    # Legacy SOAP endpoint check if explicitly configured with .asmx
    if ".asmx" in cleaned_endpoint:
        soap_url = cleaned_endpoint
        soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
               xmlns:typ="http://thalesgroup.com/RTTI/2013-11-28/Token/types"
               xmlns:ldb="http://thalesgroup.com/RTTI/2017-10-01/ldb/">
  <soap:Header>
    <typ:AccessToken>
      <typ:TokenValue>{cleaned_key}</typ:TokenValue>
    </typ:AccessToken>
  </soap:Header>
  <soap:Body>
    <ldb:GetDepartureBoardRequest>
      <ldb:numRows>1</ldb:numRows>
      <ldb:crs>WAT</ldb:crs>
    </ldb:GetDepartureBoardRequest>
  </soap:Body>
</soap:Envelope>"""
        try:
            resp = requests.post(
                soap_url,
                data=soap_body,
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    "SOAPAction": "http://thalesgroup.com/RTTI/2012-01-13/ldb/GetDepartureBoard",
                },
                timeout=timeout,
            )
            if resp.status_code == 200 and "soap:Fault" not in resp.text:
                return True, "Train live credentials are valid and active."
            if "Invalid Token" in resp.text or resp.status_code in (401, 403):
                return False, "Invalid train live token or unauthorised access."
            return (
                False,
                f"Train live service responded with status {resp.status_code}.",
            )
        except requests.exceptions.Timeout:
            return False, "Connection timed out connecting to train live SOAP service."
        except requests.exceptions.RequestException as exc:
            return False, f"Unable to connect to train live service: {str(exc)}"

    # Default to National Rail LDBWS OpenAPI REST endpoint
    base_url = (cleaned_endpoint if cleaned_endpoint else DEFAULT_LDBWS_BASE).rstrip(
        "/"
    )
    if "/api/" not in base_url:
        test_url = f"{base_url}/api/20220120/GetDepartureBoard/WAT"
    else:
        test_url = (
            f"{base_url}/GetDepartureBoard/WAT"
            if base_url.endswith("20220120")
            else base_url
        )

    try:
        # OpenAPI LDBWS uses Basic Authentication: Authorization: Basic Base64(token:)
        response = requests.get(
            test_url,
            params={"numRows": 1},
            auth=(cleaned_key, ""),
            headers={"Accept": "application/json"},
            timeout=timeout,
        )
        if response.status_code == 200:
            return True, "Train live credentials are valid and active."
        if response.status_code in (401, 403):
            return False, "Invalid train live token or unauthorised access."
        if response.status_code == 404:
            return False, f"Train live endpoint not found (404): {test_url}"
        return (
            False,
            f"Train live API error ({response.status_code}): {response.text[:120]}",
        )
    except requests.exceptions.Timeout:
        return False, "Connection timed out connecting to Live Train API."
    except requests.exceptions.RequestException as exc:
        return False, f"Unable to connect to Live Train API: {str(exc)}"
    except Exception as exc:
        return False, f"Train live validation error: {str(exc)}"
