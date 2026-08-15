"""Bus Open Data Service (BODS) API key validator."""

from typing import Optional, Tuple
import requests

from app.validators.constants import DEFAULT_BODS_BASE


def validate_bus_api_key(
    api_key: str,
    base_url: Optional[str] = None,
    timeout: float = 5.0,
) -> Tuple[bool, str]:
    """Validate Bus Open Data Service (BODS) API key.

    Args:
        api_key: The BODS API key or token to verify.
        base_url: Optional base URL for the BODS API.
        timeout: Request timeout in seconds.

    Returns:
        A tuple of (is_valid, message).
    """
    cleaned_key = (api_key or "").strip()
    if not cleaned_key:
        return False, "Bus API key is empty."

    endpoint = (base_url or DEFAULT_BODS_BASE).rstrip("/")
    if not endpoint.endswith("/dataset"):
        test_url = f"{endpoint}/dataset/"
    else:
        test_url = endpoint

    try:
        response = requests.get(
            test_url,
            params={"api_key": cleaned_key, "limit": 1},
            headers={"Accept": "application/json"},
            timeout=timeout,
        )
        if response.status_code == 200:
            return True, "Bus API key is valid and active."
        if response.status_code in (401, 403):
            return False, "Invalid Bus API key or unauthorised access."
        return (
            False,
            f"Bus API error ({response.status_code}): {response.text[:120]}",
        )
    except requests.exceptions.Timeout:
        return False, "Connection timed out connecting to Bus Open Data Service."
    except requests.exceptions.RequestException as exc:
        return (
            False,
            f"Unable to connect to Bus Open Data Service: {str(exc)}",
        )
    except Exception as exc:
        return False, f"Bus validation error: {str(exc)}"
