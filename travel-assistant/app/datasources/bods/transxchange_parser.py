"""TransXChange XML and dataset parser for UK bus timetables.

Provides secure XML deserialisation via defusedxml, extracting stops, operators,
timing sections, journey patterns, and vehicle journeys.
"""

from __future__ import annotations

import gzip
import io
from typing import Any, Dict, List, Optional, Set
import xml.etree.ElementTree as ET
import zipfile
import defusedxml.ElementTree as DefusedET

from app.datasources.bods.corridor_builder import group_trips_into_timetables
from app.datasources.bods.operating_profile import _clean_tag
from app.datasources.bods.service_parser import (
    parse_services,
    parse_vehicle_journeys,
)
from app.datasources.exceptions import DataSourceError
from app.utils.transit_time import parse_iso_duration_seconds


def _parse_stops_map(
    root: ET.Element, lookup: Dict[str, Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """Extract stop definitions from AnnotatedStopPointRef or StopPoint elements."""
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
                    "id": meta.get("id") or f"atco:{stop_ref}",
                    "name": meta.get("name") or common_name or stop_ref,
                    "indicator": meta.get("indicator") or indicator or "Bus Stop",
                    "type": "bus",
                    "icon": "directions_bus",
                    "latitude": meta.get("latitude"),
                    "longitude": meta.get("longitude"),
                }
    return stops_map


def _parse_operators_map(root: ET.Element) -> Dict[str, str]:
    """Extract operator mappings from Operator elements."""
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
    return operators_map


def _parse_sections_map(root: ET.Element) -> Dict[str, List[Dict[str, Any]]]:
    """Extract timing links from JourneyPatternSection elements."""
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
                            runtime_sec = parse_iso_duration_seconds(child.text)
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
    return sections_map


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

    if isinstance(xml_content, bytes):
        if xml_content.startswith(b"\x1f\x8b"):
            xml_content = gzip.decompress(xml_content).decode("utf-8", errors="replace")
        else:
            xml_content = xml_content.decode("utf-8", errors="replace")

    if not isinstance(xml_content, str) or not xml_content.strip():
        return []

    try:
        root = DefusedET.fromstring(xml_content)
    except ET.ParseError as e:
        raise DataSourceError(
            f"Failed to parse TransXChange XML: {str(e)}", provider="bods"
        ) from e

    stops_map = _parse_stops_map(root, lookup)
    operators_map = _parse_operators_map(root)
    sections_map = _parse_sections_map(root)
    (
        services_by_code,
        pattern_to_service,
        pattern_sequences,
    ) = parse_services(root, sections_map)

    raw_trips = parse_vehicle_journeys(
        root,
        pattern_sequences,
        services_by_code,
        pattern_to_service,
        operators_map,
    )

    return group_trips_into_timetables(raw_trips, stops_map, lookup, target_codes)


def parse_transxchange_dataset(
    dataset_bytes: bytes,
    target_stop_codes: Optional[Set[str]] = None,
    stop_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Parse raw dataset bytes (single TransXChange XML, GZIP, or ZIP archive)."""
    if not dataset_bytes:
        return []

    if dataset_bytes.startswith(b"PK\x03\x04"):
        timetables: List[Dict[str, Any]] = []
        try:
            with zipfile.ZipFile(io.BytesIO(dataset_bytes), "r") as zf:
                for name in zf.namelist():
                    if name.lower().endswith(".xml"):
                        try:
                            xml_bytes = zf.read(name)
                            parsed = parse_transxchange_xml(
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

    return parse_transxchange_xml(
        dataset_bytes,
        target_stop_codes=target_stop_codes,
        stop_lookup=stop_lookup,
    )
