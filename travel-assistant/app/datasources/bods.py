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


def _parse_operating_profile(
    elem: ET.Element,
    default_days: Optional[Dict[str, bool]] = None,
) -> Dict[str, bool]:
    """Parse OperatingProfile XML element for days of week and bank holiday flags."""
    days = (
        dict(default_days)
        if default_days is not None
        else {
            "monday": True,
            "tuesday": True,
            "wednesday": True,
            "thursday": True,
            "friday": True,
            "saturday": True,
            "sunday": True,
            "bank_holiday": True,
        }
    )

    for child in elem:
        c_tag = _clean_tag(child.tag)
        if c_tag == "RegularDayType":
            for rdt in child:
                rdt_tag = _clean_tag(rdt.tag)
                if rdt_tag == "DaysOfWeek":
                    day_tags = {_clean_tag(d.tag) for d in rdt}
                    if day_tags:
                        days["monday"] = (
                            "Monday" in day_tags
                            or "MondayToFriday" in day_tags
                            or "MondayToSaturday" in day_tags
                            or "MondayToSunday" in day_tags
                            or "MondayToThursday" in day_tags
                            or "SundayToThursday" in day_tags
                            or "NotSaturday" in day_tags
                            or "NotSunday" in day_tags
                        )
                        days["tuesday"] = (
                            "Tuesday" in day_tags
                            or "MondayToFriday" in day_tags
                            or "MondayToSaturday" in day_tags
                            or "MondayToSunday" in day_tags
                            or "MondayToThursday" in day_tags
                            or "TuesdayToFriday" in day_tags
                            or "SundayToThursday" in day_tags
                            or "NotSaturday" in day_tags
                            or "NotSunday" in day_tags
                        )
                        days["wednesday"] = (
                            "Wednesday" in day_tags
                            or "MondayToFriday" in day_tags
                            or "MondayToSaturday" in day_tags
                            or "MondayToSunday" in day_tags
                            or "MondayToThursday" in day_tags
                            or "TuesdayToFriday" in day_tags
                            or "SundayToThursday" in day_tags
                            or "NotSaturday" in day_tags
                            or "NotSunday" in day_tags
                        )
                        days["thursday"] = (
                            "Thursday" in day_tags
                            or "MondayToFriday" in day_tags
                            or "MondayToSaturday" in day_tags
                            or "MondayToSunday" in day_tags
                            or "MondayToThursday" in day_tags
                            or "TuesdayToFriday" in day_tags
                            or "SundayToThursday" in day_tags
                            or "NotSaturday" in day_tags
                            or "NotSunday" in day_tags
                        )
                        days["friday"] = (
                            "Friday" in day_tags
                            or "MondayToFriday" in day_tags
                            or "MondayToSaturday" in day_tags
                            or "MondayToSunday" in day_tags
                            or "TuesdayToFriday" in day_tags
                            or "NotSaturday" in day_tags
                            or "NotSunday" in day_tags
                        )
                        days["saturday"] = (
                            "Saturday" in day_tags
                            or "Weekend" in day_tags
                            or "SaturdayToSunday" in day_tags
                            or "MondayToSaturday" in day_tags
                            or "MondayToSunday" in day_tags
                            or "NotSunday" in day_tags
                        )
                        days["sunday"] = (
                            "Sunday" in day_tags
                            or "Weekend" in day_tags
                            or "SaturdayToSunday" in day_tags
                            or "SundayToThursday" in day_tags
                            or "MondayToSunday" in day_tags
                            or "NotSaturday" in day_tags
                        )
                elif rdt_tag == "HolidaysOnly":
                    days["monday"] = False
                    days["tuesday"] = False
                    days["wednesday"] = False
                    days["thursday"] = False
                    days["friday"] = False
                    days["saturday"] = False
                    days["sunday"] = False
                    days["bank_holiday"] = True
        elif c_tag == "BankHolidayOperation":
            for bho in child:
                bho_tag = _clean_tag(bho.tag)
                if bho_tag == "DaysOfNonOperation":
                    days["bank_holiday"] = False
                elif bho_tag == "DaysOfOperation":
                    days["bank_holiday"] = True

    return days


def _merge_stop_sequences(master: List[str], new_seq: List[str]) -> List[str]:
    """Merge new_seq into master stop sequence preserving relative visitation order."""
    if not master:
        return list(new_seq)
    if not new_seq:
        return list(master)

    res = list(master)
    curr_idx = 0
    for s in new_seq:
        if s in res[curr_idx:]:
            curr_idx = res.index(s, curr_idx) + 1
        elif s in res:
            curr_idx = res.index(s) + 1
        else:
            res.insert(curr_idx, s)
            curr_idx += 1
    return res


def _align_times_to_master(
    stops: List[str], times: List[Any], master_stops: List[str]
) -> List[Any]:
    """Align a trip's stop times onto master_stops, filling unvisited stops with empty string."""
    m_len = len(master_stops)
    aligned: List[Any] = [""] * m_len
    curr_m = 0
    for s, tm in zip(stops, times):
        while curr_m < m_len and master_stops[curr_m] != s:
            curr_m += 1
        if curr_m < m_len:
            aligned[curr_m] = tm
            curr_m += 1
    return aligned


def _align_subsequence(
    sub_stops: List[str], sub_times: List[str], master_stops: List[str]
) -> Optional[List[str]]:
    """Align sub_stops and sub_times onto master_stops, filling unvisited stops with empty string.

    Returns the aligned times list of length len(master_stops), or None if sub_stops is not a valid
    subsequence of master_stops.
    """
    m = len(master_stops)
    n = len(sub_stops)
    if n == 0:
        return [""] * m
    if n > m:
        return None

    # Search for an ordered matching of sub_stops inside master_stops
    for start_idx in range(m - n + 1):
        if master_stops[start_idx] == sub_stops[0]:
            matched_indices = [start_idx]
            curr_master = start_idx + 1
            matched = True
            for sub_idx in range(1, n):
                target = sub_stops[sub_idx]
                found = False
                while curr_master < m:
                    if master_stops[curr_master] == target:
                        matched_indices.append(curr_master)
                        curr_master += 1
                        found = True
                        break
                    curr_master += 1
                if not found:
                    matched = False
                    break
            if matched:
                aligned_times = [""] * m
                for s_idx, m_idx in enumerate(matched_indices):
                    aligned_times[m_idx] = (
                        sub_times[s_idx] if s_idx < len(sub_times) else ""
                    )
                return aligned_times
    return None


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
        getter = cls.get_setting_getter(settings)
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

    def fetch_routes(
        self,
        limit: Optional[int] = 25,
        page_size: int = 50,
    ) -> List[Dict[str, Any]]:
        """Fetch active bus routes from BODS datasets with pagination support."""
        if not self.api_key:
            raise DataSourceConfigError(
                "Bus API key is not configured.", provider=self.provider_name
            )

        url = (
            self.base_url
            if "/dataset" in self.base_url
            else f"{self.base_url}/dataset/"
        )
        offset = 0
        batch_limit = min(limit, page_size) if limit is not None else page_size
        results: List[Dict[str, Any]] = []

        try:
            while True:
                params: Dict[str, Any] = {
                    "api_key": self.api_key,
                    "status": "published",
                    "limit": batch_limit,
                    "offset": offset,
                }
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
                page_results = data.get("results", [])
                if not page_results:
                    break

                results.extend(page_results)
                offset += len(page_results)

                if limit is not None and len(results) >= limit:
                    results = results[:limit]
                    break

                if not data.get("next"):
                    break

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
        services_by_code: Dict[str, Dict[str, Any]] = {}
        pattern_to_service: Dict[str, str] = {}
        pattern_sequences: Dict[str, Dict[str, Any]] = {}

        for elem in root.iter():
            tag = _clean_tag(elem.tag)
            if tag == "Service":
                svc_code = ""
                lines: List[str] = []
                origin = ""
                destination = ""
                start_date: Optional[datetime.date] = None
                end_date: Optional[datetime.date] = None
                svc_days: Dict[str, bool] = {
                    "monday": True,
                    "tuesday": True,
                    "wednesday": True,
                    "thursday": True,
                    "friday": True,
                    "saturday": True,
                    "sunday": True,
                    "bank_holiday": True,
                }
                patterns_elem: List[ET.Element] = []

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
                        svc_days = _parse_operating_profile(
                            child, default_days=svc_days
                        )
                    elif c_tag == "StandardService":
                        for ssc in child:
                            ssc_tag = _clean_tag(ssc.tag)
                            if ssc_tag == "Origin" and ssc.text:
                                origin = ssc.text.strip()
                            elif ssc_tag == "Destination" and ssc.text:
                                destination = ssc.text.strip()
                            elif ssc_tag == "JourneyPattern":
                                patterns_elem.append(ssc)

                line_name = lines[0] if lines else svc_code or "Bus"
                svc_info = {
                    "service_code": svc_code,
                    "line_name": line_name,
                    "origin": origin,
                    "destination": destination,
                    "start_date": start_date,
                    "end_date": end_date,
                    "days": svc_days,
                }
                if svc_code:
                    services_by_code[svc_code] = svc_info
                # Also store under line_name as fallback
                services_by_code.setdefault(line_name, svc_info)

                for jp_elem in patterns_elem:
                    jp_id = jp_elem.get("id", "").strip()
                    sec_refs: List[str] = []
                    direction = ""
                    jp_days = dict(svc_days)

                    for jpc in jp_elem:
                        jpc_tag = _clean_tag(jpc.tag)
                        if jpc_tag == "JourneyPatternSectionRefs" and jpc.text:
                            sec_refs.append(jpc.text.strip())
                        elif jpc_tag == "Direction" and jpc.text:
                            direction = jpc.text.strip().lower()
                        elif jpc_tag == "OperatingProfile":
                            jp_days = _parse_operating_profile(
                                jpc, default_days=svc_days
                            )

                    if jp_id:
                        pattern_to_service[jp_id] = svc_code or line_name

                        # Build ordered stops and offsets for journey pattern
                        ordered_stops: List[str] = []
                        cum_offsets: List[int] = []
                        current_time = 0

                        for sec_ref in sec_refs:
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
                            "direction": direction,
                            "days": jp_days,
                            "service_code": svc_code,
                            "line_name": line_name,
                            "start_date": start_date,
                            "end_date": end_date,
                            "origin": origin,
                            "destination": destination,
                        }

        default_service: Dict[str, Any] = {
            "service_code": "",
            "line_name": "Bus",
            "origin": "",
            "destination": "",
            "start_date": None,
            "end_date": None,
            "days": {
                "monday": True,
                "tuesday": True,
                "wednesday": True,
                "thursday": True,
                "friday": True,
                "saturday": True,
                "sunday": True,
                "bank_holiday": True,
            },
        }

        # 5. Parse VehicleJourneys
        raw_trips: List[Dict[str, Any]] = []
        for elem in root.iter():
            tag = _clean_tag(elem.tag)
            if tag == "VehicleJourney":
                vj_code = ""
                jp_ref = ""
                svc_ref = ""
                dep_time_str = ""
                operator_ref = ""
                vj_op_profile_elem: Optional[ET.Element] = None
                vj_start_date: Optional[datetime.date] = None
                vj_end_date: Optional[datetime.date] = None

                for child in elem:
                    c_tag = _clean_tag(child.tag)
                    if c_tag == "VehicleJourneyCode" and child.text:
                        vj_code = child.text.strip()
                    elif c_tag == "JourneyPatternRef" and child.text:
                        jp_ref = child.text.strip()
                    elif c_tag == "ServiceRef" and child.text:
                        svc_ref = child.text.strip()
                    elif c_tag == "DepartureTime" and child.text:
                        dep_time_str = child.text.strip()
                    elif c_tag == "OperatorRef" and child.text:
                        operator_ref = child.text.strip()
                    elif c_tag == "OperatingProfile":
                        vj_op_profile_elem = child
                    elif c_tag == "OperatingPeriod":
                        for opc in child:
                            opc_tag = _clean_tag(opc.tag)
                            if opc_tag == "StartDate" and opc.text:
                                try:
                                    vj_start_date = datetime.date.fromisoformat(
                                        opc.text.strip()[:10]
                                    )
                                except ValueError:
                                    pass
                            elif opc_tag == "EndDate" and opc.text:
                                try:
                                    vj_end_date = datetime.date.fromisoformat(
                                        opc.text.strip()[:10]
                                    )
                                except ValueError:
                                    pass

                if not jp_ref or not dep_time_str:
                    continue

                dep_sec = _parse_time_str_to_seconds(dep_time_str)
                if dep_sec is None:
                    continue

                p_seq = pattern_sequences.get(jp_ref)
                if not p_seq or not p_seq["stops"]:
                    continue

                # Resolve service info
                resolved_svc_code = (
                    svc_ref
                    or p_seq.get("service_code")
                    or pattern_to_service.get(jp_ref, "")
                )
                svc_info = services_by_code.get(resolved_svc_code) or default_service

                # Resolve operating days for this vehicle journey
                base_days = p_seq.get("days") or svc_info["days"]
                if vj_op_profile_elem is not None:
                    vj_days = _parse_operating_profile(
                        vj_op_profile_elem, default_days=base_days
                    )
                else:
                    vj_days = dict(base_days)

                times = [
                    _format_seconds_to_hh_mm(dep_sec + offset)
                    for offset in p_seq["offsets"]
                ]
                op_name = operators_map.get(operator_ref) or operator_ref

                raw_trips.append(
                    {
                        "id": vj_code or f"trip_{len(raw_trips) + 1}",
                        "line_name": p_seq.get("line_name")
                        or svc_info.get("line_name")
                        or "Bus",
                        "direction": p_seq.get("direction", ""),
                        "stops": list(p_seq["stops"]),
                        "times": times,
                        "dep_sec": dep_sec,
                        "operator": op_name,
                        "days": vj_days,
                        "start_date": vj_start_date
                        or p_seq.get("start_date")
                        or svc_info.get("start_date"),
                        "end_date": vj_end_date
                        or p_seq.get("end_date")
                        or svc_info.get("end_date"),
                    }
                )

        # 6. Group trips into Timetables by Line, Operating Days, and Corridors
        # First group trips by (line_name, days_tuple)
        trips_by_line_days: Dict[Tuple[str, Tuple[bool, ...]], List[Dict[str, Any]]] = (
            {}
        )

        for trip in raw_trips:
            l_name = trip["line_name"]
            d_dict = trip["days"]
            days_tuple = (
                bool(d_dict.get("monday", True)),
                bool(d_dict.get("tuesday", True)),
                bool(d_dict.get("wednesday", True)),
                bool(d_dict.get("thursday", True)),
                bool(d_dict.get("friday", True)),
                bool(d_dict.get("saturday", True)),
                bool(d_dict.get("sunday", True)),
                bool(d_dict.get("bank_holiday", True)),
            )
            trips_by_line_days.setdefault((l_name, days_tuple), []).append(trip)

        def _can_merge_corridor(master_stops: List[str], trip_stops: List[str]) -> bool:
            """Check if trip_stops flows in the same direction as master_stops without reversals."""
            if not master_stops or not trip_stops:
                return True
            common_stops = [s for s in trip_stops if s in master_stops]
            if len(common_stops) < 2:
                return True
            master_indices = [master_stops.index(s) for s in common_stops]
            return all(
                master_indices[i] < master_indices[i + 1]
                for i in range(len(master_indices) - 1)
            )

        timetables: List[Dict[str, Any]] = []

        for (l_name, days_tuple), line_trips in trips_by_line_days.items():
            # Check if any trip or service in this group is circular
            has_circular = any(
                (t["stops"][0] == t["stops"][-1] and len(t["stops"]) > 1)
                or t.get("direction") in ("circular", "clockwise", "anticlockwise")
                for t in line_trips
            )

            # Sort trips descending by stop count so longer full-length routes form initial master sequences
            sorted_line_trips = sorted(
                line_trips, key=lambda t: len(t.get("stops", [])), reverse=True
            )

            corridors: List[Dict[str, Any]] = []

            for trip in sorted_line_trips:
                t_stops = trip["stops"]
                if not t_stops:
                    continue

                t_dir = trip.get("direction", "").strip().lower()
                is_trip_circular = (
                    has_circular
                    or (t_stops[0] == t_stops[-1] and len(t_stops) > 1)
                    or t_dir in ("circular", "clockwise", "anticlockwise")
                )

                merged = False
                for corr in corridors:
                    if is_trip_circular:
                        if corr["is_circular"]:
                            corr["master_stops"] = _merge_stop_sequences(
                                corr["master_stops"], t_stops
                            )
                            corr["trips"].append(trip)
                            merged = True
                            break
                    else:
                        if not corr["is_circular"]:
                            # If directions match or are unspecified, check flow order compatibility
                            if (
                                not t_dir
                                or not corr["direction"]
                                or t_dir == corr["direction"]
                            ):
                                if _can_merge_corridor(corr["master_stops"], t_stops):
                                    corr["master_stops"] = _merge_stop_sequences(
                                        corr["master_stops"], t_stops
                                    )
                                    corr["trips"].append(trip)
                                    if not corr["direction"] and t_dir:
                                        corr["direction"] = t_dir
                                    merged = True
                                    break

                if not merged:
                    corridors.append(
                        {
                            "is_circular": is_trip_circular,
                            "direction": t_dir,
                            "master_stops": list(t_stops),
                            "trips": [trip],
                        }
                    )

            for corr in corridors:
                master_stops = corr["master_stops"]
                corr_trips = corr["trips"]
                if not master_stops or not corr_trips:
                    continue

            # Filter by target stops if requested
            if target_codes is not None:
                covers_target = any(
                    s.upper().strip() in target_codes for s in master_stops
                )
                if not covers_target:
                    continue

            stops_list: List[Dict[str, Any]] = []
            for s_ref in master_stops:
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

            first_name = stops_list[0]["name"] if stops_list else "Origin"
            last_name = stops_list[-1]["name"] if stops_list else "Destination"
            first_id = stops_list[0]["id"] if stops_list else ""
            last_id = stops_list[-1]["id"] if stops_list else ""

            if corr["is_circular"] or (
                first_id and last_id and first_id == last_id and len(stops_list) > 1
            ):
                timetable_name = f"Bus {l_name}: {first_name} (Circular)"
            else:
                timetable_name = f"Bus {l_name}: {first_name} to {last_name}"

            # Align each trip's times onto the master stop sequence
            aligned_trips: List[Dict[str, Any]] = []
            seen_trip_ids: Set[str] = set()

            # Sort trips chronologically
            sorted_trips = sorted(corr_trips, key=lambda t: t.get("dep_sec", 0))

            for idx, t in enumerate(sorted_trips):
                tid = t.get("id") or f"trip_{idx + 1}"
                if tid in seen_trip_ids:
                    continue
                seen_trip_ids.add(tid)

                aligned_times = _align_times_to_master(
                    t["stops"], t["times"], master_stops
                )
                aligned_trips.append(
                    {
                        "id": tid,
                        "headsign": f"{l_name} to {last_name}".strip(),
                        "operator": t.get("operator", ""),
                        "times": aligned_times,
                    }
                )

            # Determine start and end date
            start_date = corr_trips[0].get("start_date")
            end_date = corr_trips[0].get("end_date")

            (
                mon,
                tue,
                wed,
                thu,
                fri,
                sat,
                sun,
                bh,
            ) = days_tuple

            timetables.append(
                {
                    "name": timetable_name,
                    "transport_type": "bus",
                    "start_date": start_date,
                    "end_date": end_date,
                    "monday": mon,
                    "tuesday": tue,
                    "wednesday": wed,
                    "thursday": thu,
                    "friday": fri,
                    "saturday": sat,
                    "sunday": sun,
                    "bank_holiday": bh,
                    "auto_added": True,
                    "content": {
                        "stops": stops_list,
                        "trips": aligned_trips,
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
        limit: Optional[int] = None,
        page_size: int = 50,
    ) -> List[Dict[str, Any]]:
        """Fetch and parse published bus timetables covering target stops from BODS.

        Supports multi-page pagination across all available datasets and merges
        trips for identical routes and operating day profiles.
        """
        if not self.api_key:
            raise DataSourceConfigError(
                "Bus API key is not configured.", provider=self.provider_name
            )

        url = (
            self.base_url
            if "/dataset" in self.base_url
            else f"{self.base_url}/dataset/"
        )
        offset = 0
        batch_limit = min(limit, page_size) if limit is not None else page_size
        results: List[Dict[str, Any]] = []

        try:
            while True:
                params: Dict[str, Any] = {
                    "api_key": self.api_key,
                    "status": "published",
                    "limit": batch_limit,
                    "offset": offset,
                }
                if admin_areas:
                    clean_areas = [
                        str(a).strip() for a in admin_areas if str(a).strip()
                    ]
                    if clean_areas:
                        params["adminArea"] = ",".join(clean_areas)

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
                page_results = data.get("results", [])
                if not page_results:
                    break

                results.extend(page_results)
                offset += len(page_results)

                if limit is not None and len(results) >= limit:
                    results = results[:limit]
                    break

                if not data.get("next"):
                    break

            timetables_by_key: Dict[Tuple[str, Tuple[bool, ...]], Dict[str, Any]] = {}

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
                        name = tt.get("name") or "Bus"
                        days_key = (
                            bool(tt.get("monday")),
                            bool(tt.get("tuesday")),
                            bool(tt.get("wednesday")),
                            bool(tt.get("thursday")),
                            bool(tt.get("friday")),
                            bool(tt.get("saturday")),
                            bool(tt.get("sunday")),
                            bool(tt.get("bank_holiday")),
                        )
                        key = (name, days_key)

                        if key in timetables_by_key:
                            # Merge trips and combine stops into existing timetable
                            existing = timetables_by_key[key]
                            existing_stops = [
                                s.get("id", "")
                                for s in existing.get("content", {}).get("stops", [])
                            ]
                            new_stops = [
                                s.get("id", "")
                                for s in tt.get("content", {}).get("stops", [])
                            ]

                            # Unified stop sequence
                            combined_stops = _merge_stop_sequences(
                                existing_stops, new_stops
                            )

                            # Rebuild stops metadata list
                            stop_meta_by_id = {
                                s.get("id"): s
                                for s in existing.get("content", {}).get("stops", [])
                            }
                            for s in tt.get("content", {}).get("stops", []):
                                if s.get("id") and s.get("id") not in stop_meta_by_id:
                                    stop_meta_by_id[s.get("id")] = s

                            combined_stops_list = [
                                stop_meta_by_id.get(
                                    sid, {"id": sid, "name": sid, "type": "bus"}
                                )
                                for sid in combined_stops
                            ]

                            # Re-align existing trips onto combined stops
                            existing_trips = existing.get("content", {}).get(
                                "trips", []
                            )
                            for t in existing_trips:
                                t["times"] = _align_times_to_master(
                                    existing_stops, t.get("times", []), combined_stops
                                )

                            # Align and append new trips
                            new_trips = tt.get("content", {}).get("trips", [])
                            seen_trip_ids = {
                                t.get("id") for t in existing_trips if t.get("id")
                            }

                            for nt in new_trips:
                                tid = nt.get("id")
                                if not tid or tid not in seen_trip_ids:
                                    if tid:
                                        seen_trip_ids.add(tid)
                                    nt["times"] = _align_times_to_master(
                                        new_stops, nt.get("times", []), combined_stops
                                    )
                                    existing_trips.append(nt)

                            def _first_time_val(trip: Dict[str, Any]) -> str:
                                for tm in trip.get("times", []):
                                    if isinstance(tm, str) and tm.strip():
                                        return tm.strip()
                                return "99:99"

                            existing_trips.sort(key=_first_time_val)
                            existing["content"]["stops"] = combined_stops_list
                            existing["content"]["trips"] = existing_trips
                        else:
                            timetables_by_key[key] = tt
                except (
                    DataSourceAuthError,
                    DataSourceConfigError,
                    DataSourceRateLimitError,
                ):
                    raise
                except Exception:
                    continue

            return list(timetables_by_key.values())

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
