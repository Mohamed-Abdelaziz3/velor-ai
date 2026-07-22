import logging
import os
import threading
import time
from urllib.parse import urlsplit

log = logging.getLogger("adam.ratelimit")

# ── Redis connection (lazy singleton) ───────────────────────
_redis_client = None
_redis_available: bool = True
_redis_last_failure_at: float = 0.0
_REDIS_CONNECTION_LOCK = threading.Lock()

# Redis is optional in the pilot runtime. Keep a bounded process-local fixed
# window so synthetic public keys (``ip:*``, ``tenant_limit:*``, visitors)
# remain enforceable during an outage.
_LOCAL_COUNTER_LOCK = threading.Lock()
_LOCAL_COUNTERS = {}
_LOCAL_COUNTER_MAX_ENTRIES = max(100, int(os.getenv("RATE_LIMIT_LOCAL_MAX_ENTRIES", "10000")))


def _safe_redis_target(redis_url: str) -> str:
    """Return a credential-free Redis target suitable for logs."""
    try:
        parsed = urlsplit(redis_url)
        scheme = parsed.scheme or "redis"
        host = parsed.hostname or "configured-host"
        port = f":{parsed.port}" if parsed.port else ""
        return f"{scheme}://{host}{port}{parsed.path or ''}"
    except Exception:
        return "redis://configured-host"


def _is_rate_limited_local(
    company_id: str,
    user_id: str,
    limit: int,
    window_seconds: int,
) -> bool:
    """Thread-safe, bounded fixed-window fallback independent of the DB."""
    safe_limit = max(1, int(limit))
    safe_window = max(1, int(window_seconds))
    now = time.monotonic()
    key = (str(company_id), str(user_id), safe_window)

    with _LOCAL_COUNTER_LOCK:
        started_at, count, _last_seen = _LOCAL_COUNTERS.get(key, (now, 0, now))
        if now - started_at >= safe_window:
            started_at, count = now, 0
        count += 1
        _LOCAL_COUNTERS[key] = (started_at, count, now)

        if len(_LOCAL_COUNTERS) > _LOCAL_COUNTER_MAX_ENTRIES:
            expired = [
                existing_key
                for existing_key, (window_start, _count, _seen) in _LOCAL_COUNTERS.items()
                if now - window_start >= existing_key[2]
            ]
            for existing_key in expired:
                _LOCAL_COUNTERS.pop(existing_key, None)
            overflow = len(_LOCAL_COUNTERS) - _LOCAL_COUNTER_MAX_ENTRIES
            if overflow > 0:
                oldest = sorted(_LOCAL_COUNTERS.items(), key=lambda item: item[1][2])[:overflow]
                for existing_key, _value in oldest:
                    _LOCAL_COUNTERS.pop(existing_key, None)

        return count > safe_limit


def _reset_local_rate_limits_for_tests() -> None:
    with _LOCAL_COUNTER_LOCK:
        _LOCAL_COUNTERS.clear()


def _redis_retry_seconds() -> float:
    raw = os.getenv("RATE_LIMIT_REDIS_RETRY_SECONDS", "30")
    try:
        return max(1.0, float(raw))
    except (TypeError, ValueError):
        return 30.0


def _mark_redis_unavailable() -> None:
    global _redis_client, _redis_available, _redis_last_failure_at
    _redis_available = False
    _redis_client = None
    _redis_last_failure_at = time.monotonic()


def _get_redis(*, force_probe: bool = False):
    global _redis_client, _redis_available, _redis_last_failure_at
    if _redis_client is not None:
        return _redis_client

    now = time.monotonic()
    if not _redis_available and not force_probe:
        # ``0`` is intentionally treated as an explicit disabled/test state.
        # Real connection failures always record a timestamp and are retried.
        if _redis_last_failure_at <= 0:
            return None
        if now - _redis_last_failure_at < _redis_retry_seconds():
            return None

    with _REDIS_CONNECTION_LOCK:
        if _redis_client is not None:
            return _redis_client
        now = time.monotonic()
        if (
            not _redis_available
            and not force_probe
            and _redis_last_failure_at > 0
            and now - _redis_last_failure_at < _redis_retry_seconds()
        ):
            return None

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        try:
            import redis

            r = redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)
            r.ping()
            _redis_client = r
            _redis_available = True
            _redis_last_failure_at = 0.0
            log.info("Redis rate-limiter connected: %s", _safe_redis_target(redis_url))
            return _redis_client
        except Exception as exc:
            log.warning(
                "Redis unavailable (%s); using bounded in-process rate limiting",
                exc.__class__.__name__,
            )
            _mark_redis_unavailable()
            return None


def get_rate_limiter_health(*, force_probe: bool = False) -> dict:
    """Return credential-free distributed limiter health.

    Development can safely use the bounded process-local fallback. Release
    environments must expose Redis as healthy because multiple workers cannot
    share an in-memory counter.
    """
    client = _get_redis(force_probe=force_probe)
    if client is not None and force_probe:
        try:
            client.ping()
        except Exception as exc:
            log.warning("Redis health probe failed (%s)", exc.__class__.__name__)
            _mark_redis_unavailable()
            client = None
    required = os.getenv("ENV", "development").strip().casefold() in {
        "verification",
        "staging",
        "production",
    }
    available = client is not None
    return {
        "redis_available": available,
        "mode": "redis" if available else "local",
        "required": required,
        "ready": available or not required,
    }


# ── Fixed-window counter via atomic Lua script ──────────────
#
# Bug in naive INCR+EXPIRE pipeline: pipe.expire() resets TTL on every call,
# so the window never expires for active users (sliding instead of fixed).
#
# Fix: Lua script sets EXPIRE only when the key is brand-new (count == 1),
# guaranteeing a true fixed-window with no TTL drift.
_INCR_WITH_EXPIRE_LUA = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""


def is_rate_limited_redis(
    company_id: str,
    user_id: str,
    limit: int = 7,
    window_seconds: int = 60,
) -> bool:
    r = _get_redis()
    if r is None:
        return _is_rate_limited_local(company_id, user_id, limit, window_seconds)
    key = f"rate:{company_id}:{user_id}"
    try:
        script = r.register_script(_INCR_WITH_EXPIRE_LUA)
        count = int(script(keys=[key], args=[window_seconds]))
        return count > limit
    except Exception as exc:
        log.warning(
            "Redis rate-limit error (%s); using bounded in-process rate limiting",
            exc.__class__.__name__,
        )
        _mark_redis_unavailable()
        return _is_rate_limited_local(company_id, user_id, limit, window_seconds)


def is_rate_limited(
    db,
    company_id: str,
    user_id: str,
    limit: int = 7,
    window_seconds: int = 60,
) -> bool:
    """
    Redis fast-path -> bounded in-process fallback.

    ``db`` remains in the signature for compatibility with existing callers;
    message-table counting is not a valid fallback for synthetic limiter keys.
    """
    return is_rate_limited_redis(company_id, user_id, limit, window_seconds)
