"""Client library for UK Bus Open Data Service (BODS) SIRI-VM real-time vehicle telemetry."""

import datetime
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import defusedxml.ElementTree as DefusedET
import requests

from app.datasources.base import BaseDataSource
from app.datasources.exceptions import (
    DataSourceAuthError,
    DataSourceConfigError,
    DataSourceConnectionError,
    DataSourceError,
    DataSourceRateLimitError,
)
from app.utils.transit_time import parse_time_to_minutes

logger = logging.getLogger(__name__)

DEFAULT_BODS_SIRI_VM_URL = "https://data.bus-data.dft.gov.uk/api/v1/datafeed"
SIRI_NAMESPACE = {"siri": "http://www.siri.org.uk/siri"}


def _clean_tag(tag: str) -> str:
    """Strip XML namespace prefix from tag name."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def parse_iso_delay(delay_str: Optional[str]) -> Tuple[int, int, str, str]:
    """Parse SIRI ISO 8601 delay string (e.g. PT2M30S, -PT1M, PT0S) into delay metrics.

    Args:
        delay_str: Raw ISO 8601 delay string or None.

    Returns:
        Tuple of (delay_seconds, delay_minutes, status, formatted_label).
        status: 'On time', 'Early', or 'Delayed'
        formatted_label: e.g. 'On time', 'Early -2m', '+4m late'
    """
    if not delay_str:
        return 0, 0, "On time", "On time"

    s = str(delay_str).strip()
    is_early = s.startswith("-")
    clean_s = s.lstrip("-")

    match = re.search(
        r"PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?",
        clean_s,
    )
    if not match:
        return 0, 0, "On time", "On time"

    h = int(match.group("hours") or 0)
    m = int(match.group("minutes") or 0)
    sec = int(match.group("seconds") or 0)

    total_secs = h * 3600 + m * 60 + sec
    if is_early:
        total_secs = -total_secs

    total_mins = int(total_secs / 60)
    abs_mins = abs(total_mins)
    abs_secs = abs(total_secs) % 60

    if total_secs < -30:
        status = "Early"
        label = f"Early -{abs_mins}m" if abs_mins > 0 else f"Early -{abs_secs}s"
    elif total_secs <= 60:
        status = "On time"
        label = "On time"
    else:
        status = "Delayed"
        label = f"+{abs_mins}m late" if abs_mins > 0 else f"+{abs_secs}s late"

    return total_secs, total_mins, status, label


@dataclass
class LiveBusStatus:
    """Structured representation of a real-time bus vehicle position and telemetry."""

    vehicle_id: str
    line_name: str
    operator_ref: str
    direction: str
    origin_name: str
    destination_name: str
    origin_ref: Optional[str] = None
    destination_ref: Optional[str] = None
    scheduled_dep_time: Optional[str] = None
    delay_seconds: int = 0
    delay_minutes: int = 0
    delay_status: str = "On time"
    formatted_delay: str = "On time"
    delay_raw: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    bearing: Optional[float] = None
    recorded_at: Optional[datetime.datetime] = None
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert telemetry to a JSON-serialisable dictionary."""
        return {
            "vehicle_id": self.vehicle_id,
            "line_name": self.line_name,
            "operator_ref": self.operator_ref,
            "direction": self.direction,
            "origin_name": self.origin_name,
            "destination_name": self.destination_name,
            "origin_ref": self.origin_ref,
            "destination_ref": self.destination_ref,
            "scheduled_dep_time": self.scheduled_dep_time,
            "delay_seconds": self.delay_seconds,
            "delay_minutes": self.delay_minutes,
            "delay_status": self.delay_status,
            "formatted_delay": self.formatted_delay,
            "delay_raw": self.delay_raw,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "bearing": self.bearing,
            "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None,
            "is_active": self.is_active,
        }


class BodsLiveClient(BaseDataSource):
    """Datasource client for UK Bus Open Data Service (BODS) SIRI-VM live telemetry."""

    provider_name: str = "bus_live"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 8.0,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.base_url = base_url.rstrip("/") if base_url else DEFAULT_BODS_SIRI_VM_URL
        self.timeout = float(timeout)

    @classmethod
    def from_settings(cls, settings: Optional[Any] = None) -> "BodsLiveClient":
        """Instantiate BodsLiveClient with credentials loaded from Setting model or provider."""
        getter = cls.get_setting_getter(settings)
        return cls(
            api_key=getter("bus_api_key", ""),
            base_url=getter("bus_live_endpoint", "") or None,
        )

    def validate_credentials(self) -> Dict[str, Any]:
        """Validate BODS API key against the live SIRI-VM feed."""
        valid, msg = self.validate_tuple()
        return {"valid": valid, "message": msg}

    def validate_tuple(self) -> Tuple[bool, str]:
        """Validate BODS credentials returning a (valid, message) tuple."""
        if not self.api_key:
            return False, "BODS Bus API key is not configured."

        url = self.base_url
        headers = {"User-Agent": "TravelAssistantLiveBus/1.0"}
        params = {"api_key": self.api_key, "limit": 1}

        try:
            response = requests.get(
                url, headers=headers, params=params, timeout=self.timeout
            )
            if response.status_code in (401, 403):
                return False, "Invalid BODS API key."
            if response.status_code == 429:
                return False, "BODS rate limit exceeded. Please try again later."
            if response.status_code >= 500:
                return (
                    False,
                    f"BODS server error (HTTP {response.status_code}). Please try again later.",
                )
            if not response.ok:
                return False, f"BODS validation failed (HTTP {response.status_code})."

            return True, "BODS SIRI-VM live bus connection verified successfully."
        except requests.Timeout:
            return False, "Connection to BODS SIRI-VM timed out."
        except requests.RequestException as err:
            return False, f"Network error connecting to BODS SIRI-VM: {str(err)}"
        except Exception as err:
            return False, f"Unexpected error connecting to BODS SIRI-VM: {str(err)}"

    def fetch_live_vehicles(
        self,
        operator_ref: Optional[str] = None,
        line_ref: Optional[str] = None,
        bounding_box: Optional[Tuple[float, float, float, float]] = None,
        now_utc: Optional[datetime.datetime] = None,
    ) -> List[LiveBusStatus]:
        """Fetch and parse real-time active bus vehicles from BODS SIRI-VM feed.

        Args:
            operator_ref: Optional National Operator Code (NOC) filter.
            line_ref: Optional line / route name filter (e.g. '73', '205').
            bounding_box: Optional (min_lon, min_lat, max_lon, max_lat) tuple.
            now_utc: Optional current UTC datetime for freshness calculation (testing).

        Returns:
            List of LiveBusStatus objects representing active tracked vehicles.

        Raises:
            DataSourceConfigError: If API key is missing.
            DataSourceAuthError: If API key is rejected (HTTP 401/403).
            DataSourceRateLimitError: If rate limit is hit (HTTP 429).
            DataSourceConnectionError: On timeout or network failure.
            DataSourceError: On malformed XML or unexpected response.
        """
        if not self.api_key:
            raise DataSourceConfigError(
                "BODS Bus API key is not configured.", provider=self.provider_name
            )

        url = self.base_url
        headers = {"User-Agent": "TravelAssistantLiveBus/1.0"}
        params: Dict[str, Any] = {"api_key": self.api_key}

        if operator_ref:
            params["operatorRef"] = operator_ref.strip()
        if line_ref:
            params["lineRef"] = line_ref.strip()
        if bounding_box and len(bounding_box) == 4:
            params["boundingBox"] = (
                f"{bounding_box[0]},{bounding_box[1]},{bounding_box[2]},{bounding_box[3]}"
            )

        try:
            response = requests.get(
                url, headers=headers, params=params, timeout=self.timeout
            )
            if response.status_code in (401, 403):
                raise DataSourceAuthError(
                    f"BODS authentication failed (HTTP {response.status_code}). Check API key.",
                    provider=self.provider_name,
                )
            if response.status_code == 429:
                raise DataSourceRateLimitError(
                    "BODS rate limit exceeded.", provider=self.provider_name
                )
            if not response.ok:
                raise DataSourceConnectionError(
                    f"BODS returned HTTP {response.status_code}: {response.text[:200]}",
                    provider=self.provider_name,
                )

            return self._parse_siri_vm_xml(response.content, now_utc=now_utc)

        except requests.Timeout as err:
            raise DataSourceConnectionError(
                f"BODS SIRI-VM connection timed out: {str(err)}",
                provider=self.provider_name,
            )
        except requests.RequestException as err:
            raise DataSourceConnectionError(
                f"Network error connecting to BODS SIRI-VM: {str(err)}",
                provider=self.provider_name,
            )
        except (
            DataSourceAuthError,
            DataSourceRateLimitError,
            DataSourceConnectionError,
        ):
            raise
        except Exception as err:
            raise DataSourceError(
                f"Unexpected error fetching live vehicles: {str(err)}",
                provider=self.provider_name,
            )

    def _parse_siri_vm_xml(
        self, xml_bytes: bytes, now_utc: Optional[datetime.datetime] = None
    ) -> List[LiveBusStatus]:
        """Parse SIRI-VM XML payload into structured LiveBusStatus entries."""
        try:
            root = DefusedET.fromstring(xml_bytes)
        except Exception as err:
            raise DataSourceError(
                f"Failed to parse SIRI-VM XML response: {str(err)}",
                provider=self.provider_name,
            )

        if now_utc is None:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
        vehicles: List[LiveBusStatus] = []

        # Find VehicleActivity elements with namespace support or namespace-stripped fallback
        activities = root.findall(".//siri:VehicleActivity", SIRI_NAMESPACE)
        if not activities:
            activities = [
                elem
                for elem in root.iter()
                if _clean_tag(elem.tag) == "VehicleActivity"
            ]

        for act in activities:
            rec_time_str = ""
            rec_time_elem = act.find(".//siri:RecordedAtTime", SIRI_NAMESPACE)
            if rec_time_elem is None:
                for c in act.iter():
                    if _clean_tag(c.tag) == "RecordedAtTime":
                        rec_time_str = (c.text or "").strip()
                        break
            else:
                rec_time_str = (rec_time_elem.text or "").strip()

            rec_dt: Optional[datetime.datetime] = None
            is_active = True
            if rec_time_str:
                try:
                    clean_iso = rec_time_str.replace("Z", "+00:00")
                    rec_dt = datetime.datetime.fromisoformat(clean_iso)
                    age_secs = max(0, int((now_utc - rec_dt).total_seconds()))
                    # Vehicles reporting within the last 15 minutes are considered active
                    is_active = age_secs < 900
                except Exception:
                    rec_dt = None

            mvj = act.find(".//siri:MonitoredVehicleJourney", SIRI_NAMESPACE)
            if mvj is None:
                for c in act.iter():
                    if _clean_tag(c.tag) == "MonitoredVehicleJourney":
                        mvj = c
                        break
            if mvj is None:
                continue

            def _find_val(tag_name: str) -> Optional[str]:
                assert mvj is not None
                elem = mvj.find(f"siri:{tag_name}", SIRI_NAMESPACE)
                if elem is not None and elem.text:
                    return elem.text.strip()
                for c in mvj.iter():
                    if _clean_tag(c.tag) == tag_name and c.text:
                        return c.text.strip()
                return None

            line_name = (
                _find_val("PublishedLineName") or _find_val("LineRef") or "Unknown"
            )
            operator_ref = _find_val("OperatorRef") or "Unknown"
            vehicle_id = _find_val("VehicleRef") or "Unknown"
            direction = _find_val("DirectionRef") or "outbound"
            origin_name = (_find_val("OriginName") or "Origin").replace("_", " ")
            destination_name = (_find_val("DestinationName") or "Destination").replace(
                "_", " "
            )
            origin_ref = _find_val("OriginRef")
            destination_ref = _find_val("DestinationRef")

            aimed_dep_str = _find_val("OriginAimedDepartureTime")
            scheduled_dep = None
            if aimed_dep_str:
                if len(aimed_dep_str) >= 16 and "T" in aimed_dep_str:
                    scheduled_dep = aimed_dep_str.split("T", 1)[1][:5]
                elif len(aimed_dep_str) >= 5:
                    scheduled_dep = aimed_dep_str[:5]

            delay_raw = _find_val("Delay")
            delay_sec, delay_min, delay_status, formatted_delay = parse_iso_delay(
                delay_raw
            )

            # Location and bearing
            lat: Optional[float] = None
            lon: Optional[float] = None
            bearing: Optional[float] = None

            lat_str = _find_val("Latitude")
            lon_str = _find_val("Longitude")
            bearing_str = _find_val("Bearing")

            if lat_str and lon_str:
                try:
                    lat = float(lat_str)
                    lon = float(lon_str)
                except ValueError:
                    lat, lon = None, None

            if bearing_str:
                try:
                    bearing = float(bearing_str)
                except ValueError:
                    bearing = None

            status_entry = LiveBusStatus(
                vehicle_id=vehicle_id,
                line_name=line_name,
                operator_ref=operator_ref,
                direction=direction,
                origin_name=origin_name,
                destination_name=destination_name,
                origin_ref=origin_ref,
                destination_ref=destination_ref,
                scheduled_dep_time=scheduled_dep,
                delay_seconds=delay_sec,
                delay_minutes=delay_min,
                delay_status=delay_status if is_active else "Parked",
                formatted_delay=formatted_delay if is_active else "Inactive",
                delay_raw=delay_raw,
                latitude=lat,
                longitude=lon,
                bearing=bearing,
                recorded_at=rec_dt,
                is_active=is_active,
            )
            vehicles.append(status_entry)

        return vehicles

    def get_matching_vehicle(
        self,
        line_name: str,
        operator_ref: Optional[str] = None,
        scheduled_time: Optional[str] = None,
        origin_ref: Optional[str] = None,
        destination_ref: Optional[str] = None,
    ) -> Optional[LiveBusStatus]:
        """Find the best-matching active live vehicle for a scheduled bus service leg."""
        norm_line = (line_name or "").strip().lower()
        if not norm_line:
            return None

        try:
            vehicles = self.fetch_live_vehicles(
                operator_ref=operator_ref,
                line_ref=line_name.strip(),
            )
        except Exception as exc:
            logger.debug(
                "Failed to query live vehicles for line %s: %s", line_name, exc
            )
            return None

        # Filter to active vehicles matching the requested line name
        candidates = [
            v
            for v in vehicles
            if v.is_active and v.line_name.strip().lower() == norm_line
        ]

        if not candidates:
            return None

        # 1. Match on exact scheduled origin departure time if available
        if scheduled_time:
            for v in candidates:
                if v.scheduled_dep_time == scheduled_time:
                    return v

            # 2. Tolerant match within +/- 5 minutes
            sched_min = parse_time_to_minutes(scheduled_time)
            if sched_min is not None:
                for v in candidates:
                    if v.scheduled_dep_time:
                        v_min = parse_time_to_minutes(v.scheduled_dep_time)
                        if v_min is not None and abs(v_min - sched_min) <= 5:
                            return v

        # 3. Match on origin or destination references if available
        if destination_ref:
            dest_matches = [
                v for v in candidates if v.destination_ref == destination_ref
            ]
            if dest_matches:
                return dest_matches[0]

        if origin_ref:
            orig_matches = [v for v in candidates if v.origin_ref == origin_ref]
            if orig_matches:
                return orig_matches[0]

        # 4. Return first active vehicle
        return candidates[0]
