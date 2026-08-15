"""Unit tests for OpenAIClient."""

from unittest.mock import MagicMock, patch
import pytest
from openai import (
    APIConnectionError as OpenAIConnError,
    APIError as OpenAIError,
    APITimeoutError as OpenAITimeoutError,
    AuthenticationError as OpenAIAuthError,
)
from flask import Flask

from app.datasources.openai import (
    DEFAULT_OPENAI_BASE_URL,
    OpenAIClient,
    filter_chat_models,
)
from app.datasources.exceptions import (
    DataSourceAuthError,
    DataSourceConfigError,
    DataSourceConnectionError,
    DataSourceError,
)
from app.db.settings import SettingsRepository


def test_openai_from_settings(app: Flask) -> None:
    """Test OpenAIClient initialisation from SettingsRepository."""
    with app.app_context():
        repo = SettingsRepository()
        repo.set("open_api_key", "sk-test-12345")
        repo.set("open_api_base_url", "https://api.openai.com/v1")

        client = OpenAIClient.from_settings(repo)
        assert client.api_key == "sk-test-12345"
        assert client.base_url == DEFAULT_OPENAI_BASE_URL
        assert client.provider_name == "openai"


def test_openai_get_client_custom_and_cached() -> None:
    """Test OpenAIClient get_client caching and custom base_url configuration."""
    mock_injected = MagicMock()
    cached_client = OpenAIClient(api_key="k", openai_client=mock_injected)
    assert cached_client.get_client() is mock_injected

    custom_client = OpenAIClient(api_key="k", base_url="https://custom.ai/v1")
    created = custom_client.get_client()
    assert created is not None


def test_filter_chat_models_logic() -> None:
    """Test filter_chat_models excludes non-chat models and sorts priorities."""
    raw = [
        "whisper-1",
        "dall-e-3",
        "text-embedding-3-small",
        "tts-1",
        "custom-fine-tune",
        "gpt-4o",
        "gpt-3.5-turbo",
        "gpt-4o-mini",
        "babbage-002",
    ]
    filtered = filter_chat_models(raw)
    assert "whisper-1" not in filtered
    assert "dall-e-3" not in filtered
    assert "text-embedding-3-small" not in filtered
    assert filtered[0] == "gpt-4o-mini"
    assert filtered[1] == "gpt-4o"
    assert "custom-fine-tune" in filtered

    # Empty list
    assert filter_chat_models([]) == []


def test_openai_validate_credentials_empty() -> None:
    """Test validate_credentials returns invalid on empty key."""
    client = OpenAIClient(api_key="")
    res = client.validate_credentials()
    assert res["valid"] is False
    assert "empty" in res["message"]
    assert res["models"] == []


@patch("app.datasources.openai.OpenAI")
def test_openai_validate_credentials_success(mock_openai_cls: MagicMock) -> None:
    """Test validate_credentials with successful model retrieval."""
    mock_instance = MagicMock()
    mock_m1 = MagicMock(id="gpt-4o-mini")
    mock_m2 = MagicMock(id="whisper-1")
    mock_instance.models.list.return_value = [mock_m1, mock_m2]
    mock_openai_cls.return_value = mock_instance

    client = OpenAIClient(api_key="valid-sk")
    res = client.validate_credentials()
    assert res["valid"] is True
    assert "Found 1" in res["message"]
    assert res["models"] == ["gpt-4o-mini"]


@patch("app.datasources.openai.OpenAI")
def test_openai_validate_credentials_empty_models_fallback(
    mock_openai_cls: MagicMock,
) -> None:
    """Test validate_credentials returns fallback models when list is empty."""
    mock_instance = MagicMock()
    mock_instance.models.list.return_value = []
    mock_openai_cls.return_value = mock_instance

    client = OpenAIClient(api_key="valid-sk")
    res = client.validate_credentials()
    assert res["valid"] is True
    assert "gpt-4o-mini" in res["models"]


@patch("app.datasources.openai.OpenAI")
def test_openai_validate_credentials_errors(mock_openai_cls: MagicMock) -> None:
    """Test validate_credentials error handling."""
    mock_instance = MagicMock()
    mock_openai_cls.return_value = mock_instance

    client = OpenAIClient(api_key="test-key")

    # 401 Auth error
    mock_instance.models.list.side_effect = OpenAIAuthError(
        "Invalid key", response=MagicMock(status_code=401), body=None
    )
    assert client.validate_credentials()["valid"] is False

    # Timeout
    mock_instance.models.list.side_effect = OpenAITimeoutError(request=MagicMock())
    assert client.validate_credentials()["valid"] is False

    # Connection error
    mock_instance.models.list.side_effect = OpenAIConnError(request=MagicMock())
    assert client.validate_credentials()["valid"] is False

    # Generic OpenAIError
    mock_instance.models.list.side_effect = OpenAIError(
        "Rate limit", request=MagicMock(), body=None
    )
    assert client.validate_credentials()["valid"] is False

    # Generic Exception
    mock_instance.models.list.side_effect = RuntimeError("Crash")
    assert client.validate_credentials()["valid"] is False


def test_openai_list_chat_models_empty_key() -> None:
    """Test list_chat_models raises DataSourceConfigError when key is empty."""
    client = OpenAIClient(api_key="")
    with pytest.raises(DataSourceConfigError):
        client.list_chat_models()


@patch("app.datasources.openai.OpenAI")
def test_openai_list_chat_models_success(mock_openai_cls: MagicMock) -> None:
    """Test list_chat_models returns filtered models."""
    mock_instance = MagicMock()
    mock_instance.models.list.return_value = [
        MagicMock(id="gpt-4o"),
        MagicMock(id="tts-1"),
    ]
    mock_openai_cls.return_value = mock_instance

    client = OpenAIClient(api_key="valid-sk")
    models = client.list_chat_models()
    assert models == ["gpt-4o"]


@patch("app.datasources.openai.OpenAI")
def test_openai_list_chat_models_errors(mock_openai_cls: MagicMock) -> None:
    """Test list_chat_models error handling."""
    mock_instance = MagicMock()
    mock_openai_cls.return_value = mock_instance
    client = OpenAIClient(api_key="test-key")

    # Auth error
    mock_instance.models.list.side_effect = OpenAIAuthError(
        "Invalid", response=MagicMock(), body=None
    )
    with pytest.raises(DataSourceAuthError):
        client.list_chat_models()

    # Timeout
    mock_instance.models.list.side_effect = OpenAITimeoutError(request=MagicMock())
    with pytest.raises(DataSourceConnectionError):
        client.list_chat_models()

    # Connection error
    mock_instance.models.list.side_effect = OpenAIConnError(request=MagicMock())
    with pytest.raises(DataSourceConnectionError):
        client.list_chat_models()

    # API Error
    mock_instance.models.list.side_effect = OpenAIError(
        "API Err", request=MagicMock(), body=None
    )
    with pytest.raises(DataSourceError):
        client.list_chat_models()

    # Generic Exception
    mock_instance.models.list.side_effect = RuntimeError("Crash")
    with pytest.raises(DataSourceError):
        client.list_chat_models()
