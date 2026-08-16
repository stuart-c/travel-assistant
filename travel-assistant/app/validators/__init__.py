"""Service credentials validators module."""

from app.validators import constants
from app.validators.dispatcher import validate_service_credentials

__all__ = [
    "constants",
    "validate_service_credentials",
]
