"""Journey departure evaluation and notification timing engine."""

import datetime
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from app.datasources.train_live import TrainLiveClient
from app.models.journey import Journey, JourneyTimeSetting
from app.models.setting import Setting
from app.services.planner.exceptions import JourneyPlanningError
from app.services.planner.raptor import plan_journey
from app.services.planner.transfers import (
    DAY_NAME_TO_CODE,
    format_minutes_to_time,
    parse_time_to_minutes,
)

logger = logging.getLogger(__name__)


@dataclass
class DepartureCandidate:
    """A viable upcoming transit departure candidate for a journey."""

    journey_id: int
    journey_name: str
    service_key: str
    transit_mode: str
    line_name: str
    operator_name: Optional[str]
    origin_stop_name: str
    origin_stop_id: str
    dest_stop_name: str
    dest_stop_id: str
    final_dest_name: str
    transit_dep_minutes: int
    transit_dep_time: str
    walk_minutes: int
    leave_minutes: int
    leave_time: str
    arrival_time: str
    notification_trigger_minutes: int
    is_live: bool = False
    delay_minutes: int = 0
    platform: Optional[str] = None
    itinerary: Optional[Any] = None


def get_journey_estimated_duration_minutes(
    journey: Journey,
    default_minutes: int = 120,
) -> int:
    """Estimate journey duration in minutes from calculated routes or fallback default."""
    try:
        routes = journey.get_calculated_routes()
        if routes and isinstance(routes, list):
            durations = [
                int(r.get("total_duration_est_minutes"))
                for r in routes
                if isinstance(r, dict)
                and r.get("total_duration_est_minutes") is not None
            ]
            if durations:
                return max(max(durations), 60)
    except Exception:
        pass
    return default_minutes


def is_journey_active_for_datetime(
    journey: Journey,
    dt: datetime.datetime,
) -> Tuple[bool, Optional[JourneyTimeSetting]]:
    """Determine whether a journey has an active time window matching the specified datetime.

    Checks day of week matching (mon..sun, bank_holiday) and whether current time is within
    or approaching the configured active time window. For departure mode, allows a 30-minute
    advance evaluation margin. For arrival mode, factors in estimated journey duration and
    advance notification trigger margins.
    """
    time_settings = journey.get_time_settings()
    if not time_settings:
        # If no explicit time windows are configured, journey is not scheduled for time-based alerts
        return False, None

    weekday_idx = dt.weekday()
    day_names = [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ]
    current_day_code = DAY_NAME_TO_CODE.get(day_names[weekday_idx], "")
    current_minutes = dt.hour * 60 + dt.minute

    for ts_dict in time_settings:
        if isinstance(ts_dict, dict):
            try:
                ts = JourneyTimeSetting.model_validate(ts_dict)
            except Exception:
                continue
        elif isinstance(ts_dict, JourneyTimeSetting):
            ts = ts_dict
        else:
            continue

        # Check day match
        if ts.days and current_day_code not in ts.days:
            continue

        start_min = parse_time_to_minutes(ts.start_time)
        end_min = parse_time_to_minutes(ts.end_time)

        # If both are omitted, active all day on matching days
        if start_min is None and end_min is None:
            return True, ts

        mode = (ts.mode or "depart").strip().lower()

        if mode == "arrive":
            est_duration = get_journey_estimated_duration_minutes(journey)
            # Advance evaluation margin: journey duration + 15m notification window + 30m buffer
            advance_margin = est_duration + 45
            effective_start = (
                max(0, start_min - advance_margin) if start_min is not None else 0
            )
            effective_end = end_min if end_min is not None else 1440
        else:
            # Standard "depart" mode: 30 minutes advance evaluation before departure window start
            effective_start = (start_min - 30) if start_min is not None else 0
            effective_end = end_min if end_min is not None else 1440

        if effective_start <= current_minutes <= effective_end:
            return True, ts

    return False, None


def extract_departure_candidates(
    journey: Journey,
    dt: datetime.datetime,
    max_plans: int = 5,
) -> List[DepartureCandidate]:
    """Calculate upcoming scheduled itineraries and extract transit departure candidates."""
    current_minutes = dt.hour * 60 + dt.minute
    time_str = format_minutes_to_time(current_minutes)
    date_obj = dt.date()

    weekday_idx = dt.weekday()
    day_names = [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ]
    day_code = DAY_NAME_TO_CODE.get(day_names[weekday_idx], "mon")

    try:
        itineraries = plan_journey(
            from_type=journey.from_type,
            from_id=journey.from_id,
            to_type=journey.to_type,
            to_id=journey.to_id,
            timing_mode="depart",
            time_str=time_str,
            days_of_week=[day_code],
            target_date=date_obj,
            max_itineraries=max_plans,
        )
    except JourneyPlanningError as exc:
        logger.debug(
            "No itineraries discovered for journey %d (%s) at %s: %s",
            journey.id,
            journey.name,
            time_str,
            exc,
        )
        return []

    candidates: List[DepartureCandidate] = []

    for itin in itineraries:
        if not itin.legs:
            continue

        walk_mins = 0
        transit_leg = None

        # Determine walking access and first transit leg
        first_leg = itin.legs[0]
        if first_leg.mode == "walk":
            walk_mins = first_leg.duration_minutes
            if len(itin.legs) > 1:
                transit_leg = itin.legs[1]
        else:
            transit_leg = first_leg

        if not transit_leg or not transit_leg.dep_time:
            continue

        transit_dep_min = parse_time_to_minutes(transit_leg.dep_time)
        if transit_dep_min is None:
            continue

        leave_min = transit_dep_min - walk_mins
        leave_time_str = format_minutes_to_time(leave_min)
        trigger_min = leave_min - 15

        service_key = (
            f"j{journey.id}_{transit_leg.mode}_{transit_leg.line or 'direct'}_"
            f"{transit_leg.dep_time}_{date_obj.isoformat()}"
        )

        cand = DepartureCandidate(
            journey_id=journey.id,
            journey_name=journey.name,
            service_key=service_key,
            transit_mode=transit_leg.mode,
            line_name=transit_leg.line or "",
            operator_name=transit_leg.operator,
            origin_stop_name=transit_leg.origin.name,
            origin_stop_id=transit_leg.origin.id,
            dest_stop_name=transit_leg.destination.name,
            dest_stop_id=transit_leg.destination.id,
            final_dest_name=journey.to_name,
            transit_dep_minutes=transit_dep_min,
            transit_dep_time=transit_leg.dep_time,
            walk_minutes=walk_mins,
            leave_minutes=leave_min,
            leave_time=leave_time_str,
            arrival_time=itin.arrival_time,
            notification_trigger_minutes=trigger_min,
            itinerary=itin,
        )
        candidates.append(cand)

    # Sort candidates by departure timing
    candidates.sort(key=lambda c: c.transit_dep_minutes)
    return candidates


def apply_live_departure_adjustments(
    candidate: DepartureCandidate,
    live_client: Optional[TrainLiveClient] = None,
) -> DepartureCandidate:
    """Optionally probe live departure board feeds to refine departure timings."""
    if not live_client:
        return candidate

    if candidate.transit_mode != "rail":
        return candidate

    # Extract station CRS code if available
    crs = candidate.origin_stop_id
    if crs.startswith("naptan:"):
        crs = crs[len("naptan:") :]

    if len(crs) != 3 or not crs.isalpha():
        return candidate

    dest_crs = candidate.dest_stop_id
    if dest_crs.startswith("naptan:"):
        dest_crs = dest_crs[len("naptan:") :]

    try:
        departures = live_client.get_fastest_departures(crs, [dest_crs])
        # If live departure times are obtained, update candidate departure time

        if departures and isinstance(departures, list):
            first_dep = departures[0]
            std = first_dep.get("std")  # Scheduled
            etd = first_dep.get("etd")  # Expected
            platform = first_dep.get("platform")
            if platform:
                candidate.platform = str(platform).strip()
            if std == candidate.transit_dep_time and etd and etd != "On time":
                live_min = parse_time_to_minutes(etd)
                if live_min is not None:
                    delay = live_min - candidate.transit_dep_minutes
                    candidate.delay_minutes = delay
                    candidate.transit_dep_minutes = live_min
                    candidate.transit_dep_time = etd
                    candidate.leave_minutes = live_min - candidate.walk_minutes
                    candidate.leave_time = format_minutes_to_time(
                        candidate.leave_minutes
                    )
                    candidate.notification_trigger_minutes = (
                        candidate.leave_minutes - 15
                    )
                    candidate.is_live = True
    except Exception as exc:
        logger.debug("Live departure probe skipped for %s: %s", crs, exc)

    return candidate


def evaluate_journey_notification(
    journey: Journey,
    dt: datetime.datetime,
    sent_keys: Set[str],
    live_client: Optional[TrainLiveClient] = None,
    tolerance_minutes: int = 1,
) -> Optional[DepartureCandidate]:
    """Evaluate whether a journey departure notification should be dispatched now.

    Identifies the next viable upcoming transit candidate whose leave time has not passed.
    Triggers when current time is 15 minutes before the leave time and hasn't been sent.
    """
    is_active, active_ts = is_journey_active_for_datetime(journey, dt)
    if not is_active:
        return None

    candidates = extract_departure_candidates(journey, dt)
    if not candidates:
        return None

    current_minutes = dt.hour * 60 + dt.minute

    for candidate in candidates:
        # If leave time has already passed, Stuart missed this departure; proceed to next
        if candidate.leave_minutes < current_minutes - tolerance_minutes:
            continue

        # Adjust for live feeds if available
        adjusted = apply_live_departure_adjustments(candidate, live_client)

        # Filter candidate against active time window constraints if present
        if active_ts:
            mode = (active_ts.mode or "depart").strip().lower()
            if mode == "arrive" and active_ts.end_time:
                end_arr = parse_time_to_minutes(active_ts.end_time)
                cand_arr = parse_time_to_minutes(adjusted.arrival_time)
                if (
                    end_arr is not None
                    and cand_arr is not None
                    and cand_arr > end_arr + 15
                ):
                    continue
            elif mode != "arrive" and active_ts.end_time:
                end_dep = parse_time_to_minutes(active_ts.end_time)
                if end_dep is not None and adjusted.leave_minutes > end_dep + 15:
                    continue

        # Check if already notified
        if adjusted.service_key in sent_keys:
            continue

        # Check if current time matches the 15-minute notification trigger window
        # (e.g. trigger_minutes - tolerance <= current_minutes <= trigger_minutes + tolerance)
        diff = abs(current_minutes - adjusted.notification_trigger_minutes)
        if diff <= tolerance_minutes:
            return adjusted

    return None


def format_departure_notification(
    candidate: DepartureCandidate,
) -> Tuple[str, str, Dict[str, Any]]:
    """Format notification title, rich message, and tap action metadata in British English."""
    title = f"Travel Alert: {candidate.journey_name}"

    walk_info = (
        f"walk {candidate.walk_minutes}m"
        if candidate.walk_minutes > 0
        else "direct departure"
    )

    mode_label = candidate.transit_mode.title()
    line_name = candidate.line_name.strip()
    if line_name:
        if mode_label.lower() in line_name.lower():
            service_desc = line_name
        else:
            service_desc = f"{mode_label} {line_name}"
    else:
        service_desc = mode_label

    plat_note = f" (Platform {candidate.platform})" if candidate.platform else ""
    live_note = ""
    if candidate.is_live and candidate.delay_minutes > 0:
        live_note = f" (delayed by {candidate.delay_minutes}m)"

    message = (
        f"Leave by {candidate.leave_time} ({walk_info}) for {service_desc}{plat_note}{live_note} "
        f"from {candidate.origin_stop_name} departing at {candidate.transit_dep_time}. "
        f"Estimated arrival at {candidate.final_dest_name} by {candidate.arrival_time}."
    )

    panel_slug = (
        Setting.get_val(
            "ingress_panel_slug",
            os.environ.get("ADDON_PANEL_PATH", ""),
        )
        or ""
    ).strip("/")
    nav_url = f"/{panel_slug}" if panel_slug else "/journey"

    data: Dict[str, Any] = {
        "url": nav_url,
        "clickAction": nav_url,
        "tag": f"journey_{candidate.journey_id}",
        "group": "travel_assistant_journeys",
    }

    return title, message, data
