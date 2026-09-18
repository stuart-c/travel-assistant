"""Operating profile parser for TransXChange timetables.

Parses operating days of the week, holidays, and bank holiday operations.
"""

from __future__ import annotations

from typing import Dict, Optional
import xml.etree.ElementTree as ET


def _clean_tag(tag: str) -> str:
    """Strip XML namespace prefix from tag name."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def parse_operating_profile(
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


_parse_operating_profile = parse_operating_profile
