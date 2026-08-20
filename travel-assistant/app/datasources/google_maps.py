"""Client library for Google Maps Platform APIs (Geocoding, Distance Matrix, Directions)."""

import logging
from typing import Any, Dict, List, Optional, Tuple, Union
import googlemaps
from googlemaps.exceptions import (
    ApiError as GoogleMapsApiError,
    HTTPError as GoogleMapsHTTPError,
    Timeout as GoogleMapsTimeout,
    TransportError as GoogleMapsTransportError,
)

from app.datasources.base import BaseDataSource
from app.datasources.exceptions import (
    DataSourceAuthError,
    DataSourceConfigError,
    DataSourceConnectionError,
    DataSourceError,
    DataSourceRateLimitError,
)

logger = logging.getLogger(__name__)


DEFAULT_REGION = "uk"


class GoogleMapsClient(BaseDataSource):
    """Datasource client for Google Maps Platform web services."""

    provider_name: str = "google_maps"

    def __init__(
        self,
        api_key: str = "",
        region: str = DEFAULT_REGION,
        timeout: float = 10.0,
        client: Optional[googlemaps.Client] = None,
    ) -> None:
        """Initialise GoogleMapsClient with API credentials and configuration.

        Args:
            api_key: Google Maps Platform API key.
            region: Optional default region bias (e.g. 'uk', 'gb', 'us').
            timeout: Request timeout in seconds.
            client: Injected googlemaps.Client instance for testing.
        """
        self.api_key = (api_key or "").strip()
        self.region = (region or DEFAULT_REGION).strip().lower()
        self.timeout = timeout
        self._client = client

    @classmethod
    def from_settings(cls, settings: Optional[Any] = None) -> "GoogleMapsClient":
        """Instantiate GoogleMapsClient with credentials loaded from Setting model or provider.

        Args:
            settings: Optional Setting model, dictionary, or provider.

        Returns:
            Configured GoogleMapsClient instance.
        """
        getter = cls.get_setting_getter(settings)
        api_key = ""
        region = DEFAULT_REGION
        try:
            api_key = getter("google_maps_api_key", "")
            region = getter("google_maps_region", DEFAULT_REGION)
        except Exception as e:
            logger.warning("Could not load Google Maps settings from database: %s", e)

        return cls(api_key=api_key or "", region=region or DEFAULT_REGION)

    def get_client(self) -> googlemaps.Client:
        """Retrieve or lazily initialise the underlying googlemaps.Client.

        Returns:
            googlemaps.Client instance.

        Raises:
            DataSourceConfigError: If API key is missing.
        """
        if self._client is not None:
            return self._client

        if not self.api_key:
            raise DataSourceConfigError(
                "Google Maps API key is not configured.", provider=self.provider_name
            )

        self._client = googlemaps.Client(
            key=self.api_key,
            timeout=self.timeout,
        )
        return self._client

    def validate_credentials(self) -> Dict[str, Any]:
        """Validate credentials against Google Maps Platform services.

        Sends a lightweight geocoding probe request to verify the API key and service activation:
        - HTTP 200 with geocoding results confirms valid authentication and enabled APIs.
        - REQUEST_DENIED: Authentication rejected (invalid key, unauthorised project,
          billing required).
        - OVER_QUERY_LIMIT: Quota or rate limit exceeded.

        Returns:
            Dict containing 'valid' (bool), 'message' (str), and provider metadata.
        """
        if not self.api_key:
            return {
                "valid": False,
                "message": "Google Maps API key is required.",
                "provider": self.provider_name,
            }

        try:
            client = self.get_client()
            # Probe geocoding request to verify key validity and service access
            client.geocode("London", region=self.region)
            return {
                "valid": True,
                "message": "Google Maps credentials valid.",
                "provider": self.provider_name,
            }
        except GoogleMapsApiError as e:
            status = getattr(e, "status", "")
            message = getattr(e, "message", str(e))

            if status in ("OK", "ZERO_RESULTS"):
                return {
                    "valid": True,
                    "message": "Google Maps credentials valid.",
                    "provider": self.provider_name,
                }
            if status == "REQUEST_DENIED":
                return {
                    "valid": False,
                    "message": f"Google Maps request denied: {message}",
                    "provider": self.provider_name,
                }
            if status == "OVER_QUERY_LIMIT":
                return {
                    "valid": False,
                    "message": f"Google Maps quota or rate limit exceeded: {message}",
                    "provider": self.provider_name,
                }
            return {
                "valid": False,
                "message": f"Google Maps validation error ({status}): {message}",
                "provider": self.provider_name,
            }
        except GoogleMapsTimeout:
            return {
                "valid": False,
                "message": "Connection timeout while validating Google Maps credentials.",
                "provider": self.provider_name,
            }
        except (GoogleMapsTransportError, GoogleMapsHTTPError) as e:
            return {
                "valid": False,
                "message": f"Google Maps connection error: {e}",
                "provider": self.provider_name,
            }
        except Exception as e:
            return {
                "valid": False,
                "message": f"Unexpected error validating Google Maps credentials: {e}",
                "provider": self.provider_name,
            }

    def validate_tuple(self) -> Tuple[bool, str]:
        """Validate credentials and return (is_valid, message) tuple.

        Returns:
            Tuple of (is_valid, message).
        """
        res = self.validate_credentials()
        return bool(res.get("valid", False)), str(res.get("message", ""))

    def geocode(
        self,
        address: str,
        region: Optional[str] = None,
        components: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """Geocode an address to geographic coordinates.

        Args:
            address: Street address or location name.
            region: Optional region bias code (e.g. 'uk').
            components: Optional component filters.

        Returns:
            List of geocoding result dictionaries.

        Raises:
            DataSourceConfigError: If API key is missing.
            DataSourceAuthError: If authentication is rejected.
            DataSourceRateLimitError: If query quota is exceeded.
            DataSourceConnectionError: If network connection fails.
            DataSourceError: For other Google Maps API errors.
        """
        client = self.get_client()
        target_region = (region or self.region or DEFAULT_REGION).strip().lower()
        try:
            results = client.geocode(
                address=address,
                region=target_region,
                components=components,
            )
            return results or []
        except GoogleMapsApiError as e:
            self._handle_api_error(e)
        except GoogleMapsTimeout as e:
            raise DataSourceConnectionError(
                f"Google Maps geocoding timeout: {e}", provider=self.provider_name
            ) from e
        except (GoogleMapsTransportError, GoogleMapsHTTPError) as e:
            raise DataSourceConnectionError(
                f"Google Maps geocoding connection error: {e}",
                provider=self.provider_name,
            ) from e

    def reverse_geocode(
        self,
        lat: float,
        lng: float,
    ) -> List[Dict[str, Any]]:
        """Reverse geocode latitude and longitude coordinates to an address.

        Args:
            lat: Latitude coordinate.
            lng: Longitude coordinate.

        Returns:
            List of reverse geocoding result dictionaries.
        """
        client = self.get_client()
        try:
            results = client.reverse_geocode((lat, lng))
            return results or []
        except GoogleMapsApiError as e:
            self._handle_api_error(e)
        except GoogleMapsTimeout as e:
            raise DataSourceConnectionError(
                f"Google Maps reverse geocoding timeout: {e}",
                provider=self.provider_name,
            ) from e
        except (GoogleMapsTransportError, GoogleMapsHTTPError) as e:
            raise DataSourceConnectionError(
                f"Google Maps reverse geocoding connection error: {e}",
                provider=self.provider_name,
            ) from e

    def distance_matrix(
        self,
        origins: Union[str, Tuple[float, float], List[Any]],
        destinations: Union[str, Tuple[float, float], List[Any]],
        mode: str = "walking",
        departure_time: Optional[Any] = None,
        units: str = "metric",
    ) -> Dict[str, Any]:
        """Compute travel distance and duration matrix between origins and destinations.

        Args:
            origins: Origin address, (lat, lng) tuple, or list of origins.
            destinations: Destination address, (lat, lng) tuple, or list of destinations.
            mode: Travel mode ('walking', 'transit', 'driving', 'bicycling').
            departure_time: Optional departure time (timestamp or datetime).
            units: Unit system ('metric' or 'imperial').

        Returns:
            Dictionary containing distance matrix response.
        """
        client = self.get_client()
        try:
            return client.distance_matrix(
                origins=origins,
                destinations=destinations,
                mode=mode,
                departure_time=departure_time,
                units=units,
                region=self.region,
            )
        except GoogleMapsApiError as e:
            self._handle_api_error(e)
        except GoogleMapsTimeout as e:
            raise DataSourceConnectionError(
                f"Google Maps distance matrix timeout: {e}",
                provider=self.provider_name,
            ) from e
        except (GoogleMapsTransportError, GoogleMapsHTTPError) as e:
            raise DataSourceConnectionError(
                f"Google Maps distance matrix connection error: {e}",
                provider=self.provider_name,
            ) from e

    def directions(
        self,
        origin: Union[str, Tuple[float, float]],
        destination: Union[str, Tuple[float, float]],
        mode: str = "walking",
        departure_time: Optional[Any] = None,
        alternatives: bool = False,
    ) -> List[Dict[str, Any]]:
        """Retrieve directions and navigation legs between origin and destination.

        Args:
            origin: Starting address or (lat, lng) tuple.
            destination: Destination address or (lat, lng) tuple.
            mode: Travel mode ('walking', 'transit', 'driving', 'bicycling').
            departure_time: Optional departure time.
            alternatives: Whether to return alternative routes.

        Returns:
            List of route dictionaries.
        """
        client = self.get_client()
        try:
            return client.directions(
                origin=origin,
                destination=destination,
                mode=mode,
                departure_time=departure_time,
                alternatives=alternatives,
                region=self.region,
            )
        except GoogleMapsApiError as e:
            self._handle_api_error(e)
        except GoogleMapsTimeout as e:
            raise DataSourceConnectionError(
                f"Google Maps directions timeout: {e}", provider=self.provider_name
            ) from e
        except (GoogleMapsTransportError, GoogleMapsHTTPError) as e:
            raise DataSourceConnectionError(
                f"Google Maps directions connection error: {e}",
                provider=self.provider_name,
            ) from e

    def _handle_api_error(self, err: GoogleMapsApiError) -> None:
        """Map googlemaps ApiError into domain-specific DataSource exceptions."""
        status = getattr(err, "status", "")
        msg = getattr(err, "message", str(err))

        if status == "REQUEST_DENIED":
            raise DataSourceAuthError(
                f"Google Maps authentication error: {msg}",
                provider=self.provider_name,
            ) from err
        if status == "OVER_QUERY_LIMIT":
            raise DataSourceRateLimitError(
                f"Google Maps rate limit exceeded: {msg}",
                provider=self.provider_name,
            ) from err
        raise DataSourceError(
            f"Google Maps API error ({status}): {msg}",
            provider=self.provider_name,
        ) from err
