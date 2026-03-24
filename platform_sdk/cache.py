"""
Platform SDK — Tool-result caching.

Provides two reusable building blocks:

ToolResultCache
    Redis-backed cache for MCP tool results.  Gracefully degrades to a no-op
    when Redis is not configured (REDIS_HOST not set), so services work in
    environments without Redis without code changes.

cached_tool(cache)
    Decorator factory that wraps an async tool function with cache
    get/set logic.  Skips caching responses that begin with "ERROR:" so
    bad results are never served from cache.

Example — MCP server:
    from platform_sdk import MCPConfig
    from platform_sdk.cache import ToolResultCache, cached_tool

    config = MCPConfig.from_env()
    cache  = ToolResultCache.from_env(ttl_seconds=config.tool_cache_ttl_seconds)

    @mcp.tool()
    @cached_tool(cache)
    async def execute_read_query(query: str, session_id: str) -> str:
        ...

Key design decisions:
- Returns None from from_env() when REDIS_HOST is not set — callers treat None
  as "caching disabled" and the cached_tool decorator becomes a pass-through.
- Cache key = "tool_cache:" + hex(sha256(json(sorted(kwargs)))) — stable across
  argument orderings; includes the function name to avoid cross-tool collisions.
- get/set errors are swallowed so a Redis outage never breaks tool execution.
- TTL is required at construction time (not per-call) for operational simplicity.
"""
import hashlib
import json
import os
from functools import wraps
from typing import Callable, Optional

from .logging import get_logger
from .resilience import CircuitBreaker

log = get_logger(__name__)

_KEY_PREFIX = "tool_cache:"


class ToolResultCache:
    """
    Async Redis cache for tool results with circuit-breaker pattern.

    Gracefully degrades: when constructed with redis=None (i.e. Redis is not
    configured), get/set are no-ops so callers do not need special-case logic.

    Circuit breaker (via reusable CircuitBreaker): after consecutive errors,
    the cache bypasses Redis for a recovery period before probing again.
    This prevents Redis outages from adding latency to every tool call.
    """

    def __init__(self, redis_client, ttl_seconds: int = 300) -> None:  # type: ignore[valid-type]
        self._redis = redis_client   # redis.asyncio.Redis or None
        self._ttl   = ttl_seconds
        self._cb = CircuitBreaker(name="redis_cache")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get(self, key: str) -> Optional[str]:
        """Return cached value or None (also None on any Redis error)."""
        if self._redis is None or self._cb.is_open:
            return None
        try:
            value = await self._redis.get(key)
            self._cb.record_success()
            if value is not None:
                log.info("cache_hit", key=key)
                return value.decode() if isinstance(value, bytes) else value
            log.debug("cache_miss", key=key)
            return None
        except Exception as exc:
            self._cb.record_failure()
            log.warning("cache_get_error", key=key, error=str(exc))
            return None

    async def set(self, key: str, value: str) -> None:
        """Store value with TTL (silently ignores any Redis error)."""
        if self._redis is None or self._cb.is_open:
            return
        try:
            await self._redis.setex(key, self._ttl, value)
            self._cb.record_success()
            log.debug("cache_set", key=key, ttl=self._ttl)
        except Exception as exc:
            self._cb.record_failure()
            log.warning("cache_set_error", key=key, error=str(exc))

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, config: "MCPConfig", ttl_seconds: int = 300) -> Optional["ToolResultCache"]:
        """
        Construct a ToolResultCache from a centralised MCPConfig.

        Preferred over ``from_env()`` — reads Redis connection details from
        the config dataclass rather than calling ``os.environ`` directly.

        Returns None when ``config.redis_host`` is empty so callers can
        treat a missing Redis as 'caching disabled' without branching logic.
        """
        # Avoid circular import — MCPConfig is only used for type checking here.
        if not config.redis_host:
            log.info("tool_cache_disabled", reason="redis_host not set")
            return None

        try:
            import redis.asyncio as aioredis  # type: ignore[import]

            password = config.redis_password or None

            client = aioredis.Redis(
                host=config.redis_host,
                port=config.redis_port,
                password=password,
                decode_responses=False,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            log.info("tool_cache_ready", host=config.redis_host, port=config.redis_port, ttl=ttl_seconds)
            return cls(client, ttl_seconds=ttl_seconds)
        except ImportError:
            log.warning("redis_not_installed", fallback="cache_disabled")
            return None

    @classmethod
    def from_env(cls, ttl_seconds: int = 300) -> Optional["ToolResultCache"]:
        """
        Construct a ToolResultCache from environment variables.

        .. deprecated:: Prefer ``from_config(config)`` for centralised
           configuration.  This method is retained for backward compatibility.

        Returns None when REDIS_HOST is not set so callers can treat a
        missing Redis as 'caching disabled' without branching logic.
        """
        redis_host = os.environ.get("REDIS_HOST", "")
        if not redis_host:
            log.info("tool_cache_disabled", reason="REDIS_HOST not set")
            return None

        try:
            import redis.asyncio as aioredis  # type: ignore[import]

            port     = int(os.environ.get("REDIS_PORT", "6379"))
            password = os.environ.get("REDIS_PASSWORD") or None

            client = aioredis.Redis(
                host=redis_host,
                port=port,
                password=password,
                decode_responses=False,   # we decode manually to handle both bytes and str
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            log.info("tool_cache_ready", host=redis_host, port=port, ttl=ttl_seconds)
            return cls(client, ttl_seconds=ttl_seconds)

        except ImportError:
            log.warning(
                "tool_cache_disabled",
                reason="redis[asyncio] not installed — run: pip install redis[asyncio]",
            )
            return None
        except Exception as exc:
            log.warning("tool_cache_disabled", reason=str(exc))
            return None

    async def aclose(self) -> None:
        """Release the Redis connection pool."""
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass
            log.info("tool_cache_closed")


# ---------------------------------------------------------------------------
# cached_tool decorator
# ---------------------------------------------------------------------------

def make_cache_key(fn_name: str, kwargs: dict) -> str:
    """
    Derive a stable cache key from a function name and its keyword arguments.

    Uses sha256(json(sorted_kwargs)) so key is order-independent.
    """
    payload = json.dumps({"fn": fn_name, **kwargs}, sort_keys=True, default=str)
    digest  = hashlib.sha256(payload.encode()).hexdigest()
    return f"{_KEY_PREFIX}{digest}"


def cached_tool(cache: Optional[ToolResultCache]) -> Callable:
    """
    Decorator factory that adds cache get/set around an async tool function.

    When cache is None (Redis not configured) the decorator is a transparent
    pass-through — zero overhead, no branching in the wrapped function needed.

    Responses that start with "ERROR:" are never written to cache so callers
    always see fresh errors rather than a stale cached failure.

    Usage:
        cache = ToolResultCache.from_env(ttl_seconds=300)

        @mcp.tool()
        @cached_tool(cache)
        async def my_tool(query: str, session_id: str) -> str:
            ...
    """
    # Import once at decorator-creation time, not inside the per-call wrapper.
    from .authorized_tool import is_error_response

    def decorator(fn: Callable) -> Callable:
        if cache is None:
            # No-op wrapper — identical behaviour, no overhead
            return fn

        @wraps(fn)
        async def wrapper(**kwargs) -> str:
            key = make_cache_key(fn.__name__, kwargs)

            cached = await cache.get(key)
            if cached is not None:
                return cached

            result: str = await fn(**kwargs)

            # Never cache error responses — they should be retried fresh.
            # Recognises both legacy "ERROR:" prefix and new JSON {"error": ...} format.
            if not is_error_response(result):
                await cache.set(key, result)

            return result

        return wrapper
    return decorator
