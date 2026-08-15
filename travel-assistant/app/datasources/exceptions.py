"""Unified domain exceptions for external datasource clients."""

from typing import Optional


class DataSourceError(Exception):
    """Base exception for all datasource-related errors."""

    def __init__(self, message: str, provider: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider

    def __str__(self) -> str:
        if self.provider:
            return f"[{self.provider}] {self.message}"
        return self.message


class DataSourceConfigError(DataSourceError):
    """Raised when required datasource configuration or credentials are missing."""


class DataSourceAuthError(DataSourceError):
    """Raised when authentication with an external datasource fails (e.g. invalid API key)."""


class DataSourceConnectionError(DataSourceError):
    """Raised when a network timeout or connection failure occurs."""


class DataSourceRateLimitError(DataSourceError):
    """Raised when an external datasource returns HTTP 429 rate limit exceeded."""
