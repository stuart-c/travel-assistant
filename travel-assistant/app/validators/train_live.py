"""Validator for National Rail Darwin credentials (delegates to TrainLiveClient)."""

from typing import Optional, Tuple

from app.datasources.train_live import (
    DEFAULT_DARWIN_ENDPOINT,
    TrainLiveClient,
)


def validate_train_live_token(
    api_key: str,
    endpoint: Optional[str] = None,
    timeout: float = 5.0,
) -> Tuple[bool, str]:
    """Validate live train departure board API credentials against National Rail Darwin.

    Args:
        api_key: The Darwin LDBWS access token / API key.
        endpoint: Custom endpoint URL or Darwin ASMX SOAP URL.
        timeout: Request timeout in seconds.

    Returns:
        Tuple of (is_valid, message).
    """
    client = TrainLiveClient(
        api_key=api_key,
        endpoint=endpoint or DEFAULT_DARWIN_ENDPOINT,
        timeout=timeout,
    )
    return client.validate_tuple()


__all__ = ["validate_train_live_token"]
