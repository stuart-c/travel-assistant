"""OpenAI / OpenAI-compatible API key and model discovery validator."""

from typing import List, Optional, Tuple
from openai import (
    OpenAI,
    AuthenticationError as OpenAIAuthError,
    APIConnectionError as OpenAIConnError,
    APITimeoutError as OpenAITimeoutError,
    APIError as OpenAIError,
)

from app.validators.constants import (
    DEFAULT_OPENAI_BASE,
    DEFAULT_OPENAI_MODELS,
    EXCLUDED_MODEL_PREFIXES,
    EXCLUDED_MODEL_SUBSTRINGS,
    PRIORITY_MODELS,
)


def filter_chat_models(raw_models: List[str]) -> List[str]:
    """Filter and prioritise conversational / chat completion models.

    Excludes embedding, audio, TTS, whisper, and moderation models, while
    prioritising standard conversational models.

    Args:
        raw_models: List of model ID strings returned by the API.

    Returns:
        Sorted list of chat-compatible model ID strings.
    """
    if not raw_models:
        return []

    filtered: List[str] = []
    for model_id in raw_models:
        cleaned_id = model_id.strip()
        if not cleaned_id:
            continue
        lower_id = cleaned_id.lower()

        if any(lower_id.startswith(p) for p in EXCLUDED_MODEL_PREFIXES):
            continue
        if any(sub in lower_id for sub in EXCLUDED_MODEL_SUBSTRINGS):
            continue
        filtered.append(cleaned_id)

    candidates = filtered if filtered else [m.strip() for m in raw_models if m.strip()]

    def sort_key(model_name: str) -> Tuple[int, str]:
        lower = model_name.lower()
        if lower in PRIORITY_MODELS:
            return (PRIORITY_MODELS.index(lower), lower)
        if lower.startswith("gpt-") or lower.startswith("o"):
            return (len(PRIORITY_MODELS), lower)
        return (len(PRIORITY_MODELS) + 1, lower)

    return sorted(list(dict.fromkeys(candidates)), key=sort_key)


def validate_open_api_key(
    api_key: str,
    base_url: Optional[str] = None,
    timeout: float = 5.0,
) -> Tuple[bool, str, List[str]]:
    """Validate OpenAI or OpenAI-compatible API key and retrieve chat models.

    Args:
        api_key: The API secret key.
        base_url: Optional custom API endpoint base URL.
        timeout: Request timeout in seconds.

    Returns:
        A tuple of (is_valid, message, chat_models).
    """
    cleaned_key = (api_key or "").strip()
    if not cleaned_key:
        return False, "Open API key is empty.", []

    cleaned_base = (base_url or "").strip() or None

    try:
        client = OpenAI(
            api_key=cleaned_key,
            base_url=cleaned_base,
            timeout=timeout,
        )
        # Attempt to list models to confirm token validity and extract model options
        models_response = client.models.list()
        raw_models: List[str] = []
        for model in models_response:
            model_id = getattr(model, "id", None)
            if model_id:
                raw_models.append(str(model_id))

        filtered_models = filter_chat_models(raw_models)
        models = filtered_models if filtered_models else DEFAULT_OPENAI_MODELS

        return True, "Open API credentials are valid and active.", models
    except OpenAIAuthError:
        return False, "Invalid Open API key or unauthorised access.", []
    except OpenAITimeoutError:
        return False, "Connection timed out connecting to Open API service.", []
    except OpenAIConnError:
        endpoint_display = cleaned_base or DEFAULT_OPENAI_BASE
        return (
            False,
            f"Unable to connect to Open API endpoint ({endpoint_display}).",
            [],
        )
    except OpenAIError as exc:
        return False, f"Open API error: {getattr(exc, 'message', str(exc))}", []
    except Exception as exc:
        return False, f"Open API validation error: {str(exc)}", []
