"""Validator for Bus Open Data Service (BODS) credentials (delegates to BodsClient)."""

from typing import Optional, Tuple

from app.datasources.bods import BodsClient, DEFAULT_BODS_BASE_URL


def validate_bus_api_key(
    api_key: str,
    base_url: Optional[str] = None,
    timeout: float = 5.0,
) -> Tuple[bool, str]:
    """Validate Bus Open Data Service (BODS) API key against the live dataset endpoint.

    Args:
        api_key: The BODS API key string.
        base_url: Optional custom base URL for the dataset endpoint.
        timeout: Request timeout in seconds.

    Returns:
        Tuple of (is_valid, message).
    """
    client = BodsClient(
        api_key=api_key,
        base_url=base_url or DEFAULT_BODS_BASE_URL,
        timeout=timeout,
    )
    return client.validate_tuple()
