"""Darwin National Rail live platform query and disruption status resolution."""

import logging
import re
from typing import Any, Dict, Optional

from app.datasources.train_live import TrainLiveClient, extract_live_services
from app.services.dispatcher.station_resolver import resolve_station_crs
from app.services.dispatcher.tracker.models import LiveRailStatus
from app.utils.transit_time import parse_time_to_minutes

logger = logging.getLogger(__name__)


def _clean_delay_reason(reason: Optional[str]) -> Optional[str]:
    """Clean and standardise National Rail Darwin delay/cancellation reason phrases."""
    if not reason:
        return None
    cleaned = reason.strip()
    cleaned = re.sub(r"<[^>]+>", "", cleaned).strip()
    cleaned = re.sub(
        r"^(?:this\s+(?:service|train)\s+has\s+been\s+(?:delayed|cancelled)\s+(?:by|due\s+to|because\s+of)\s+|(?:delayed|cancelled)\s+(?:by|due\s+to|because\s+of)\s+)",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = cleaned.rstrip(". ")
    return cleaned if cleaned else None


def _service_calls_at_dest(service: Dict[str, Any], dest_crs: Optional[str]) -> bool:
    """Verify whether a train service calls at or terminates at the destination CRS."""
    if not dest_crs:
        return True
    dest_crs_upper = dest_crs.upper()
    dest = service.get("destination")
    if isinstance(dest, list):
        for d in dest:
            if isinstance(d, dict) and d.get("crs", "").upper() == dest_crs_upper:
                return True
    elif isinstance(dest, dict):
        if dest.get("crs", "").upper() == dest_crs_upper:
            return True

    calling_points_lists = service.get("subsequentCallingPoints")
    if isinstance(calling_points_lists, list):
        for cpl in calling_points_lists:
            pts = cpl.get("callingPointList") if isinstance(cpl, dict) else cpl
            if isinstance(pts, list):
                for pt in pts:
                    if (
                        isinstance(pt, dict)
                        and pt.get("crs", "").upper() == dest_crs_upper
                    ):
                        return True
    return False


def resolve_live_rail_platform(
    origin_id: str,
    dest_id: str,
    scheduled_time: str,
    live_client: Optional[TrainLiveClient] = None,
) -> LiveRailStatus:
    """Probe Darwin Live Departure Boards for real-time platform and service status."""
    if not live_client:
        return LiveRailStatus()

    crs = resolve_station_crs(origin_id)
    if not crs:
        return LiveRailStatus()

    dest_crs = resolve_station_crs(dest_id)
    filter_list = [dest_crs] if dest_crs else None

    try:
        raw_departures = live_client.get_fastest_departures(crs, filter_list)
        services = extract_live_services(raw_departures)

        # Fallback to departure board if no services found or destination platform missing
        if not services or (dest_crs and not any(s.get("platform") for s in services)):
            try:
                board = live_client.get_departure_board(
                    crs=crs, filter_crs=dest_crs, num_rows=5
                )
                board_services = extract_live_services(board)
                if board_services:
                    services = board_services
            except Exception as board_exc:
                logger.debug(
                    "Live departure board fallback probe skipped for %s -> %s: %s",
                    crs,
                    dest_crs,
                    board_exc,
                )

        if services:
            candidate_services = (
                [s for s in services if _service_calls_at_dest(s, dest_crs)]
                if dest_crs
                else services
            )
            if not candidate_services:
                candidate_services = services

            target_dep = None
            if scheduled_time:
                sched_min = parse_time_to_minutes(scheduled_time)
                # 1. Exact match on scheduled departure time (std)
                for dep in candidate_services:
                    if dep.get("std") == scheduled_time:
                        target_dep = dep
                        break
                # 2. Tolerant match within +/- 3 minutes for minor timetable variations
                if not target_dep and sched_min is not None:
                    for dep in candidate_services:
                        std = dep.get("std")
                        std_m = parse_time_to_minutes(std) if std else None
                        if std_m is not None and abs(std_m - sched_min) <= 3:
                            target_dep = dep
                            break
                # 3. If scheduled_time is in the past or unmatched, fall back to next upcoming departure calling at destination
                if not target_dep:
                    for dep in candidate_services:
                        std = dep.get("std")
                        std_m = parse_time_to_minutes(std) if std else None
                        if std_m is not None and (
                            sched_min is None or std_m >= sched_min
                        ):
                            target_dep = dep
                            break
                    if not target_dep:
                        target_dep = candidate_services[0]
            elif candidate_services:
                target_dep = candidate_services[0]

            if target_dep:
                platform = target_dep.get("platform")
                etd = target_dep.get("etd")
                std = target_dep.get("std")
                raw_delay_reason = target_dep.get("delayReason")
                raw_cancel_reason = target_dep.get("cancelReason")
                is_cancelled = bool(target_dep.get("isCancelled"))

                delay_mins = 0
                if std and etd and etd not in ("On time", "Delayed", "Cancelled"):
                    std_m = parse_time_to_minutes(std)
                    etd_m = parse_time_to_minutes(etd)
                    if std_m is not None and etd_m is not None:
                        delay_mins = max(0, etd_m - std_m)

                cleaned_delay_reason = _clean_delay_reason(raw_delay_reason)
                cleaned_cancel_reason = _clean_delay_reason(raw_cancel_reason)

                return LiveRailStatus(
                    platform=str(platform).strip() if platform else None,
                    std=str(std).strip() if std else None,
                    etd=str(etd).strip() if etd else None,
                    delay_minutes=delay_mins,
                    delay_reason=cleaned_delay_reason,
                    is_cancelled=is_cancelled,
                    cancel_reason=cleaned_cancel_reason,
                )
    except Exception as exc:
        logger.debug("Live platform probe skipped for %s: %s", crs, exc)

    return LiveRailStatus()


def resolve_live_rail_arrival_platform(
    origin_id: str,
    dest_id: str,
    scheduled_arr_time: Optional[str] = None,
    live_client: Optional[TrainLiveClient] = None,
) -> Optional[str]:
    """Probe Darwin Live Arrival Boards for real-time arrival platform at destination station."""
    if not live_client:
        return None

    dest_crs = resolve_station_crs(dest_id)
    if not dest_crs:
        return None

    orig_crs = resolve_station_crs(origin_id)

    try:
        raw_arrivals = live_client.get_arrival_board(
            crs=dest_crs,
            filter_crs=orig_crs,
            num_rows=5,
        )
        services = extract_live_services(raw_arrivals)
        if services:
            target_svc = None
            if scheduled_arr_time:
                sched_m = parse_time_to_minutes(scheduled_arr_time)
                for svc in services:
                    if svc.get("sta") == scheduled_arr_time:
                        target_svc = svc
                        break
                if not target_svc and sched_m is not None:
                    for svc in services:
                        sta = svc.get("sta")
                        sta_m = parse_time_to_minutes(sta) if sta else None
                        if sta_m is not None and abs(sta_m - sched_m) <= 3:
                            target_svc = svc
                            break
            if not target_svc:
                target_svc = services[0]

            platform = target_svc.get("platform")
            if platform:
                return str(platform).strip()
    except Exception as exc:
        logger.debug("Live arrival platform probe skipped for %s: %s", dest_crs, exc)

    return None


__all__ = [
    "_clean_delay_reason",
    "resolve_live_rail_arrival_platform",
    "resolve_live_rail_platform",
]
