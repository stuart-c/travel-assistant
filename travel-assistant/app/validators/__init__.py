"""Credential validation package for Travel Assistant.

Provides live verification functions for external APIs and cloud services,
including Bus Open Data Service (BODS), AWS S3 bucket storage, National Rail
Darwin LDBWS (via OpenAPI and SOAP), and OpenAI-compatible services.
"""

from app.validators.bus import validate_bus_api_key
from app.validators.constants import (
    DEFAULT_BODS_BASE,
    DEFAULT_LDBWS_BASE,
    DEFAULT_OPENAI_BASE,
    DEFAULT_OPENAI_MODELS,
    EXCLUDED_MODEL_PREFIXES,
    EXCLUDED_MODEL_SUBSTRINGS,
    PRIORITY_MODELS,
)
from app.validators.dispatcher import validate_service_credentials
from app.validators.google_maps import validate_google_maps_api_key
from app.validators.openai import filter_chat_models, validate_open_api_key
from app.validators.s3 import validate_train_s3_bucket
from app.validators.train_live import validate_train_live_token

__all__ = [
    "DEFAULT_BODS_BASE",
    "DEFAULT_LDBWS_BASE",
    "DEFAULT_OPENAI_BASE",
    "DEFAULT_OPENAI_MODELS",
    "EXCLUDED_MODEL_PREFIXES",
    "EXCLUDED_MODEL_SUBSTRINGS",
    "PRIORITY_MODELS",
    "filter_chat_models",
    "validate_bus_api_key",
    "validate_google_maps_api_key",
    "validate_open_api_key",
    "validate_service_credentials",
    "validate_train_live_token",
    "validate_train_s3_bucket",
]
