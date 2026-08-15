"""Validator for OpenAI API credentials and chat models (delegates to OpenAIClient)."""

from typing import List, Optional, Tuple

from app.datasources.openai import (
    DEFAULT_OPENAI_BASE_URL,
    OpenAIClient,
    filter_chat_models,
)


def validate_open_api_key(
    api_key: str,
    base_url: Optional[str] = None,
    timeout: float = 5.0,
) -> Tuple[bool, str, List[str]]:
    """Validate OpenAI API key against the models endpoint.

    Args:
        api_key: The OpenAI secret API key.
        base_url: Optional custom OpenAI base URL.
        timeout: Request timeout in seconds.

    Returns:
        Tuple of (is_valid, message, compatible_models_list).
    """
    client = OpenAIClient(
        api_key=api_key,
        base_url=base_url or DEFAULT_OPENAI_BASE_URL,
        timeout=timeout,
    )
    return client.validate_tuple()


__all__ = ["validate_open_api_key", "filter_chat_models"]
