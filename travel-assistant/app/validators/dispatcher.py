"""Service credentials validation dispatcher."""

from typing import Any, Dict, Tuple

from app.validators.bus import validate_bus_api_key
from app.validators.openai import validate_open_api_key
from app.validators.s3 import validate_train_s3_bucket
from app.validators.train_live import validate_train_live_token


def validate_service_credentials(
    service: str,
    payload: Dict[str, Any],
    timeout: float = 5.0,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Dispatch credential validation to the appropriate service handler.

    Args:
        service: Name of the service ('bus', 'train_s3', 'train_live', 'open_api').
        payload: Dictionary containing credential values.
        timeout: Network timeout in seconds.

    Returns:
        A tuple of (is_valid, message, extra_data).
    """
    service_normalised = (service or "").lower().strip()

    if service_normalised == "bus":
        valid, msg = validate_bus_api_key(
            api_key=payload.get("bus_api_key", ""),
            base_url=payload.get("bus_api_base_url"),
            timeout=timeout,
        )
        return valid, msg, {}

    if service_normalised in ("train_s3", "train-s3", "s3"):
        valid, msg = validate_train_s3_bucket(
            bucket=payload.get("train_s3_bucket", ""),
            region=payload.get("train_s3_region"),
            access_key=payload.get("train_s3_access_key"),
            secret_key=payload.get("train_s3_secret_key"),
            timeout=timeout,
        )
        return valid, msg, {}

    if service_normalised in ("train_live", "train-live", "ldbws"):
        valid, msg = validate_train_live_token(
            api_key=payload.get("train_live_api_key", ""),
            endpoint=payload.get("train_live_endpoint"),
            timeout=timeout,
        )
        return valid, msg, {}

    if service_normalised in ("open_api", "open-api", "openai"):
        valid, msg, models = validate_open_api_key(
            api_key=payload.get("open_api_key", ""),
            base_url=payload.get("open_api_base_url"),
            timeout=timeout,
        )
        return valid, msg, {"models": models}

    return False, f"Unknown service: '{service}'.", {}
