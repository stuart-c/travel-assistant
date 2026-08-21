"""Client library for NaPTAN (National Public Transport Access Node) transit datasets."""

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

DEFAULT_RAIL_REFERENCES_URL = (
    "https://beta-naptan.dft.gov.uk/Download/File/RailReferences.csv"
)


def classify_stop_type(naptan_stop_type: str) -> str:
    """Classify a NaPTAN StopType into a canonical transit category."""
    st = (naptan_stop_type or "").upper().strip()
    if st in ("BCT", "BCS", "BCP", "BST"):
        return "bus"
    elif st in ("RLY", "RPL", "RSE"):
        return "rail"
    elif st in ("MET", "PLT"):
        return "metro"
    elif st in ("TMU",):
        return "tram"
    elif st in ("FTD", "FER"):
        return "ferry"
    elif st in ("AIR", "GAT"):
        return "air"
    return "bus" if not st else "other"


class NaptanClient(BaseDataSource):
    """Datasource client for NaPTAN public transit access nodes and stops."""

    provider_name: str = "naptan"

    def __init__(
        self,
        endpoint: str = DEFAULT_NAPTAN_STOPS_URL,
        timeout: int = 30,
    ) -> None:
        self.endpoint = endpoint or DEFAULT_NAPTAN_STOPS_URL
        self.timeout = timeout

    @classmethod
    def from_settings(cls, settings: Optional[Any] = None) -> "NaptanClient":
        """Instantiate NaptanClient (NaPTAN requires no API key)."""
        getter = cls.get_setting_getter(settings)
        endpoint = (
            getter("naptan_stops_url", DEFAULT_NAPTAN_STOPS_URL)
            or DEFAULT_NAPTAN_STOPS_URL
        )
        return cls(endpoint=endpoint)

    def validate_credentials(self) -> Dict[str, Any]:
        """Validate NaPTAN service availability (public open data)."""
        return {
            "valid": True,
            "message": "NaPTAN dataset is public open data and does not require credentials.",
        }

    def fetch_stops(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Fetch transit access nodes from NaPTAN CSV feed.

        Returns:
            List of dictionaries representing transit stops for repository insertion.
        """
        try:
            response = requests.get(self.endpoint, timeout=self.timeout)
            response.raise_for_status()

            reader = csv.DictReader(io.StringIO(response.text))
            stops: List[Dict[str, Any]] = []

            for row in reader:
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

                raw_stop_type = row.get("StopType") or row.get("stop_type") or ""
                stop_type = classify_stop_type(raw_stop_type)

                east_val = row.get("Easting") or row.get("easting")
                north_val = row.get("Northing") or row.get("northing")
                try:
                    easting = int(east_val) if east_val else None
                    northing = int(north_val) if north_val else None
                except (ValueError, TypeError):
                    easting, northing = None, None

                stops.append(
                    {
                        "atco_code": atco_code.strip(),
                        "naptan_code": (
                            row.get("NaptanCode") or row.get("naptan_code") or ""
                        ).strip()
                        or None,
                        "stop_type": stop_type,
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
                        "easting": easting,
                        "northing": northing,
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


class RailReferencesClient(BaseDataSource):
    """Datasource client for NaPTAN RailReferences.csv (TIPLOC/ATCO/CRS mapping).

    Downloads the rail references CSV from the UK government NaPTAN service,
    providing a lookup table that maps TIPLOC codes (used in Darwin XML timetable
    feeds) to NaPTAN ATCO codes and passenger-facing CRS codes.
    """

    provider_name: str = "naptan_rail_references"

    def __init__(
        self,
        endpoint: str = DEFAULT_RAIL_REFERENCES_URL,
        timeout: int = 30,
    ) -> None:
        self.endpoint = endpoint or DEFAULT_RAIL_REFERENCES_URL
        self.timeout = timeout

    @classmethod
    def from_settings(cls, settings: Optional[Any] = None) -> "RailReferencesClient":
        """Instantiate RailReferencesClient (NaPTAN requires no API key)."""
        getter = cls.get_setting_getter(settings)
        endpoint = (
            getter("naptan_rail_references_url", DEFAULT_RAIL_REFERENCES_URL)
            or DEFAULT_RAIL_REFERENCES_URL
        )
        return cls(endpoint=endpoint)

    def validate_credentials(self) -> Dict[str, Any]:
        """Validate NaPTAN service availability (public open data)."""
        return {
            "valid": True,
            "message": "NaPTAN RailReferences is public open data and does not require credentials.",
        }

    def fetch_rail_references(
        self, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch TIPLOC/ATCO/CRS rail reference mappings from NaPTAN CSV feed.

        Each row in ``RailReferences.csv`` maps a TIPLOC code to the corresponding
        NaPTAN ATCO code and passenger-facing CRS code. Rows without a TIPLOC are
        silently skipped.

        Args:
            limit: Optional maximum number of records to return (useful for testing).

        Returns:
            List of dicts with keys ``tiploc``, ``atco_code``, ``crs_code``.
        """
        try:
            response = requests.get(self.endpoint, timeout=self.timeout)
            response.raise_for_status()

            reader = csv.DictReader(io.StringIO(response.text))
            refs: List[Dict[str, Any]] = []

            for row in reader:
                tiploc = (
                    (
                        row.get("TiplocCode")
                        or row.get("tiploc_code")
                        or row.get("tiploc")
                        or ""
                    )
                    .strip()
                    .upper()
                )

                if not tiploc:
                    continue

                atco_code = (
                    row.get("AtcoCode") or row.get("atco_code") or row.get("atco") or ""
                ).strip() or None

                crs_code = (
                    row.get("CrsCode") or row.get("crs_code") or row.get("crs") or ""
                ).strip().upper() or None

                refs.append(
                    {
                        "tiploc": tiploc,
                        "atco_code": atco_code,
                        "crs_code": crs_code,
                    }
                )

                if limit is not None and len(refs) >= limit:
                    break

            return refs
        except requests.exceptions.Timeout as e:
            raise DataSourceConnectionError(
                f"NaPTAN RailReferences connection timed out: {str(e)}",
                provider=self.provider_name,
            ) from e
        except requests.exceptions.RequestException as e:
            raise DataSourceConnectionError(
                f"Network error connecting to NaPTAN RailReferences: {str(e)}",
                provider=self.provider_name,
            ) from e
        except Exception as e:
            raise DataSourceError(
                f"Unexpected error parsing NaPTAN RailReferences data: {str(e)}",
                provider=self.provider_name,
            ) from e
