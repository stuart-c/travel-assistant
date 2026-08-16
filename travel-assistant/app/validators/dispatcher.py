"""Service credentials validation dispatcher."""

from typing import Any, Dict, Tuple

from app.datasources.bods import BodsClient, DEFAULT_BODS_BASE_URL
from app.datasources.google_maps import GoogleMapsClient
from app.datasources.openai import DEFAULT_OPENAI_BASE_URL, OpenAIClient
from app.datasources.train_live import DEFAULT_DARWIN_ENDPOINT, TrainLiveClient
from app.datasources.train_s3 import DEFAULT_S3_REGION, TrainS3Client


def validate_service_credentials(
    service: str,
    payload: Dict[str, Any],
    timeout: float = 5.0,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Dispatch credential validation to the appropriate datasource client.

    Args:
        service: Name of the service ('bus', 'train_s3', 'train_live', 'open_api', 'google_maps').
        payload: Dictionary containing credential values.
        timeout: Network timeout in seconds.

    Returns:
        A tuple of (is_valid, message, extra_data).
    """
    service_normalised = (service or "").lower().strip()

    if service_normalised == "bus":
        client = BodsClient(
            api_key=payload.get("bus_api_key", ""),
            base_url=payload.get("bus_api_base_url") or DEFAULT_BODS_BASE_URL,
            timeout=timeout,
        )
        valid, msg = client.validate_tuple()
        return valid, msg, {}

    if service_normalised == "train_s3":
        client = TrainS3Client(
            bucket_name=payload.get("train_s3_bucket", ""),
            region=payload.get("train_s3_region") or DEFAULT_S3_REGION,
            access_key=payload.get("train_s3_access_key"),
            secret_key=payload.get("train_s3_secret_key"),
            timeout=timeout,
        )
        valid, msg = client.validate_tuple()
        return valid, msg, {}

    if service_normalised == "train_live":
        client = TrainLiveClient(
            api_key=payload.get("train_live_api_key", ""),
            endpoint=payload.get("train_live_endpoint") or DEFAULT_DARWIN_ENDPOINT,
            timeout=timeout,
        )
        valid, msg = client.validate_tuple()
        return valid, msg, {}

    if service_normalised == "open_api":
        client = OpenAIClient(
            api_key=payload.get("open_api_key", ""),
            base_url=payload.get("open_api_base_url") or DEFAULT_OPENAI_BASE_URL,
            timeout=timeout,
        )
        valid, msg, models = client.validate_tuple()
        return valid, msg, {"models": models}

    if service_normalised == "google_maps":
        client = GoogleMapsClient(
            api_key=payload.get("google_maps_api_key", ""),
            region=payload.get("google_maps_region") or "uk",
            timeout=timeout,
        )
        valid, msg = client.validate_tuple()
        return valid, msg, {}

    return False, f"Unknown service: '{service}'.", {}


__all__ = ["validate_service_credentials"]
