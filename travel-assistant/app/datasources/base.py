"""Base class for all external datasource clients."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseDataSource(ABC):
    """Abstract base class defining the datasource client interface."""

    provider_name: str = "base"

    @abstractmethod
    def validate_credentials(self) -> Dict[str, Any]:
        """Validate credentials against the external provider API.

        Returns:
            Dict containing 'valid' (bool), 'message' (str), and any provider-specific metadata.
        """

    @classmethod
    def get_setting_getter(cls, settings: Optional[Any] = None) -> Any:
        """Resolve a getter callable that retrieves setting values with optional defaults.

        Supports Setting model classes/instances (get_val), dict instances (get),
        or falls back to Setting.get_val.
        """
        from app.models.setting import Setting

        if settings is None:
            return Setting.get_val
        if isinstance(settings, dict):
            return settings.get
        if hasattr(settings, "get") and callable(settings.get):
            return settings.get
        if hasattr(settings, "get_val") and callable(settings.get_val):
            return settings.get_val
        return Setting.get_val

    @classmethod
    @abstractmethod
    def from_settings(cls, settings: Optional[Any] = None) -> "BaseDataSource":
        """Factory method to initialise a client instance from saved settings or Setting model.

        Args:
            settings: Optional Setting model, dict, or settings provider.

        Returns:
            Configured datasource client instance.
        """
