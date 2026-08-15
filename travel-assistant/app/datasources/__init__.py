"""Datasources library package for Travel Assistant.

Provides modular clients for external transit APIs, cloud storage, and AI providers.
"""

from typing import Any, Dict, Optional, Type

from app.datasources.base import BaseDataSource
from app.datasources.bods import BodsClient
from app.datasources.exceptions import (
    DataSourceAuthError,
    DataSourceConfigError,
    DataSourceConnectionError,
    DataSourceError,
    DataSourceRateLimitError,
)
from app.datasources.google_maps import GoogleMapsClient
from app.datasources.homeassistant import HomeAssistantClient
from app.datasources.naptan import NaptanClient
from app.datasources.openai import OpenAIClient, filter_chat_models
from app.datasources.train_live import TrainLiveClient
from app.datasources.train_s3 import TrainS3Client

DATASOURCE_REGISTRY: Dict[str, Type[BaseDataSource]] = {
    "bus": BodsClient,
    "bods": BodsClient,
    "train_s3": TrainS3Client,
    "s3": TrainS3Client,
    "train_live": TrainLiveClient,
    "darwin": TrainLiveClient,
    "open_api": OpenAIClient,
    "openai": OpenAIClient,
    "naptan": NaptanClient,
    "homeassistant": HomeAssistantClient,
    "ha": HomeAssistantClient,
    "google_maps": GoogleMapsClient,
    "googlemaps": GoogleMapsClient,
    "maps": GoogleMapsClient,
}


def get_datasource(service_name: str, settings: Optional[Any] = None) -> BaseDataSource:
    """Factory helper to obtain an instantiated datasource client by service key.

    Args:
        service_name: Service identifier (e.g. 'bus', 'train_s3', 'openai', 'ha', 'google_maps').
        settings: Optional settings provider or dictionary to load credentials from.


    Returns:
        Configured BaseDataSource client.

    Raises:
        DataSourceConfigError: If service_name is unknown.
    """
    key = service_name.lower().strip()
    cls = DATASOURCE_REGISTRY.get(key)
    if not cls:
        services_list = list(DATASOURCE_REGISTRY.keys())
        raise DataSourceConfigError(
            f"Unknown datasource service '{service_name}'. Supported services: {services_list}"
        )
    return cls.from_settings(settings)


__all__ = [
    "BaseDataSource",
    "DataSourceError",
    "DataSourceConfigError",
    "DataSourceAuthError",
    "DataSourceConnectionError",
    "DataSourceRateLimitError",
    "BodsClient",
    "TrainS3Client",
    "TrainLiveClient",
    "OpenAIClient",
    "GoogleMapsClient",
    "NaptanClient",
    "HomeAssistantClient",
    "filter_chat_models",
    "get_datasource",
    "DATASOURCE_REGISTRY",
]
