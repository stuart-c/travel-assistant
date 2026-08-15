"""Validator for Google Maps Platform credentials (delegates to GoogleMapsClient)."""

from typing import Optional, Tuple

from app.datasources.google_maps import GoogleMapsClient


def validate_google_maps_api_key(
    api_key: str,
    region: Optional[str] = None,
    timeout: float = 5.0,
) -> Tuple[bool, str]:
    """Validate Google Maps API key using a zero-cost parameter probe.

    Args:
        api_key: Google Maps Platform API key.
        region: Optional default region bias (e.g. 'uk').
        timeout: Request timeout in seconds.

    Returns:
        Tuple of (is_valid, message).
    """
    client = GoogleMapsClient(
        api_key=api_key,
        region=region or "uk",
        timeout=timeout,
    )
    return client.validate_tuple()


__all__ = ["validate_google_maps_api_key"]
