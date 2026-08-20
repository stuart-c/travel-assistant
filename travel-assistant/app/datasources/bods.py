"""Client library for UK Bus Open Data Service (BODS) REST API and TransXChange timetables."""

import datetime
import gzip
import io
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import xml.etree.ElementTree as ET
import zipfile
import requests

from app.datasources.base import BaseDataSource
from app.datasources.exceptions import (
    DataSourceAuthError,
    DataSourceConfigError,
    DataSourceConnectionError,
    DataSourceError,
    DataSourceRateLimitError,
)
from app.models.setting import Setting

DEFAULT_BODS_BASE_URL = "https://data.bus-data.dft.gov.uk/api/v1/dataset"


def _clean_tag(tag: str) -> str:
    """Strip XML namespace prefix from tag name."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _parse_iso_duration_seconds(dur_str: Optional[str]) -> int:
    """Parse ISO 8601 duration string (e.g., PT10M, PT1H30M, PT45S, PT1M30S) into seconds."""
    if not dur_str:
        return 0
    s = str(dur_str).strip().upper()
    if not s.startswith("P"):
        return 0

    # Match hours, minutes, seconds components from PT#H#M#S
    match = re.search(
        r"PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?",
        s,
    )
    if not match:
        return 0

    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    return hours * 3600 + minutes * 60 + seconds


def _parse_time_str_to_seconds(time_str: Optional[str]) -> Optional[int]:
    """Parse HH:MM:SS or HH:MM string into seconds from midnight."""
    if not time_str:
        return None
    parts = str(time_str).strip().split(":")
    if len(parts) >= 2:
        try:
            h = int(parts[0])
            m = int(parts[1])
            s = int(parts[2]) if len(parts) > 2 else 0
            return h * 3600 + m * 60 + s
        except ValueError:
            return None
    return None


def _format_seconds_to_hh_mm(total_seconds: int) -> str:
    """Format seconds from midnight modulo 86400 into HH:MM string."""
    norm = total_seconds % 86400
    h = norm // 3600
    m = (norm % 3600) // 60
    return f"{h:02d}:{m:02d}"


class BodsClient(BaseDataSource):
    """Datasource client for the UK Bus Open Data Service (BODS)."""

    provider_name: str = "bods"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BODS_BASE_URL,
        timeout: float = 5.0,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.base_url = base_url.rstrip("/") if base_url else DEFAULT_BODS_BASE_URL
        self.timeout = float(timeout)

    @classmethod
    def from_settings(cls, settings: Optional[Any] = None) -> "BodsClient":
        """Instantiate BodsClient with credentials loaded from Setting model or provider."""
        getter = (
            settings.get_val
            if hasattr(settings, "get_val")
            else (settings.get if hasattr(settings, "get") else Setting.get_val)
        )
        return cls(api_key=getter("bus_api_key", ""))

    def validate_credentials(self) -> Dict[str, Any]:
        """Validate the BODS API key against the dataset endpoint."""
        valid, message = self.validate_tuple()
        return {"valid": valid, "message": message}

    def validate_tuple(self) -> Tuple[bool, str]:
        """Validate BODS API key returning a (valid, message) tuple."""
        if not self.api_key:
            return False, "Bus API key is empty. Please enter a valid API key."

        endpoint = (
            self.base_url
            if "/dataset" in self.base_url
            else f"{self.base_url}/dataset/"
        )
        params = {"api_key": self.api_key, "limit": 1}

        try:
            response = requests.get(endpoint, params=params, timeout=self.timeout)

            if response.status_code == 200:
                return True, "Bus API key is valid and active."
            elif response.status_code in (401, 403):
                return (
                    False,
                    f"Invalid Bus API key or unauthorised access (HTTP {response.status_code}).",
                )
            elif response.status_code == 429:
                return False, "BODS rate limit exceeded. Please try again later."
            else:
                return (
                    False,
                    f"Bus API returned unexpected status code {response.status_code}.",
                )
        except requests.exceptions.Timeout:
            return (
                False,
                f"Bus API validation request timed out after {self.timeout}s.",
            )
        except requests.exceptions.RequestException as e:
            return False, f"Network error during Bus API validation: {str(e)}"
        except Exception as e:
            return False, f"Unexpected error during Bus API validation: {str(e)}"

    def fetch_routes(self, limit: int = 25) -> List[Dict[str, Any]]:
        """Fetch active bus routes from BODS datasets."""
        if not self.api_key:
            raise DataSourceConfigError(
                "Bus API key is not configured.", provider=self.provider_name
            )

        url = (
            self.base_url
            if "/dataset" in self.base_url
            else f"{self.base_url}/dataset/"
        )
        params = {"api_key": self.api_key, "limit": limit, "status": "published"}

        try:
            response = requests.get(url, params=params, timeout=self.timeout)
            if response.status_code in (401, 403):
                raise DataSourceAuthError(
                    f"BODS authentication failed (HTTP {response.status_code}): "
                    "Invalid Bus API key.",
                    provider=self.provider_name,
                )
            elif response.status_code == 429:
                raise DataSourceRateLimitError(
                    "BODS rate limit exceeded.", provider=self.provider_name
                )
            response.raise_for_status()

            data = response.json()
            results = data.get("results", [])
            routes: List[Dict[str, Any]] = []

            for item in results:
                name = item.get("name", "").strip()
                nocs = item.get("noc", [])
                operator_code = nocs[0] if nocs and isinstance(nocs, list) else None
                description = item.get("description", "") or item.get("comment", "")
                operator_name = item.get("operator_name")

                lines = item.get("lines", [])
                if lines and isinstance(lines, list):
                    for line in lines:
                        line_name = (
                            line if isinstance(line, str) else str(line)
                        ).strip()
                        if not line_name:
                            continue
                        routes.append(
                            {
                                "route_number": line_name,
                                "operator_name": operator_name or name,
                                "operator_code": operator_code,
                                "origin": item.get("origin"),
                                "destination": item.get("destination"),
                                "description": description,
                            }
                        )
            return routes

        except requests.exceptions.Timeout as e:
            raise DataSourceConnectionError(
                f"BODS connection timed out: {str(e)}", provider=self.provider_name
            ) from e
        except requests.exceptions.RequestException as e:
            raise DataSourceConnectionError(
                f"Network error connecting to BODS: {str(e)}",
                provider=self.provider_name,
            ) from e
        except DataSourceError:
            raise
        except Exception as e:
            raise DataSourceError(
                f"Unexpected error fetching routes from BODS: {str(e)}",
                provider=self.provider_name,
            ) from e

    def download_dataset_file(self, download_url: str) -> bytes:
        """Download raw dataset file content (TransXChange XML or ZIP archive)."""
        if not self.api_key:
            raise DataSourceConfigError(
                "Bus API key is not configured.", provider=self.provider_name
            )
        if not download_url:
            raise DataSourceError(
                "Dataset download URL is empty.", provider=self.provider_name
            )

        try:
            params = {}
            if "api_key" not in download_url and "?" not in download_url:
                params["api_key"] = self.api_key

            response = requests.get(download_url, params=params, timeout=self.timeout)
            if response.status_code in (401, 403):
                raise DataSourceAuthError(
                    f"BODS authentication failed (HTTP {response.status_code}) "
                    "downloading dataset.",
                    provider=self.provider_name,
                )
            elif response.status_code == 429:
                raise DataSourceRateLimitError(
                    "BODS rate limit exceeded downloading dataset.",
                    provider=self.provider_name,
                )
            response.raise_for_status()
            return response.content

        except requests.exceptions.Timeout as e:
            raise DataSourceConnectionError(
                f"BODS download timed out: {str(e)}", provider=self.provider_name
            ) from e
        except requests.exceptions.RequestException as e:
            raise DataSourceConnectionError(
                f"Network error downloading dataset from BODS: {str(e)}",
                provider=self.provider_name,
            ) from e
        except DataSourceError:
            raise
        except Exception as e:
            raise DataSourceError(
                f"Unexpected error downloading dataset from BODS: {str(e)}",
                provider=self.provider_name,
            ) from e

    @staticmethod
    def parse_transxchange_xml(
        xml_content: Any,
        target_stop_codes: Optional[Set[str]] = None,
        stop_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Parse TransXChange XML timetable content into structured Timetable dictionaries."""
        lookup = stop_lookup or {}
        target_codes = (
            {c.upper().strip() for c in target_stop_codes if c}
            if target_stop_codes is not None
            else None
        )

        # Decode raw bytes if necessary
        if isinstance(xml_content, bytes):
            if xml_content.startswith(b"\x1f\x8b"):
                xml_content = gzip.decompress(xml_content).decode(
                    "utf-8", errors="replace"
                )
            else:
                xml_content = xml_content.decode("utf-8", errors="replace")

        if not isinstance(xml_content, str) or not xml_content.strip():
            return []

        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            raise DataSourceError(
                f"Failed to parse TransXChange XML: {str(e)}", provider="bods"
            ) from e

        # 1. Parse StopPoints (AnnotatedStopPointRef / StopPoint)
        stops_map: Dict[str, Dict[str, Any]] = {}
        for elem in root.iter():
            tag = _clean_tag(elem.tag)
            if tag in ("AnnotatedStopPointRef", "StopPoint"):
                stop_ref = ""
                common_name = ""
                indicator = ""
                for child in elem:
                    c_tag = _clean_tag(child.tag)
                    if c_tag == "StopPointRef" and child.text:
                        stop_ref = child.text.strip()
                    elif c_tag == "CommonName" and child.text:
                        common_name = child.text.strip()
                    elif c_tag == "Indicator" and child.text:
                        indicator = child.text.strip()
                if stop_ref:
                    meta = lookup.get(stop_ref.upper()) or {}
                    stops_map[stop_ref] = {
                        "id": stop_ref,
                        "name": meta.get("name") or common_name or stop_ref,
                        "indicator": meta.get("indicator") or indicator or "Bus Stop",
                        "type": "bus",
                        "icon": "directions_bus",
                        "latitude": meta.get("latitude"),
                        "longitude": meta.get("longitude"),
                    }

        # 2. Parse Operators
        operators_map: Dict[str, str] = {}
        for elem in root.iter():
            tag = _clean_tag(elem.tag)
            if tag == "Operator":
                op_id = elem.get("id", "").strip()
                op_name = ""
                for child in elem:
                    c_tag = _clean_tag(child.tag)
                    if (
                        c_tag
                        in ("OperatorShortName", "OperatorNameOnLicence", "TradingName")
                        and child.text
                    ):
                        op_name = child.text.strip()
                        break
                    elif c_tag == "NationalOperatorCode" and child.text:
                        op_name = child.text.strip()
                if op_id and op_name:
                    operators_map[op_id] = op_name

        # 3. Parse JourneyPatternSections
        sections_map: Dict[str, List[Dict[str, Any]]] = {}
        for elem in root.iter():
            tag = _clean_tag(elem.tag)
            if tag == "JourneyPatternSection":
                sec_id = elem.get("id", "").strip()
                links: List[Dict[str, Any]] = []
                for link in elem:
                    if _clean_tag(link.tag) == "JourneyPatternTimingLink":
                        from_ref = ""
                        to_ref = ""
                        runtime_sec = 0
                        for child in link:
                            c_tag = _clean_tag(child.tag)
                            if c_tag == "From":
                                for fc in child:
                                    if _clean_tag(fc.tag) == "StopPointRef" and fc.text:
                                        from_ref = fc.text.strip()
                            elif c_tag == "To":
                                for tc in child:
                                    if _clean_tag(tc.tag) == "StopPointRef" and tc.text:
                                        to_ref = tc.text.strip()
                            elif c_tag == "RunTime" and child.text:
                                runtime_sec = _parse_iso_duration_seconds(child.text)
                        if from_ref and to_ref:
                            links.append(
                                {
                                    "from": from_ref,
                                    "to": to_ref,
                                    "runtime_sec": runtime_sec,
                                }
                            )
                if sec_id:
                    sections_map[sec_id] = links

        # 4. Parse Services
        services: List[Dict[str, Any]] = []
        for elem in root.iter():
            tag = _clean_tag(elem.tag)
            if tag == "Service":
                svc_code = ""
                lines: List[str] = []
                origin = ""
                destination = ""
                start_date: Optional[datetime.date] = None
                end_date: Optional[datetime.date] = None
                monday = tuesday = wednesday = thursday = friday = saturday = sunday = (
                    True
                )
                bank_holiday = True
                patterns: Dict[str, Dict[str, Any]] = {}

                for child in elem:
                    c_tag = _clean_tag(child.tag)
                    if c_tag == "ServiceCode" and child.text:
                        svc_code = child.text.strip()
                    elif c_tag == "Lines":
                        for line_elem in child:
                            if _clean_tag(line_elem.tag) == "Line":
                                for lc in line_elem:
                                    if _clean_tag(lc.tag) == "LineName" and lc.text:
                                        lines.append(lc.text.strip())
                    elif c_tag == "OperatingPeriod":
                        for opc in child:
                            opc_tag = _clean_tag(opc.tag)
                            if opc_tag == "StartDate" and opc.text:
                                try:
                                    start_date = datetime.date.fromisoformat(
                                        opc.text.strip()[:10]
                                    )
                                except ValueError:
                                    pass
                            elif opc_tag == "EndDate" and opc.text:
                                try:
                                    end_date = datetime.date.fromisoformat(
                                        opc.text.strip()[:10]
                                    )
                                except ValueError:
                                    pass
                    elif c_tag == "OperatingProfile":
                        for opc in child:
                            if _clean_tag(opc.tag) == "RegularDayType":
                                for rdt in opc:
                                    if _clean_tag(rdt.tag) == "DaysOfWeek":
                                        day_tags = {_clean_tag(d.tag) for d in rdt}
                                        if day_tags:
                                            monday = (
                                                "Monday" in day_tags
                                                or "MondayToFriday" in day_tags
                                                or "MondayToSaturday" in day_tags
                                                or "MondayToSunday" in day_tags
                                            )
                                            tuesday = (
                                                "Tuesday" in day_tags
                                                or "MondayToFriday" in day_tags
                                                or "MondayToSaturday" in day_tags
                                                or "MondayToSunday" in day_tags
                                            )
                                            wednesday = (
                                                "Wednesday" in day_tags
                                                or "MondayToFriday" in day_tags
                                                or "MondayToSaturday" in day_tags
                                                or "MondayToSunday" in day_tags
                                            )
                                            thursday = (
                                                "Thursday" in day_tags
                                                or "MondayToFriday" in day_tags
                                                or "MondayToSaturday" in day_tags
                                                or "MondayToSunday" in day_tags
                                            )
                                            friday = (
                                                "Friday" in day_tags
                                                or "MondayToFriday" in day_tags
                                                or "MondayToSaturday" in day_tags
                                                or "MondayToSunday" in day_tags
                                            )
                                            saturday = (
                                                "Saturday" in day_tags
                                                or "Weekend" in day_tags
                                                or "MondayToSaturday" in day_tags
                                                or "MondayToSunday" in day_tags
                                            )
                                            sunday = (
                                                "Sunday" in day_tags
                                                or "Weekend" in day_tags
                                                or "MondayToSunday" in day_tags
                                            )
                            elif _clean_tag(opc.tag) == "BankHolidayOperation":
                                for bho in opc:
                                    if _clean_tag(bho.tag) == "DaysOfNonOperation":
                                        bank_holiday = False
                    elif c_tag == "StandardService":
                        for ssc in child:
                            ssc_tag = _clean_tag(ssc.tag)
                            if ssc_tag == "Origin" and ssc.text:
                                origin = ssc.text.strip()
                            elif ssc_tag == "Destination" and ssc.text:
                                destination = ssc.text.strip()
                            elif ssc_tag == "JourneyPattern":
                                jp_id = ssc.get("id", "").strip()
                                sec_refs: List[str] = []
                                for jpc in ssc:
                                    if (
                                        _clean_tag(jpc.tag)
                                        == "JourneyPatternSectionRefs"
                                        and jpc.text
                                    ):
                                        sec_refs.append(jpc.text.strip())
                                if jp_id:
                                    patterns[jp_id] = {"section_refs": sec_refs}

                line_name = lines[0] if lines else svc_code or "Bus"
                services.append(
                    {
                        "service_code": svc_code,
                        "line_name": line_name,
                        "origin": origin,
                        "destination": destination,
                        "start_date": start_date,
                        "end_date": end_date,
                        "monday": monday,
                        "tuesday": tuesday,
                        "wednesday": wednesday,
                        "thursday": thursday,
                        "friday": friday,
                        "saturday": saturday,
                        "sunday": sunday,
                        "bank_holiday": bank_holiday,
                        "patterns": patterns,
                    }
                )

        # Build full sequence of stops & cumulative offsets for each journey pattern
        pattern_sequences: Dict[str, Dict[str, Any]] = {}
        for svc in services:
            for jp_id, p_info in svc["patterns"].items():
                ordered_stops: List[str] = []
                cum_offsets: List[int] = []
                current_time = 0

                for sec_ref in p_info.get("section_refs", []):
                    links = sections_map.get(sec_ref, [])
                    for link in links:
                        from_st = link["from"]
                        to_st = link["to"]
                        runtime = link["runtime_sec"]

                        if not ordered_stops:
                            ordered_stops.append(from_st)
                            cum_offsets.append(current_time)

                        current_time += runtime
                        if not ordered_stops or ordered_stops[-1] != to_st:
                            ordered_stops.append(to_st)
                            cum_offsets.append(current_time)

                pattern_sequences[jp_id] = {
                    "stops": ordered_stops,
                    "offsets": cum_offsets,
                }

        # 5. Parse VehicleJourneys
        trips_by_pattern: Dict[str, List[Dict[str, Any]]] = {}
        for elem in root.iter():
            tag = _clean_tag(elem.tag)
            if tag == "VehicleJourney":
                vj_code = ""
                jp_ref = ""
                dep_time_str = ""
                operator_ref = ""

                for child in elem:
                    c_tag = _clean_tag(child.tag)
                    if c_tag == "VehicleJourneyCode" and child.text:
                        vj_code = child.text.strip()
                    elif c_tag == "JourneyPatternRef" and child.text:
                        jp_ref = child.text.strip()
                    elif c_tag == "DepartureTime" and child.text:
                        dep_time_str = child.text.strip()
                    elif c_tag == "OperatorRef" and child.text:
                        operator_ref = child.text.strip()

                if not jp_ref or not dep_time_str:
                    continue

                dep_sec = _parse_time_str_to_seconds(dep_time_str)
                if dep_sec is None:
                    continue

                p_seq = pattern_sequences.get(jp_ref)
                if not p_seq:
                    continue

                times = [
                    _format_seconds_to_hh_mm(dep_sec + offset)
                    for offset in p_seq["offsets"]
                ]
                op_name = operators_map.get(operator_ref) or operator_ref

                trip_obj = {
                    "id": vj_code
                    or f"trip_{len(trips_by_pattern.get(jp_ref, [])) + 1}",
                    "dep_sec": dep_sec,
                    "times": times,
                    "operator": op_name,
                }
                trips_by_pattern.setdefault(jp_ref, []).append(trip_obj)

        # 6. Build Timetable dictionaries
        timetables: List[Dict[str, Any]] = []

        for svc in services:
            for jp_id, p_info in svc["patterns"].items():
                p_seq = pattern_sequences.get(jp_id)
                if not p_seq or not p_seq["stops"]:
                    continue

                stop_refs = p_seq["stops"]

                # Filter by target stops if requested
                if target_codes is not None:
                    covers_target = any(
                        s.upper().strip() in target_codes for s in stop_refs
                    )
                    if not covers_target:
                        continue

                stops_list: List[Dict[str, Any]] = []
                for s_ref in stop_refs:
                    st_meta = stops_map.get(s_ref) or lookup.get(s_ref.upper()) or {}
                    stops_list.append(
                        {
                            "id": s_ref,
                            "name": st_meta.get("name") or s_ref,
                            "type": "bus",
                            "indicator": st_meta.get("indicator") or "Bus Stop",
                            "icon": "directions_bus",
                            "latitude": st_meta.get("latitude"),
                            "longitude": st_meta.get("longitude"),
                        }
                    )

                raw_trips = trips_by_pattern.get(jp_id, [])
                raw_trips.sort(key=lambda t: t.get("dep_sec", 0))

                origin_name = svc["origin"] or (
                    stops_list[0]["name"] if stops_list else "Origin"
                )
                dest_name = svc["destination"] or (
                    stops_list[-1]["name"] if stops_list else "Destination"
                )
                line_name = svc["line_name"]

                clean_trips: List[Dict[str, Any]] = []
                for idx, t in enumerate(raw_trips):
                    clean_trips.append(
                        {
                            "id": t.get("id") or f"trip_{idx + 1}",
                            "headsign": f"{line_name} to {dest_name}".strip(),
                            "operator": t.get("operator", ""),
                            "times": t.get("times", []),
                        }
                    )

                timetable_name = f"Bus {line_name}: {origin_name} to {dest_name}"

                timetables.append(
                    {
                        "name": timetable_name,
                        "transport_type": "bus",
                        "start_date": svc["start_date"],
                        "end_date": svc["end_date"],
                        "monday": svc["monday"],
                        "tuesday": svc["tuesday"],
                        "wednesday": svc["wednesday"],
                        "thursday": svc["thursday"],
                        "friday": svc["friday"],
                        "saturday": svc["saturday"],
                        "sunday": svc["sunday"],
                        "bank_holiday": svc["bank_holiday"],
                        "auto_added": True,
                        "content": {
                            "stops": stops_list,
                            "trips": clean_trips,
                        },
                    }
                )

        return timetables

    @classmethod
    def parse_transxchange_dataset(
        cls,
        dataset_bytes: bytes,
        target_stop_codes: Optional[Set[str]] = None,
        stop_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Parse raw dataset bytes (single TransXChange XML, GZIP, or ZIP archive)."""
        if not dataset_bytes:
            return []

        # Check if bytes are a ZIP archive
        if dataset_bytes.startswith(b"PK\x03\x04"):
            timetables: List[Dict[str, Any]] = []
            try:
                with zipfile.ZipFile(io.BytesIO(dataset_bytes), "r") as zf:
                    for name in zf.namelist():
                        if name.lower().endswith(".xml"):
                            try:
                                xml_bytes = zf.read(name)
                                parsed = cls.parse_transxchange_xml(
                                    xml_bytes,
                                    target_stop_codes=target_stop_codes,
                                    stop_lookup=stop_lookup,
                                )
                                timetables.extend(parsed)
                            except Exception:
                                continue
            except zipfile.BadZipFile as e:
                raise DataSourceError(
                    f"Corrupted ZIP archive from BODS: {str(e)}", provider="bods"
                ) from e
            return timetables

        # Fallback to direct XML / GZIP XML parsing
        return cls.parse_transxchange_xml(
            dataset_bytes,
            target_stop_codes=target_stop_codes,
            stop_lookup=stop_lookup,
        )

    def fetch_timetables(
        self,
        target_stop_codes: Optional[Set[str]] = None,
        admin_areas: Optional[List[str]] = None,
        stop_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """Fetch and parse published bus timetables covering target stops from BODS."""
        if not self.api_key:
            raise DataSourceConfigError(
                "Bus API key is not configured.", provider=self.provider_name
            )

        url = (
            self.base_url
            if "/dataset" in self.base_url
            else f"{self.base_url}/dataset/"
        )
        params: Dict[str, Any] = {
            "api_key": self.api_key,
            "status": "published",
            "limit": limit,
        }

        if admin_areas:
            clean_areas = [str(a).strip() for a in admin_areas if str(a).strip()]
            if clean_areas:
                params["adminArea"] = ",".join(clean_areas)

        try:
            response = requests.get(url, params=params, timeout=self.timeout)
            if response.status_code in (401, 403):
                raise DataSourceAuthError(
                    f"BODS authentication failed (HTTP {response.status_code}): "
                    "Invalid Bus API key.",
                    provider=self.provider_name,
                )
            elif response.status_code == 429:
                raise DataSourceRateLimitError(
                    "BODS rate limit exceeded.", provider=self.provider_name
                )
            response.raise_for_status()

            data = response.json()
            results = data.get("results", [])

            all_timetables: List[Dict[str, Any]] = []
            seen_names: Set[str] = set()

            for item in results:
                dl_url = item.get("url")
                if not dl_url:
                    continue

                try:
                    file_bytes = self.download_dataset_file(dl_url)
                    parsed_tt = self.parse_transxchange_dataset(
                        file_bytes,
                        target_stop_codes=target_stop_codes,
                        stop_lookup=stop_lookup,
                    )
                    for tt in parsed_tt:
                        name = tt.get("name")
                        if name and name not in seen_names:
                            seen_names.add(name)
                            all_timetables.append(tt)
                except (
                    DataSourceAuthError,
                    DataSourceConfigError,
                    DataSourceRateLimitError,
                ):
                    raise
                except Exception:
                    continue

            return all_timetables

        except requests.exceptions.Timeout as e:
            raise DataSourceConnectionError(
                f"BODS connection timed out: {str(e)}", provider=self.provider_name
            ) from e
        except requests.exceptions.RequestException as e:
            raise DataSourceConnectionError(
                f"Network error connecting to BODS: {str(e)}",
                provider=self.provider_name,
            ) from e
        except DataSourceError:
            raise
        except Exception as e:
            raise DataSourceError(
                f"Unexpected error fetching timetables from BODS: {str(e)}",
                provider=self.provider_name,
            ) from e
