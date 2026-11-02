import datetime
import logging
import time
from typing import Any, Dict, List, Optional, Tuple, Union
import googlemaps
import requests
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


def _get_api_tracker():
    """Lazily import API tracking and caching utilities to avoid circular imports."""
    from app.services.api_tracker import (
        build_cache_key,
        check_quota,
        global_api_cache,
        record_api_call,
    )

    return build_cache_key, check_quota, global_api_cache, record_api_call


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
        enable_cache: Optional[bool] = None,
    ) -> None:
        """Initialise GoogleMapsClient with API credentials and configuration.

        Args:
            api_key: Google Maps Platform API key.
            region: Optional default region bias (e.g. 'uk', 'gb', 'us').
            timeout: Request timeout in seconds.
            client: Injected googlemaps.Client instance for testing.
            enable_cache: Whether to enable response caching (defaults to True unless client is mocked).
        """
        self.api_key = (api_key or "").strip()
        self.region = (region or DEFAULT_REGION).strip().lower()
        self.timeout = timeout
        self._client = client
        self.enable_cache = (
            (client is None) if enable_cache is None else bool(enable_cache)
        )

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
        caller: str = "system",
        bypass_cache: bool = False,
    ) -> List[Dict[str, Any]]:
        """Geocode an address to geographic coordinates.

        Args:
            address: Street address or location name.
            region: Optional region bias code (e.g. 'uk').
            components: Optional component filters.
            caller: Subsystem identifier for usage auditing.
            bypass_cache: Force fresh external request.

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
        summary = str(address).strip()
        build_cache_key, check_quota, global_api_cache, record_api_call = (
            _get_api_tracker()
        )
        cache_key = build_cache_key(
            "geocode", summary.lower(), target_region, components
        )

        if self.enable_cache and not bypass_cache:
            cached = global_api_cache.get(self.provider_name, cache_key)
            if cached is not None:
                record_api_call(
                    provider=self.provider_name,
                    endpoint="geocode",
                    caller=caller,
                    query_summary=summary,
                    status_code=200,
                    duration_ms=0,
                    is_cached=True,
                )
                return cached

        allowed, reason = check_quota(self.provider_name)
        if not allowed:
            record_api_call(
                provider=self.provider_name,
                endpoint="geocode",
                caller=caller,
                query_summary=summary,
                status_code=429,
                duration_ms=0,
                is_cached=False,
                error_message=reason,
            )
            raise DataSourceRateLimitError(reason, provider=self.provider_name)

        t0 = time.time()
        try:
            results = client.geocode(
                address=address,
                region=target_region,
                components=components,
            )
            res = results or []
            dur_ms = int((time.time() - t0) * 1000)
            record_api_call(
                provider=self.provider_name,
                endpoint="geocode",
                caller=caller,
                query_summary=summary,
                status_code=200,
                duration_ms=dur_ms,
                is_cached=False,
            )
            if self.enable_cache:
                global_api_cache.set(
                    self.provider_name, cache_key, res, ttl_seconds=86400
                )
            return res
        except GoogleMapsApiError as e:
            dur_ms = int((time.time() - t0) * 1000)
            record_api_call(
                provider=self.provider_name,
                endpoint="geocode",
                caller=caller,
                query_summary=summary,
                status_code=400,
                duration_ms=dur_ms,
                is_cached=False,
                error_message=str(e),
            )
            self._handle_api_error(e)
        except GoogleMapsTimeout as e:
            dur_ms = int((time.time() - t0) * 1000)
            record_api_call(
                provider=self.provider_name,
                endpoint="geocode",
                caller=caller,
                query_summary=summary,
                status_code=408,
                duration_ms=dur_ms,
                is_cached=False,
                error_message=str(e),
            )
            raise DataSourceConnectionError(
                f"Google Maps geocoding timeout: {e}", provider=self.provider_name
            ) from e
        except (GoogleMapsTransportError, GoogleMapsHTTPError) as e:
            dur_ms = int((time.time() - t0) * 1000)
            record_api_call(
                provider=self.provider_name,
                endpoint="geocode",
                caller=caller,
                query_summary=summary,
                status_code=500,
                duration_ms=dur_ms,
                is_cached=False,
                error_message=str(e),
            )
            raise DataSourceConnectionError(
                f"Google Maps geocoding connection error: {e}",
                provider=self.provider_name,
            ) from e

    def reverse_geocode(
        self,
        lat: float,
        lng: float,
        caller: str = "system",
        bypass_cache: bool = False,
    ) -> List[Dict[str, Any]]:
        """Reverse geocode latitude and longitude coordinates to an address.

        Args:
            lat: Latitude coordinate.
            lng: Longitude coordinate.
            caller: Subsystem identifier for usage auditing.
            bypass_cache: Force fresh external request.

        Returns:
            List of reverse geocoding result dictionaries.
        """
        client = self.get_client()
        summary = f"{lat:.5f},{lng:.5f}"
        build_cache_key, check_quota, global_api_cache, record_api_call = (
            _get_api_tracker()
        )
        cache_key = build_cache_key("reverse_geocode", round(lat, 5), round(lng, 5))

        if self.enable_cache and not bypass_cache:
            cached = global_api_cache.get(self.provider_name, cache_key)
            if cached is not None:
                record_api_call(
                    provider=self.provider_name,
                    endpoint="reverse_geocode",
                    caller=caller,
                    query_summary=summary,
                    status_code=200,
                    duration_ms=0,
                    is_cached=True,
                )
                return cached

        allowed, reason = check_quota(self.provider_name)
        if not allowed:
            record_api_call(
                provider=self.provider_name,
                endpoint="reverse_geocode",
                caller=caller,
                query_summary=summary,
                status_code=429,
                duration_ms=0,
                is_cached=False,
                error_message=reason,
            )
            raise DataSourceRateLimitError(reason, provider=self.provider_name)

        t0 = time.time()
        try:
            results = client.reverse_geocode((lat, lng))
            res = results or []
            dur_ms = int((time.time() - t0) * 1000)
            record_api_call(
                provider=self.provider_name,
                endpoint="reverse_geocode",
                caller=caller,
                query_summary=summary,
                status_code=200,
                duration_ms=dur_ms,
                is_cached=False,
            )
            if self.enable_cache:
                global_api_cache.set(
                    self.provider_name, cache_key, res, ttl_seconds=86400
                )
            return res
        except GoogleMapsApiError as e:
            dur_ms = int((time.time() - t0) * 1000)
            record_api_call(
                provider=self.provider_name,
                endpoint="reverse_geocode",
                caller=caller,
                query_summary=summary,
                status_code=400,
                duration_ms=dur_ms,
                is_cached=False,
                error_message=str(e),
            )
            self._handle_api_error(e)
        except GoogleMapsTimeout as e:
            dur_ms = int((time.time() - t0) * 1000)
            record_api_call(
                provider=self.provider_name,
                endpoint="reverse_geocode",
                caller=caller,
                query_summary=summary,
                status_code=408,
                duration_ms=dur_ms,
                is_cached=False,
                error_message=str(e),
            )
            raise DataSourceConnectionError(
                f"Google Maps reverse geocoding timeout: {e}",
                provider=self.provider_name,
            ) from e
        except (GoogleMapsTransportError, GoogleMapsHTTPError) as e:
            dur_ms = int((time.time() - t0) * 1000)
            record_api_call(
                provider=self.provider_name,
                endpoint="reverse_geocode",
                caller=caller,
                query_summary=summary,
                status_code=500,
                duration_ms=dur_ms,
                is_cached=False,
                error_message=str(e),
            )
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
        caller: str = "system",
        bypass_cache: bool = False,
    ) -> Dict[str, Any]:
        """Compute travel distance and duration matrix between origins and destinations.

        Args:
            origins: Origin address, (lat, lng) tuple, or list of origins.
            destinations: Destination address, (lat, lng) tuple, or list of destinations.
            mode: Travel mode ('walking', 'transit', 'driving', 'bicycling').
            departure_time: Optional departure time (timestamp or datetime).
            units: Unit system ('metric' or 'imperial').
            caller: Subsystem identifier for usage auditing.
            bypass_cache: Force fresh external request.

        Returns:
            Dictionary containing distance matrix response.
        """
        client = self.get_client()
        summary = f"{origins} -> {destinations} ({mode})"
        build_cache_key, check_quota, global_api_cache, record_api_call = (
            _get_api_tracker()
        )
        cache_key = build_cache_key(
            "distance_matrix", origins, destinations, mode, units
        )

        if self.enable_cache and not bypass_cache:
            cached = global_api_cache.get(self.provider_name, cache_key)
            if cached is not None:
                record_api_call(
                    provider=self.provider_name,
                    endpoint="distance_matrix",
                    caller=caller,
                    query_summary=summary,
                    status_code=200,
                    duration_ms=0,
                    is_cached=True,
                )
                return cached

        allowed, reason = check_quota(self.provider_name)
        if not allowed:
            record_api_call(
                provider=self.provider_name,
                endpoint="distance_matrix",
                caller=caller,
                query_summary=summary,
                status_code=429,
                duration_ms=0,
                is_cached=False,
                error_message=reason,
            )
            raise DataSourceRateLimitError(reason, provider=self.provider_name)

        t0 = time.time()
        try:
            res = client.distance_matrix(
                origins=origins,
                destinations=destinations,
                mode=mode,
                departure_time=departure_time,
                units=units,
                region=self.region,
            )
            dur_ms = int((time.time() - t0) * 1000)
            record_api_call(
                provider=self.provider_name,
                endpoint="distance_matrix",
                caller=caller,
                query_summary=summary,
                status_code=200,
                duration_ms=dur_ms,
                is_cached=False,
            )
            # Cache walking matrix results for 24 hours, others for 15 minutes
            ttl = 86400 if mode == "walking" else 900
            if self.enable_cache:
                global_api_cache.set(
                    self.provider_name, cache_key, res, ttl_seconds=ttl
                )
            return res
        except GoogleMapsApiError as e:
            dur_ms = int((time.time() - t0) * 1000)
            record_api_call(
                provider=self.provider_name,
                endpoint="distance_matrix",
                caller=caller,
                query_summary=summary,
                status_code=400,
                duration_ms=dur_ms,
                is_cached=False,
                error_message=str(e),
            )
            self._handle_api_error(e)
        except GoogleMapsTimeout as e:
            dur_ms = int((time.time() - t0) * 1000)
            record_api_call(
                provider=self.provider_name,
                endpoint="distance_matrix",
                caller=caller,
                query_summary=summary,
                status_code=408,
                duration_ms=dur_ms,
                is_cached=False,
                error_message=str(e),
            )
            raise DataSourceConnectionError(
                f"Google Maps distance matrix timeout: {e}",
                provider=self.provider_name,
            ) from e
        except (GoogleMapsTransportError, GoogleMapsHTTPError) as e:
            dur_ms = int((time.time() - t0) * 1000)
            record_api_call(
                provider=self.provider_name,
                endpoint="distance_matrix",
                caller=caller,
                query_summary=summary,
                status_code=500,
                duration_ms=dur_ms,
                is_cached=False,
                error_message=str(e),
            )
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
        caller: str = "system",
        bypass_cache: bool = False,
    ) -> List[Dict[str, Any]]:
        """Retrieve directions and navigation legs between origin and destination.

        Args:
            origin: Starting address or (lat, lng) tuple.
            destination: Destination address or (lat, lng) tuple.
            mode: Travel mode ('walking', 'transit', 'driving', 'bicycling').
            departure_time: Optional departure time.
            alternatives: Whether to return alternative routes.
            caller: Subsystem identifier for usage auditing.
            bypass_cache: Force fresh external request.

        Returns:
            List of route dictionaries.
        """
        client = self.get_client()
        summary = f"{origin} -> {destination} ({mode})"
        build_cache_key, check_quota, global_api_cache, record_api_call = (
            _get_api_tracker()
        )
        cache_key = build_cache_key(
            "directions", origin, destination, mode, alternatives
        )

        if self.enable_cache and not bypass_cache:
            cached = global_api_cache.get(self.provider_name, cache_key)
            if cached is not None:
                record_api_call(
                    provider=self.provider_name,
                    endpoint="directions",
                    caller=caller,
                    query_summary=summary,
                    status_code=200,
                    duration_ms=0,
                    is_cached=True,
                )
                return cached

        allowed, reason = check_quota(self.provider_name)
        if not allowed:
            record_api_call(
                provider=self.provider_name,
                endpoint="directions",
                caller=caller,
                query_summary=summary,
                status_code=429,
                duration_ms=0,
                is_cached=False,
                error_message=reason,
            )
            raise DataSourceRateLimitError(reason, provider=self.provider_name)

        t0 = time.time()
        try:
            res = client.directions(
                origin=origin,
                destination=destination,
                mode=mode,
                departure_time=departure_time,
                alternatives=alternatives,
                region=self.region,
            )
            dur_ms = int((time.time() - t0) * 1000)
            record_api_call(
                provider=self.provider_name,
                endpoint="directions",
                caller=caller,
                query_summary=summary,
                status_code=200,
                duration_ms=dur_ms,
                is_cached=False,
            )
            # Walking directions are static, cache for 24 hours. Other modes for 15 mins.
            ttl = 86400 if mode == "walking" else 900
            if self.enable_cache:
                global_api_cache.set(
                    self.provider_name, cache_key, res, ttl_seconds=ttl
                )
            return res
        except GoogleMapsApiError as e:
            dur_ms = int((time.time() - t0) * 1000)
            record_api_call(
                provider=self.provider_name,
                endpoint="directions",
                caller=caller,
                query_summary=summary,
                status_code=400,
                duration_ms=dur_ms,
                is_cached=False,
                error_message=str(e),
            )
            self._handle_api_error(e)
        except GoogleMapsTimeout as e:
            dur_ms = int((time.time() - t0) * 1000)
            record_api_call(
                provider=self.provider_name,
                endpoint="directions",
                caller=caller,
                query_summary=summary,
                status_code=408,
                duration_ms=dur_ms,
                is_cached=False,
                error_message=str(e),
            )
            raise DataSourceConnectionError(
                f"Google Maps directions timeout: {e}", provider=self.provider_name
            ) from e
        except (GoogleMapsTransportError, GoogleMapsHTTPError) as e:
            dur_ms = int((time.time() - t0) * 1000)
            record_api_call(
                provider=self.provider_name,
                endpoint="directions",
                caller=caller,
                query_summary=summary,
                status_code=500,
                duration_ms=dur_ms,
                is_cached=False,
                error_message=str(e),
            )
            raise DataSourceConnectionError(
                f"Google Maps directions connection error: {e}",
                provider=self.provider_name,
            ) from e

    def compute_transit_routes(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        departure_time: Optional[Union[datetime.datetime, str]] = None,
        arrival_time: Optional[Union[datetime.datetime, str]] = None,
        compute_alternative_routes: bool = True,
        caller: str = "system",
        bypass_cache: bool = False,
        cache_ttl_seconds: int = 900,
    ) -> Dict[str, Any]:
        """Compute transit routes between coordinates using Google Routes API v2.

        Args:
            origin: (latitude, longitude) coordinate tuple of departure point.
            destination: (latitude, longitude) coordinate tuple of arrival point.
            departure_time: Optional departure datetime or RFC3339 string.
            arrival_time: Optional arrival datetime or RFC3339 string.
            compute_alternative_routes: Whether to request alternative routes.
            caller: Subsystem identifier for usage auditing.
            bypass_cache: Force fresh external request.
            cache_ttl_seconds: Cache duration in seconds (default: 900s / 15m).

        Returns:
            Dict containing raw Google Routes API response JSON.

        Raises:
            DataSourceConfigError: If API key is missing.
            DataSourceAuthError: If authentication/quota is denied.
            DataSourceRateLimitError: If rate limit exceeded.
            DataSourceConnectionError: If network request times out or fails.
            DataSourceError: For any other API error.
        """
        if not self.api_key:
            raise DataSourceConfigError(
                "Google Maps API key is not configured.", provider=self.provider_name
            )

        def _bucket_time(t: Any) -> str:
            if isinstance(t, datetime.datetime):
                bucket_min = (t.minute // 15) * 15
                return t.strftime(f"%Y-%m-%d %H:{bucket_min:02d}")
            if isinstance(t, str):
                return t[:16]
            return ""

        summary = f"{origin[0]:.4f},{origin[1]:.4f} -> {destination[0]:.4f},{destination[1]:.4f}"
        build_cache_key, check_quota, global_api_cache, record_api_call = (
            _get_api_tracker()
        )
        cache_key = build_cache_key(
            "compute_transit_routes",
            (round(origin[0], 4), round(origin[1], 4)),
            (round(destination[0], 4), round(destination[1], 4)),
            _bucket_time(departure_time),
            _bucket_time(arrival_time),
            compute_alternative_routes,
        )

        if self.enable_cache and not bypass_cache:
            cached = global_api_cache.get(self.provider_name, cache_key)
            if cached is not None:
                record_api_call(
                    provider=self.provider_name,
                    endpoint="compute_transit_routes",
                    caller=caller,
                    query_summary=summary,
                    status_code=200,
                    duration_ms=0,
                    is_cached=True,
                )
                return cached

        allowed, reason = check_quota(self.provider_name)
        if not allowed:
            record_api_call(
                provider=self.provider_name,
                endpoint="compute_transit_routes",
                caller=caller,
                query_summary=summary,
                status_code=429,
                duration_ms=0,
                is_cached=False,
                error_message=reason,
            )
            raise DataSourceRateLimitError(reason, provider=self.provider_name)

        url = "https://routes.googleapis.com/directions/v2:computeRoutes"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": (
                "routes.duration,"
                "routes.distanceMeters,"
                "routes.description,"
                "routes.legs.duration,"
                "routes.legs.distanceMeters,"
                "routes.legs.polyline,"
                "routes.legs.steps"
            ),
        }

        body: Dict[str, Any] = {
            "origin": {
                "location": {
                    "latLng": {
                        "latitude": float(origin[0]),
                        "longitude": float(origin[1]),
                    }
                }
            },
            "destination": {
                "location": {
                    "latLng": {
                        "latitude": float(destination[0]),
                        "longitude": float(destination[1]),
                    }
                }
            },
            "travelMode": "TRANSIT",
            "computeAlternativeRoutes": bool(compute_alternative_routes),
        }

        if departure_time:
            if isinstance(departure_time, datetime.datetime):
                body["departureTime"] = departure_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            else:
                body["departureTime"] = str(departure_time)
        elif arrival_time:
            if isinstance(arrival_time, datetime.datetime):
                body["arrivalTime"] = arrival_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            else:
                body["arrivalTime"] = str(arrival_time)
        else:
            body["departureTime"] = datetime.datetime.utcnow().strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

        t0 = time.time()
        try:
            resp = requests.post(url, json=body, headers=headers, timeout=self.timeout)
            dur_ms = int((time.time() - t0) * 1000)

            if resp.status_code == 200:
                data = resp.json()
                record_api_call(
                    provider=self.provider_name,
                    endpoint="compute_transit_routes",
                    caller=caller,
                    query_summary=summary,
                    status_code=200,
                    duration_ms=dur_ms,
                    is_cached=False,
                )
                if self.enable_cache:
                    global_api_cache.set(
                        self.provider_name,
                        cache_key,
                        data,
                        ttl_seconds=cache_ttl_seconds,
                    )
                return data

            data: Dict[str, Any] = {}
            try:
                data = resp.json()
            except Exception:
                pass
            msg = data.get("error", {}).get("message", resp.text)

            record_api_call(
                provider=self.provider_name,
                endpoint="compute_transit_routes",
                caller=caller,
                query_summary=summary,
                status_code=resp.status_code,
                duration_ms=dur_ms,
                is_cached=False,
                error_message=msg,
            )

            if resp.status_code in (401, 403):
                raise DataSourceAuthError(
                    f"Google Routes API authentication error: {msg}",
                    provider=self.provider_name,
                )
            if resp.status_code == 429:
                raise DataSourceRateLimitError(
                    f"Google Routes API rate limit exceeded: {msg}",
                    provider=self.provider_name,
                )
            raise DataSourceError(
                f"Google Routes API error ({resp.status_code}): {msg}",
                provider=self.provider_name,
            )
        except requests.Timeout as e:
            dur_ms = int((time.time() - t0) * 1000)
            record_api_call(
                provider=self.provider_name,
                endpoint="compute_transit_routes",
                caller=caller,
                query_summary=summary,
                status_code=408,
                duration_ms=dur_ms,
                is_cached=False,
                error_message=str(e),
            )
            raise DataSourceConnectionError(
                f"Google Routes API timeout: {e}", provider=self.provider_name
            ) from e
        except requests.RequestException as e:
            dur_ms = int((time.time() - t0) * 1000)
            record_api_call(
                provider=self.provider_name,
                endpoint="compute_transit_routes",
                caller=caller,
                query_summary=summary,
                status_code=500,
                duration_ms=dur_ms,
                is_cached=False,
                error_message=str(e),
            )
            raise DataSourceConnectionError(
                f"Google Routes API connection error: {e}", provider=self.provider_name
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
