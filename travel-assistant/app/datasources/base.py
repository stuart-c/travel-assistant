"""Base class for all external datasource clients."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from app.db.settings import SettingsRepository


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
    @abstractmethod
    def from_settings(
        cls, settings_repo: Optional[SettingsRepository] = None
    ) -> "BaseDataSource":
        """Factory method to initialise a client instance from saved SettingsRepository.

        Args:
            settings_repo: Optional SettingsRepository instance.

        Returns:
            Configured datasource client instance.
        """
