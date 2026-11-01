"""External API usage tracking, cost estimation, caching, and quota enforcement."""

import datetime
import hashlib
import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from peewee import fn

from app.models.api_usage import ApiUsageLog
from app.models.setting import Setting

logger = logging.getLogger(__name__)

# Default pricing rates in USD per external request
PRICING_PER_CALL: Dict[str, float] = {
    "google_maps:compute_transit_routes": 0.010,
    "google_maps:directions": 0.005,
    "google_maps:geocode": 0.005,
    "google_maps:reverse_geocode": 0.005,
    "google_maps:distance_matrix": 0.005,
    "darwin:fastest_departures": 0.0,
    "darwin:departure_board": 0.0,
    "darwin:arrival_board": 0.0,
    "bods:siri_vm": 0.0,
    "homeassistant:get_entity_state": 0.0,
}

DEFAULT_DAILY_LIMIT = 100
DEFAULT_MONTHLY_LIMIT = 1000
DEFAULT_CACHE_TTL_SECONDS = 900  # 15 minutes


class ApiCache:
    """Thread-safe in-memory cache with time-to-live (TTL) expiration."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: Dict[str, Tuple[float, Any]] = (
            {}
        )  # key -> (expiry_timestamp, value)
        self._hits: int = 0
        self._misses: int = 0

    def _make_key(self, provider: str, raw_key: str) -> str:
        return f"{provider}:{raw_key}"

    def get(self, provider: str, raw_key: str) -> Optional[Any]:
        """Retrieve a cached value if present and unexpired."""
        composite_key = self._make_key(provider, raw_key)
        now = time.time()
        with self._lock:
            if composite_key in self._cache:
                expiry, val = self._cache[composite_key]
                if now < expiry:
                    self._hits += 1
                    return val
                # Expired
                del self._cache[composite_key]
            self._misses += 1
            return None

    def set(
        self,
        provider: str,
        raw_key: str,
        value: Any,
        ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        """Store a value in cache with a TTL."""
        composite_key = self._make_key(provider, raw_key)
        expiry = time.time() + max(1, ttl_seconds)
        with self._lock:
            self._cache[composite_key] = (expiry, value)

    def clear(self, provider: Optional[str] = None) -> int:
        """Clear cached entries for a given provider or all providers."""
        with self._lock:
            if provider is None:
                count = len(self._cache)
                self._cache.clear()
                return count
            prefix = f"{provider}:"
            keys_to_delete = [k for k in self._cache if k.startswith(prefix)]
            for k in keys_to_delete:
                del self._cache[k]
            return len(keys_to_delete)

    def stats(self) -> Dict[str, Any]:
        """Return cache hit and size statistics."""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100.0) if total > 0 else 0.0
            return {
                "hits": self._hits,
                "misses": self._misses,
                "total_queries": total,
                "hit_rate_pct": round(hit_rate, 1),
                "active_entries": len(self._cache),
            }


# Singleton in-memory API cache instance
global_api_cache = ApiCache()


def clear_cache(provider: Optional[str] = None) -> int:
    """Clear cached entries for a given provider or all providers."""
    return global_api_cache.clear(provider=provider)


def build_cache_key(*args: Any, **kwargs: Any) -> str:
    """Generate a deterministic SHA-256 hash string for caching inputs."""
    data = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True, default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def calculate_cost(provider: str, endpoint: str) -> float:
    """Calculate estimated cost in USD for a single external API request."""
    key = f"{provider}:{endpoint}"
    return PRICING_PER_CALL.get(key, PRICING_PER_CALL.get(f"{provider}:default", 0.0))


def record_api_call(
    provider: str,
    endpoint: str,
    caller: str = "system",
    query_summary: str = "",
    status_code: int = 200,
    duration_ms: int = 0,
    is_cached: bool = False,
    error_message: Optional[str] = None,
    cost_usd: Optional[float] = None,
) -> Optional[ApiUsageLog]:
    """Persist an external API call log entry to the database."""
    estimated_cost = 0.0
    if not is_cached:
        estimated_cost = (
            cost_usd
            if cost_usd is not None
            else calculate_cost(provider=provider, endpoint=endpoint)
        )

    try:
        log_entry = ApiUsageLog.create(
            provider=provider,
            endpoint=endpoint,
            caller=caller,
            query_summary=query_summary[:500] if query_summary else "",
            status_code=status_code,
            duration_ms=max(0, duration_ms),
            is_cached=is_cached,
            estimated_cost_usd=round(estimated_cost, 4),
            error_message=str(error_message)[:500] if error_message else None,
        )
        return log_entry
    except Exception as exc:
        logger.warning("Could not persist API usage log entry: %s", exc)
        return None


def get_quota_limits(provider: str = "google_maps") -> Tuple[int, int]:
    """Retrieve daily and monthly call limits from application settings."""
    daily_limit = DEFAULT_DAILY_LIMIT
    monthly_limit = DEFAULT_MONTHLY_LIMIT
    try:
        daily_val = Setting.get_val(f"{provider}_daily_limit", DEFAULT_DAILY_LIMIT)
        monthly_val = Setting.get_val(
            f"{provider}_monthly_limit", DEFAULT_MONTHLY_LIMIT
        )
        daily_limit = int(daily_val) if daily_val is not None else DEFAULT_DAILY_LIMIT
        monthly_limit = (
            int(monthly_val) if monthly_val is not None else DEFAULT_MONTHLY_LIMIT
        )
    except Exception as exc:
        logger.debug("Failed reading quota limits from settings: %s", exc)

    return daily_limit, monthly_limit


def check_quota(provider: str = "google_maps") -> Tuple[bool, str]:
    """Verify whether external API usage remains within configured safety limits."""
    daily_limit, monthly_limit = get_quota_limits(provider)

    # 0 or negative signifies unlimited
    if daily_limit <= 0 and monthly_limit <= 0:
        return True, ""

    now = datetime.datetime.now()
    start_of_day = datetime.datetime(now.year, now.month, now.day)
    start_of_month = datetime.datetime(now.year, now.month, 1)

    try:
        if daily_limit > 0:
            today_calls = (
                ApiUsageLog.select()
                .where(
                    (ApiUsageLog.provider == provider)
                    & (ApiUsageLog.is_cached == False)  # noqa: E712
                    & (ApiUsageLog.created_at >= start_of_day)
                )
                .count()
            )
            if today_calls >= daily_limit:
                msg = (
                    f"Daily safety limit of {daily_limit} calls reached for {provider} "
                    f"({today_calls} calls recorded today)."
                )
                logger.warning(msg)
                return False, msg

        if monthly_limit > 0:
            month_calls = (
                ApiUsageLog.select()
                .where(
                    (ApiUsageLog.provider == provider)
                    & (ApiUsageLog.is_cached == False)  # noqa: E712
                    & (ApiUsageLog.created_at >= start_of_month)
                )
                .count()
            )
            if month_calls >= monthly_limit:
                msg = (
                    f"Monthly safety limit of {monthly_limit} calls reached for {provider} "
                    f"({month_calls} calls recorded this month)."
                )
                logger.warning(msg)
                return False, msg

    except Exception as exc:
        logger.warning("Error checking API quota: %s", exc)

    return True, ""


def get_usage_summary(provider: Optional[str] = "google_maps") -> Dict[str, Any]:
    """Calculate aggregated usage, estimated costs, and cache hit metrics."""
    now = datetime.datetime.now()
    start_of_day = datetime.datetime(now.year, now.month, now.day)
    start_of_month = datetime.datetime(now.year, now.month, 1)

    daily_limit, monthly_limit = get_quota_limits(provider or "google_maps")

    base_query = ApiUsageLog.select()
    if provider:
        base_query = base_query.where(ApiUsageLog.provider == provider)

    try:
        calls_today = (
            base_query.clone()
            .where(
                (ApiUsageLog.is_cached == False)  # noqa: E712
                & (ApiUsageLog.created_at >= start_of_day)
            )
            .count()
        )
        cached_today = (
            base_query.clone()
            .where(
                (ApiUsageLog.is_cached == True)  # noqa: E712
                & (ApiUsageLog.created_at >= start_of_day)
            )
            .count()
        )
        calls_month = (
            base_query.clone()
            .where(
                (ApiUsageLog.is_cached == False)  # noqa: E712
                & (ApiUsageLog.created_at >= start_of_month)
            )
            .count()
        )
        cached_month = (
            base_query.clone()
            .where(
                (ApiUsageLog.is_cached == True)  # noqa: E712
                & (ApiUsageLog.created_at >= start_of_month)
            )
            .count()
        )

        cost_today_res = (
            base_query.clone()
            .where(
                (ApiUsageLog.is_cached == False)  # noqa: E712
                & (ApiUsageLog.created_at >= start_of_day)
            )
            .select(fn.SUM(ApiUsageLog.estimated_cost_usd))
            .scalar()
        )
        cost_today = float(cost_today_res or 0.0)

        cost_month_res = (
            base_query.clone()
            .where(
                (ApiUsageLog.is_cached == False)  # noqa: E712
                & (ApiUsageLog.created_at >= start_of_month)
            )
            .select(fn.SUM(ApiUsageLog.estimated_cost_usd))
            .scalar()
        )
        cost_month = float(cost_month_res or 0.0)

        total_month = calls_month + cached_month
        cache_rate_month = (
            (cached_month / total_month * 100.0) if total_month > 0 else 0.0
        )
        # Cost saved is cached calls * typical transit call cost ($0.010)
        saved_month = cached_month * 0.010

    except Exception as exc:
        logger.warning("Error computing API usage summary: %s", exc)
        calls_today = 0
        cached_today = 0
        calls_month = 0
        cached_month = 0
        cost_today = 0.0
        cost_month = 0.0
        cache_rate_month = 0.0
        saved_month = 0.0

    cache_stats = global_api_cache.stats()

    return {
        "provider": provider or "all",
        "calls_today": calls_today,
        "cached_today": cached_today,
        "total_requests_today": calls_today + cached_today,
        "calls_month": calls_month,
        "cached_month": cached_month,
        "total_requests_month": calls_month + cached_month,
        "estimated_cost_today_usd": round(cost_today, 3),
        "estimated_cost_month_usd": round(cost_month, 3),
        "cache_savings_month_usd": round(saved_month, 3),
        "cache_hit_rate_pct": round(cache_rate_month, 1),
        "daily_limit": daily_limit,
        "monthly_limit": monthly_limit,
        "daily_quota_pct": (
            round((calls_today / daily_limit * 100.0), 1) if daily_limit > 0 else 0.0
        ),
        "monthly_quota_pct": (
            round((calls_month / monthly_limit * 100.0), 1)
            if monthly_limit > 0
            else 0.0
        ),
        "cache_in_memory_entries": cache_stats.get("active_entries", 0),
    }


def get_recent_calls(
    limit: int = 50,
    provider: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve recent external API query audit records."""
    try:
        query = ApiUsageLog.select().order_by(ApiUsageLog.created_at.desc())
        if provider:
            query = query.where(ApiUsageLog.provider == provider)
        records = list(query.limit(max(1, min(limit, 200))))
        return [r.to_dict() for r in records]
    except Exception as exc:
        logger.warning("Error fetching recent API calls: %s", exc)
        return []
