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
    @abstractmethod
    def from_settings(cls, settings: Optional[Any] = None) -> "BaseDataSource":
        """Factory method to initialise a client instance from saved settings or Setting model.

        Args:
            settings: Optional Setting model, dict, or settings provider.

        Returns:
            Configured datasource client instance.
        """
