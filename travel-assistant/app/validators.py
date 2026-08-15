"""Credential validation services for Travel Assistant.

Provides live verification functions for external APIs and cloud services,
including Bus Open Data Service (BODS), AWS S3 bucket storage, National Rail
LDBWS (via OpenAPI/Bravado and SOAP), and OpenAI-compatible services.
"""

from typing import Any, Dict, Optional, Tuple
import requests
import boto3
from botocore.config import Config
from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    BotoCoreError,
)
from bods_client.client import BODSClient
from bods_client.models.base import APIError as BodsAPIError
from openai import (
    OpenAI,
    AuthenticationError as OpenAIAuthError,
    APIConnectionError as OpenAIConnError,
    APITimeoutError as OpenAITimeoutError,
    APIError as OpenAIError,
)

# Standard default endpoints
DEFAULT_LDBWS_BASE = "https://realtime.nationalrail.co.uk/LDBWS"
DEFAULT_OPENAI_BASE = "https://api.openai.com/v1"


def validate_bus_api_key(api_key: str, timeout: float = 5.0) -> Tuple[bool, str]:
    """Validate Bus Open Data Service (BODS) API key.

    Args:
        api_key: The BODS API key or token to verify.
        timeout: Request timeout in seconds.

    Returns:
        A tuple of (is_valid, message).
    """
    cleaned_key = (api_key or "").strip()
    if not cleaned_key:
        return False, "Bus API key is empty."

    try:
        client = BODSClient(api_key=cleaned_key)
        # Query datasets with a limit of 1 to verify authentication
        response = client.get_timetable_datasets()
        if isinstance(response, BodsAPIError):
            if response.status_code in (401, 403):
                return False, "Invalid Bus API key or unauthorised access."
            return (
                False,
                f"Bus API error ({response.status_code}): {response.reason}",
            )
        return True, "Bus API key is valid and active."
    except requests.exceptions.Timeout:
        return False, "Connection timed out connecting to Bus Open Data Service."
    except requests.exceptions.RequestException as exc:
        return (
            False,
            f"Unable to connect to Bus Open Data Service: {str(exc)}",
        )
    except Exception as exc:
        return False, f"Bus validation error: {str(exc)}"


def validate_train_s3_bucket(
    bucket: str,
    region: Optional[str] = None,
    access_key: Optional[str] = None,
    secret_key: Optional[str] = None,
    timeout: float = 5.0,
) -> Tuple[bool, str]:
    """Validate AWS S3 bucket connectivity, existence, and permissions.

    Args:
        bucket: The name of the S3 bucket.
        region: AWS region name (e.g. eu-west-2).
        access_key: AWS access key ID.
        secret_key: AWS secret access key.
        timeout: Network timeout in seconds.

    Returns:
        A tuple of (is_valid, message).
    """
    cleaned_bucket = (bucket or "").strip()
    if not cleaned_bucket:
        return False, "S3 bucket name is required."

    cleaned_region = (region or "").strip() or "eu-west-2"
    cleaned_access = (access_key or "").strip() or None
    cleaned_secret = (secret_key or "").strip() or None

    try:
        session = boto3.Session(
            aws_access_key_id=cleaned_access,
            aws_secret_access_key=cleaned_secret,
            region_name=cleaned_region,
        )
        s3 = session.client(
            "s3",
            config=Config(
                connect_timeout=timeout,
                read_timeout=timeout,
                retries={"max_attempts": 1},
            ),
        )
        s3.head_bucket(Bucket=cleaned_bucket)
        return True, f"S3 bucket '{cleaned_bucket}' is valid and accessible."
    except ClientError as exc:
        error_code = str(exc.response.get("Error", {}).get("Code", ""))
        if error_code in ("404", "NoSuchBucket", "NotFound"):
            return False, f"S3 bucket '{cleaned_bucket}' does not exist (404)."
        if error_code in ("403", "AccessDenied"):
            return (
                False,
                f"Access denied for S3 bucket '{cleaned_bucket}' (403). Check credentials.",
            )
        if error_code in ("301", "PermanentRedirect"):
            return (
                False,
                f"S3 bucket '{cleaned_bucket}' exists in a different region.",
            )
        error_msg = exc.response.get("Error", {}).get("Message", str(exc))
        return False, f"S3 bucket error ({error_code}): {error_msg}"
    except ConnectTimeoutError:
        return False, "Connection timed out connecting to AWS S3."
    except EndpointConnectionError:
        return False, "Unable to connect to AWS S3 endpoint."
    except BotoCoreError as exc:
        return False, f"AWS S3 error: {str(exc)}"
    except Exception as exc:
        return False, f"S3 validation error: {str(exc)}"


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


def validate_open_api_key(
    api_key: str,
    base_url: Optional[str] = None,
    timeout: float = 5.0,
) -> Tuple[bool, str]:
    """Validate OpenAI or OpenAI-compatible API key.

    Args:
        api_key: The API secret key.
        base_url: Optional custom API endpoint base URL.
        timeout: Request timeout in seconds.

    Returns:
        A tuple of (is_valid, message).
    """
    cleaned_key = (api_key or "").strip()
    if not cleaned_key:
        return False, "Open API key is empty."

    cleaned_base = (base_url or "").strip() or None

    try:
        client = OpenAI(
            api_key=cleaned_key,
            base_url=cleaned_base,
            timeout=timeout,
        )
        # Attempt to list models to confirm token validity
        client.models.list()
        return True, "Open API credentials are valid and active."
    except OpenAIAuthError:
        return False, "Invalid Open API key or unauthorised access."
    except OpenAITimeoutError:
        return False, "Connection timed out connecting to Open API service."
    except OpenAIConnError:
        endpoint_display = cleaned_base or DEFAULT_OPENAI_BASE
        return False, f"Unable to connect to Open API endpoint ({endpoint_display})."
    except OpenAIError as exc:
        return False, f"Open API error: {getattr(exc, 'message', str(exc))}"
    except Exception as exc:
        return False, f"Open API validation error: {str(exc)}"


def validate_service_credentials(
    service: str,
    payload: Dict[str, Any],
    timeout: float = 5.0,
) -> Tuple[bool, str]:
    """Dispatch credential validation to the appropriate service handler.

    Args:
        service: Name of the service ('bus', 'train_s3', 'train_live', 'open_api').
        payload: Dictionary containing credential values.
        timeout: Network timeout in seconds.

    Returns:
        A tuple of (is_valid, message).
    """
    service_normalised = (service or "").lower().strip()

    if service_normalised == "bus":
        return validate_bus_api_key(
            api_key=payload.get("bus_api_key", ""),
            timeout=timeout,
        )

    if service_normalised in ("train_s3", "train-s3", "s3"):
        return validate_train_s3_bucket(
            bucket=payload.get("train_s3_bucket", ""),
            region=payload.get("train_s3_region"),
            access_key=payload.get("train_s3_access_key"),
            secret_key=payload.get("train_s3_secret_key"),
            timeout=timeout,
        )

    if service_normalised in ("train_live", "train-live", "ldbws"):
        return validate_train_live_token(
            api_key=payload.get("train_live_api_key", ""),
            endpoint=payload.get("train_live_endpoint"),
            timeout=timeout,
        )

    if service_normalised in ("open_api", "open-api", "openai"):
        return validate_open_api_key(
            api_key=payload.get("open_api_key", ""),
            base_url=payload.get("open_api_base_url"),
            timeout=timeout,
        )

    return False, f"Unknown service: '{service}'."
