"""Client library for NaPTAN (National Public Transport Access Node) bus stop datasets."""

import csv
import io
from typing import Any, Dict, List, Optional
import requests

from app.datasources.base import BaseDataSource
from app.datasources.exceptions import (
    DataSourceConnectionError,
    DataSourceError,
)

DEFAULT_NAPTAN_STOPS_URL = (
    "https://naptan.api.dft.gov.uk/v1/access-nodes?dataFormat=csv"
)


class NaptanClient(BaseDataSource):
    """Datasource client for NaPTAN public transit access nodes and bus stops."""

    provider_name: str = "naptan"

    def __init__(
        self,
        endpoint: str = DEFAULT_NAPTAN_STOPS_URL,
        timeout: int = 20,
    ) -> None:
        self.endpoint = endpoint
        self.timeout = timeout

    @classmethod
    def from_settings(cls, settings: Optional[Any] = None) -> "NaptanClient":
        """Instantiate NaptanClient (NaPTAN requires no API key)."""
        return cls()

    def validate_credentials(self) -> Dict[str, Any]:
        """Validate NaPTAN service availability (public open data)."""
        return {
            "valid": True,
            "message": "NaPTAN dataset is public open data and does not require credentials.",
        }

    def fetch_stops(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Fetch bus stops from NaPTAN CSV feed.

        Returns:
            List of dictionaries representing bus stops for repository insertion.
        """
        try:
            response = requests.get(self.endpoint, timeout=self.timeout)
            response.raise_for_status()

            reader = csv.DictReader(io.StringIO(response.text))
            stops: List[Dict[str, Any]] = []

            for row in reader:
                stop_type = (
                    (row.get("StopType") or row.get("stop_type") or "").strip().upper()
                )
                if stop_type and not stop_type.startswith(("BC", "BCT", "BCS", "BCQ")):
                    continue

                atco_code = row.get("ATCOCode") or row.get("atco_code") or ""
                name = row.get("CommonName") or row.get("name") or ""
                if not atco_code or not name:
                    continue

                lat_val = row.get("Latitude") or row.get("latitude")
                lon_val = row.get("Longitude") or row.get("longitude")

                try:
                    lat = float(lat_val) if lat_val else None
                    lon = float(lon_val) if lon_val else None
                except (ValueError, TypeError):
                    lat, lon = None, None

                stops.append(
                    {
                        "atco_code": atco_code.strip(),
                        "naptan_code": (
                            row.get("NaptanCode") or row.get("naptan_code") or ""
                        ).strip()
                        or None,
                        "name": name.strip(),
                        "indicator": (
                            row.get("Indicator") or row.get("indicator") or ""
                        ).strip()
                        or None,
                        "locality": (
                            row.get("LocalityName") or row.get("locality") or ""
                        ).strip()
                        or None,
                        "latitude": lat,
                        "longitude": lon,
                    }
                )

                if limit is not None and len(stops) >= limit:
                    break

            return stops
        except requests.exceptions.Timeout as e:
            raise DataSourceConnectionError(
                f"NaPTAN connection timed out: {str(e)}", provider=self.provider_name
            ) from e
        except requests.exceptions.RequestException as e:
            raise DataSourceConnectionError(
                f"Network error connecting to NaPTAN: {str(e)}",
                provider=self.provider_name,
            ) from e
        except Exception as e:
            raise DataSourceError(
                f"Unexpected error parsing NaPTAN data: {str(e)}",
                provider=self.provider_name,
            ) from e

    def fetch_rail_stations(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Fetch railway stations from NaPTAN CSV feed.

        Returns:
            List of dictionaries representing rail stations for repository insertion.
        """
        try:
            response = requests.get(self.endpoint, timeout=self.timeout)
            response.raise_for_status()

            reader = csv.DictReader(io.StringIO(response.text))
            stations: List[Dict[str, Any]] = []
            seen_crs = set()

            for row in reader:
                stop_type = (
                    (row.get("StopType") or row.get("stop_type") or "").strip().upper()
                )
                if stop_type and not stop_type.startswith(("RLY", "RPL", "MET")):
                    continue

                crs = (
                    (
                        row.get("CrsRef")
                        or row.get("CRSCode")
                        or row.get("CrsCode")
                        or row.get("crs_code")
                        or row.get("crs")
                        or ""
                    )
                    .strip()
                    .upper()
                )

                name = (row.get("CommonName") or row.get("name") or "").strip()
                if not name:
                    continue

                if not crs and stop_type == "RLY":
                    atco = (row.get("ATCOCode") or "").strip()
                    if len(atco) == 3 and atco.isalpha():
                        crs = atco.upper()

                if not crs or crs in seen_crs:
                    continue
                seen_crs.add(crs)

                lat_val = row.get("Latitude") or row.get("latitude")
                lon_val = row.get("Longitude") or row.get("longitude")

                try:
                    lat = float(lat_val) if lat_val else None
                    lon = float(lon_val) if lon_val else None
                except (ValueError, TypeError):
                    lat, lon = None, None

                tiploc = (
                    row.get("TiplocRef")
                    or row.get("TIPLOC")
                    or row.get("tiploc_code")
                    or row.get("tiploc")
                    or ""
                ).strip() or None

                operator = (
                    row.get("Operator")
                    or row.get("operator")
                    or row.get("toc")
                    or "National Rail"
                ).strip()

                stations.append(
                    {
                        "crs_code": crs,
                        "name": name,
                        "tiploc_code": tiploc,
                        "latitude": lat,
                        "longitude": lon,
                        "operator": operator,
                    }
                )

                if limit is not None and len(stations) >= limit:
                    break

            return stations
        except requests.exceptions.Timeout as e:
            raise DataSourceConnectionError(
                f"NaPTAN connection timed out: {str(e)}", provider=self.provider_name
            ) from e
        except requests.exceptions.RequestException as e:
            raise DataSourceConnectionError(
                f"Network error connecting to NaPTAN: {str(e)}",
                provider=self.provider_name,
            ) from e
        except Exception as e:
            raise DataSourceError(
                f"Unexpected error parsing NaPTAN rail station data: {str(e)}",
                provider=self.provider_name,
            ) from e
