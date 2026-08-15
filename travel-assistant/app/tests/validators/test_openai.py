"""Unit tests for OpenAI validation and chat model filtering."""

from unittest.mock import MagicMock, patch
from openai import (
    AuthenticationError as OpenAIAuthError,
    APIConnectionError as OpenAIConnError,
    APITimeoutError as OpenAITimeoutError,
    APIError as OpenAIError,
)

from app.validators import filter_chat_models, validate_open_api_key


def test_filter_chat_models() -> None:
    """Test filtering and ordering of chat models from raw model list."""
    assert filter_chat_models([]) == []

    raw_models = [
        "",
        "   ",
        "text-embedding-3-small",
        "custom-moderation-model",
        "custom-realtime-voice",
        "custom-audio-transcribe",
        "whisper-1",
        "tts-1",
        "dall-e-3",
        "text-moderation-007",
        "gpt-4o",
        "gpt-5-future",
        "o4-mini",
        "gpt-3.5-turbo",
        "gpt-4o-mini",
        "omni-moderation-latest",
        "davinci-002",
        "babbage-002",
        "o3-mini",
        "claude-3-5-sonnet",
        "llama-3.1-70b",
    ]
    filtered = filter_chat_models(raw_models)

    assert "text-embedding-3-small" not in filtered
    assert "custom-moderation-model" not in filtered
    assert "custom-realtime-voice" not in filtered
    assert "custom-audio-transcribe" not in filtered
    assert "whisper-1" not in filtered
    assert "tts-1" not in filtered
    assert "dall-e-3" not in filtered
    assert "text-moderation-007" not in filtered
    assert "omni-moderation-latest" not in filtered
    assert "davinci-002" not in filtered
    assert "babbage-002" not in filtered

    assert filtered[0] == "gpt-4o-mini"
    assert filtered[1] == "gpt-4o"
    assert filtered[2] == "o3-mini"
    assert "gpt-3.5-turbo" in filtered
    assert "gpt-5-future" in filtered
    assert "o4-mini" in filtered
    assert "claude-3-5-sonnet" in filtered
    assert "llama-3.1-70b" in filtered

    all_excluded = ["text-embedding-ada-002", "whisper-medium"]
    fallback_result = filter_chat_models(all_excluded)
    assert len(fallback_result) == 2


def test_validate_open_api_key_empty() -> None:
    """Test Open API validation with empty key."""
    valid, message, models = validate_open_api_key("")
    assert not valid
    assert "Open API key is empty" in message
    assert models == []


@patch("app.datasources.openai.OpenAI")
def test_validate_open_api_key_success(mock_openai_cls: MagicMock) -> None:
    """Test Open API validation success with model extraction."""
    mock_instance = MagicMock()
    mock_model_1 = MagicMock()
    mock_model_1.id = "gpt-4o-mini"
    mock_model_2 = MagicMock()
    mock_model_2.id = "gpt-4o"
    mock_model_3 = MagicMock()
    mock_model_3.id = "text-embedding-3-large"
    mock_instance.models.list.return_value = [mock_model_1, mock_model_2, mock_model_3]
    mock_openai_cls.return_value = mock_instance

    valid, message, models = validate_open_api_key("sk-valid123")
    assert valid
    assert "valid and active" in message
    assert "gpt-4o-mini" in models
    assert "gpt-4o" in models
    assert "text-embedding-3-large" not in models


@patch("app.datasources.openai.OpenAI")
def test_validate_open_api_key_success_empty_models(mock_openai_cls: MagicMock) -> None:
    """Test Open API validation success when API returns no model objects."""
    mock_instance = MagicMock()
    mock_instance.models.list.return_value = []
    mock_openai_cls.return_value = mock_instance

    valid, message, models = validate_open_api_key("sk-valid123")
    assert valid
    assert "valid and active" in message
    assert "gpt-4o-mini" in models


@patch("app.datasources.openai.OpenAI")
def test_validate_open_api_key_unauthorised(mock_openai_cls: MagicMock) -> None:
    """Test Open API validation unauthorised key."""
    mock_instance = MagicMock()
    mock_response = MagicMock(status_code=401)
    mock_instance.models.list.side_effect = OpenAIAuthError(
        "Invalid API key", response=mock_response, body=None
    )
    mock_openai_cls.return_value = mock_instance

    valid, message, models = validate_open_api_key("sk-invalid")
    assert not valid
    assert "Invalid Open API key or unauthorised access" in message
    assert models == []


@patch("app.datasources.openai.OpenAI")
def test_validate_open_api_key_timeout(mock_openai_cls: MagicMock) -> None:
    """Test Open API validation timeout."""
    mock_instance = MagicMock()
    mock_instance.models.list.side_effect = OpenAITimeoutError(request=MagicMock())
    mock_openai_cls.return_value = mock_instance

    valid, message, models = validate_open_api_key("sk-timeout")
    assert not valid
    assert "timed out" in message.lower()
    assert models == []


@patch("app.datasources.openai.OpenAI")
def test_validate_open_api_key_conn_error(mock_openai_cls: MagicMock) -> None:
    """Test Open API validation connection error."""
    mock_instance = MagicMock()
    mock_instance.models.list.side_effect = OpenAIConnError(request=MagicMock())
    mock_openai_cls.return_value = mock_instance

    valid, message, models = validate_open_api_key(
        "sk-conn-err", base_url="https://custom.endpoint.ai/v1"
    )
    assert not valid
    assert "Unable to connect to Open API endpoint" in message
    assert models == []


@patch("app.datasources.openai.OpenAI")
def test_validate_open_api_key_api_error(mock_openai_cls: MagicMock) -> None:
    """Test Open API validation generic OpenAIError."""
    mock_instance = MagicMock()
    mock_instance.models.list.side_effect = OpenAIError(
        "Rate limit or server error",
        request=MagicMock(),
        body=None,
    )
    mock_openai_cls.return_value = mock_instance

    valid, message, models = validate_open_api_key("sk-error")
    assert not valid
    assert "Open API error" in message
    assert models == []


@patch("app.datasources.openai.OpenAI")
def test_validate_open_api_key_generic_exception(mock_openai_cls: MagicMock) -> None:
    """Test Open API validation unexpected exception."""
    mock_instance = MagicMock()
    mock_instance.models.list.side_effect = RuntimeError("OpenAI crash")
    mock_openai_cls.return_value = mock_instance

    valid, message, models = validate_open_api_key("sk-crash")
    assert not valid
    assert "Open API validation error" in message
    assert models == []
