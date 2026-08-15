"""Client library for OpenAI API and compatible LLM endpoints."""

from typing import Any, Dict, List, Optional, Tuple
from openai import (
    APIConnectionError as OpenAIConnError,
    APIError as OpenAIError,
    APITimeoutError as OpenAITimeoutError,
    AuthenticationError as OpenAIAuthError,
    OpenAI,
)

from app.datasources.base import BaseDataSource
from app.datasources.exceptions import (
    DataSourceAuthError,
    DataSourceConfigError,
    DataSourceConnectionError,
    DataSourceError,
)
from app.db.settings import SettingsRepository

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"

EXCLUDED_MODEL_PREFIXES = (
    "text-embedding",
    "text-moderation",
    "omni-moderation",
    "whisper",
    "tts",
    "dall-e",
    "davinci",
    "babbage",
)

EXCLUDED_MODEL_SUBSTRINGS = (
    "embedding",
    "moderation",
    "realtime",
    "audio",
    "transcribe",
    "voice",
)

PRIORITY_MODELS = [
    "gpt-4o-mini",
    "gpt-4o",
    "o3-mini",
]


def filter_chat_models(raw_model_ids: List[str]) -> List[str]:
    """Filter raw model IDs down to chat/completion models, sorted with common choices first."""
    if not raw_model_ids:
        return []

    chat_models: List[str] = []
    for m in raw_model_ids:
        if not m or not isinstance(m, str) or not m.strip():
            continue
        m_lower = m.lower().strip()
        if any(m_lower.startswith(prefix) for prefix in EXCLUDED_MODEL_PREFIXES):
            continue
        if any(sub in m_lower for sub in EXCLUDED_MODEL_SUBSTRINGS):
            continue
        chat_models.append(m.strip())

    priority_found = [m for m in PRIORITY_MODELS if m in chat_models]
    others = sorted([m for m in chat_models if m not in PRIORITY_MODELS])
    result = priority_found + others

    if not result:
        # Fallback to non-empty raw candidates if all were excluded
        cleaned_raw = [
            m.strip() for m in raw_model_ids if m and isinstance(m, str) and m.strip()
        ]
        return cleaned_raw

    return result


class OpenAIClient(BaseDataSource):
    """Datasource client for OpenAI API and custom OpenAI-compatible endpoints."""

    provider_name: str = "openai"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 5.0,
        openai_client: Optional[OpenAI] = None,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.base_url = (
            (base_url or DEFAULT_OPENAI_BASE_URL).rstrip("/")
            if base_url
            else DEFAULT_OPENAI_BASE_URL
        )
        self.timeout = float(timeout)
        self._openai_client = openai_client

    @classmethod
    def from_settings(
        cls, settings_repo: Optional[SettingsRepository] = None
    ) -> "OpenAIClient":
        """Instantiate OpenAIClient with credentials loaded from SettingsRepository."""
        repo = settings_repo or SettingsRepository()
        return cls(
            api_key=repo.get("open_api_key", ""),
            base_url=repo.get("open_api_base_url", DEFAULT_OPENAI_BASE_URL),
        )

    def get_client(self) -> OpenAI:
        """Create or return the configured OpenAI client."""
        if self._openai_client is not None:
            return self._openai_client
        client_kwargs: Dict[str, Any] = {
            "api_key": self.api_key or "sk-placeholder",
            "timeout": self.timeout,
        }
        if self.base_url and self.base_url != DEFAULT_OPENAI_BASE_URL:
            client_kwargs["base_url"] = self.base_url
        return OpenAI(**client_kwargs)

    def validate_credentials(self) -> Dict[str, Any]:
        """Validate OpenAI API key against the models endpoint."""
        valid, message, models = self.validate_tuple()
        return {"valid": valid, "message": message, "models": models}

    def validate_tuple(self) -> Tuple[bool, str, List[str]]:
        """Validate OpenAI key returning a (valid, message, models) tuple."""
        if not self.api_key:
            return False, "Open API key is empty. Please enter a valid key.", []

        try:
            client = self.get_client()
            response = client.models.list()
            raw_models = [
                item.id for item in response if hasattr(item, "id") and item.id
            ]

            if not raw_models:
                return (
                    True,
                    "Open API key is valid and active. No compatible chat models discovered.",
                    ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"],
                )

            filtered = filter_chat_models(raw_models)
            return (
                True,
                f"Open API key is valid and active. Found {len(filtered)} "
                "compatible chat model(s).",
                filtered,
            )
        except OpenAIAuthError as e:
            status_code = getattr(e, "status_code", 401)
            return (
                False,
                f"Invalid Open API key or unauthorised access (HTTP {status_code}).",
                [],
            )
        except OpenAITimeoutError:
            return (
                False,
                f"Open API validation request timed out after {self.timeout}s.",
                [],
            )
        except OpenAIConnError:
            return (
                False,
                f"Unable to connect to Open API endpoint: '{self.base_url}'. Check your base URL.",
                [],
            )
        except OpenAIError as e:
            return False, f"Open API error: {str(e)}", []
        except Exception as e:
            return False, f"Open API validation error: {str(e)}", []

    def list_chat_models(self) -> List[str]:
        """Fetch and return list of available chat models."""
        if not self.api_key:
            raise DataSourceConfigError(
                "OpenAI API key is not configured.", provider=self.provider_name
            )

        try:
            client = self.get_client()
            response = client.models.list()
            raw_models = [
                item.id for item in response if hasattr(item, "id") and item.id
            ]
            return filter_chat_models(raw_models)
        except OpenAIAuthError as e:
            raise DataSourceAuthError(
                f"OpenAI authentication failed: {str(e)}", provider=self.provider_name
            ) from e
        except OpenAITimeoutError as e:
            raise DataSourceConnectionError(
                f"OpenAI connection timed out: {str(e)}", provider=self.provider_name
            ) from e
        except OpenAIConnError as e:
            raise DataSourceConnectionError(
                f"Network error connecting to OpenAI: {str(e)}",
                provider=self.provider_name,
            ) from e
        except OpenAIError as e:
            raise DataSourceError(
                f"OpenAI API error: {str(e)}", provider=self.provider_name
            ) from e
        except Exception as e:
            raise DataSourceError(
                f"Unexpected error listing OpenAI models: {str(e)}",
                provider=self.provider_name,
            ) from e
