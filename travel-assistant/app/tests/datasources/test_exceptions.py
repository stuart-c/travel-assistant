"""Unit tests for datasource domain exceptions."""

from app.datasources.exceptions import (
    DataSourceAuthError,
    DataSourceConfigError,
    DataSourceConnectionError,
    DataSourceError,
    DataSourceRateLimitError,
)


def test_datasource_error_str_formatting() -> None:
    """Test DataSourceError string representation with and without provider."""
    err_without_provider = DataSourceError("Network timeout")
    assert str(err_without_provider) == "Network timeout"
    assert err_without_provider.message == "Network timeout"
    assert err_without_provider.provider is None

    err_with_provider = DataSourceError("Invalid API key", provider="bods")
    assert str(err_with_provider) == "[bods] Invalid API key"
    assert err_with_provider.provider == "bods"


def test_datasource_subclasses_inheritance() -> None:
    """Test that all specific exception subclasses inherit from DataSourceError."""
    auth_err = DataSourceAuthError("401 Unauthorized", provider="openai")
    assert isinstance(auth_err, DataSourceError)
    assert str(auth_err) == "[openai] 401 Unauthorized"

    config_err = DataSourceConfigError("Missing key", provider="train_s3")
    assert isinstance(config_err, DataSourceError)

    conn_err = DataSourceConnectionError("Timeout", provider="train_live")
    assert isinstance(conn_err, DataSourceError)

    rate_err = DataSourceRateLimitError("Rate limit exceeded", provider="bods")
    assert isinstance(rate_err, DataSourceError)
