"""Service and vehicle journey parser for TransXChange XML documents.

Extracts service metadata, line names, operating periods, journey patterns,
and trip timing instances.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

from app.datasources.bods.operating_profile import (
    _clean_tag,
    parse_operating_profile,
)
from app.utils.transit_time import (
    format_seconds_to_hh_mm,
    parse_time_str_to_seconds,
)


def parse_services(
    root: ET.Element, sections_map: Dict[str, List[Dict[str, Any]]]
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str], Dict[str, Dict[str, Any]]]:
    """Extract service definitions, lines, and journey pattern sequences."""
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
                    svc_days = parse_operating_profile(child, default_days=svc_days)
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
                        jp_days = parse_operating_profile(jpc, default_days=svc_days)

                if jp_id:
                    pattern_to_service[jp_id] = svc_code or line_name

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

    return services_by_code, pattern_to_service, pattern_sequences


def parse_vehicle_journeys(
    root: ET.Element,
    pattern_sequences: Dict[str, Dict[str, Any]],
    services_by_code: Dict[str, Dict[str, Any]],
    pattern_to_service: Dict[str, str],
    operators_map: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Extract individual vehicle journey trip instances."""
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

            dep_sec = parse_time_str_to_seconds(dep_time_str)
            if dep_sec is None:
                continue

            p_seq = pattern_sequences.get(jp_ref)
            if not p_seq or not p_seq["stops"]:
                continue

            resolved_svc_code = (
                svc_ref
                or p_seq.get("service_code")
                or pattern_to_service.get(jp_ref, "")
            )
            svc_info = services_by_code.get(resolved_svc_code) or default_service

            base_days = p_seq.get("days") or svc_info["days"]
            if vj_op_profile_elem is not None:
                vj_days = parse_operating_profile(
                    vj_op_profile_elem, default_days=base_days
                )
            else:
                vj_days = dict(base_days)

            times = [
                format_seconds_to_hh_mm(dep_sec + offset) for offset in p_seq["offsets"]
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

    return raw_trips
