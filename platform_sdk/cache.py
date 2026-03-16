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

log = get_logger(__name__)

_KEY_PREFIX = "tool_cache:"


class ToolResultCache:
    """
    Async Redis cache for tool results.

    Gracefully degrades: when constructed with redis=None (i.e. Redis is not
    configured), get/set are no-ops so callers do not need special-case logic.
    """

    def __init__(self, redis_client, ttl_seconds: int = 300) -> None:  # type: ignore[valid-type]
        self._redis = redis_client   # redis.asyncio.Redis or None
        self._ttl   = ttl_seconds

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get(self, key: str) -> Optional[str]:
        """Return cached value or None (also None on any Redis error)."""
        if self._redis is None:
            return None
        try:
            value = await self._redis.get(key)
            if value is not None:
                log.info("cache_hit", key=key)
                return value.decode() if isinstance(value, bytes) else value
            log.debug("cache_miss", key=key)
            return None
        except Exception as exc:
            log.warning("cache_get_error", key=key, error=str(exc))
            return None

    async def set(self, key: str, value: str) -> None:
        """Store value with TTL (silently ignores any Redis error)."""
        if self._redis is None:
            return
        try:
            await self._redis.setex(key, self._ttl, value)
            log.debug("cache_set", key=key, ttl=self._ttl)
        except Exception as exc:
            log.warning("cache_set_error", key=key, error=str(exc))

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls, ttl_seconds: int = 300) -> Optional["ToolResultCache"]:
        """
        Construct a ToolResultCache from environment variables.

        Returns None when REDIS_HOST is not set so callers can treat a
        missing Redis as 'caching disabled' without branching logic.

        Environment variables:
            REDIS_HOST      — required; if absent returns None
            REDIS_PORT      — optional, default 6379
            REDIS_PASSWORD  — optional, default empty (no auth)
        """
        redis_host = os.environ.get("REDIS_HOST", "")
        if not redis_host:
            log.info("tool_cache_disabled", reason="REDIS_HOST not set")
            return None

        try:
            # Lazy import so services without redis[asyncio] installed can
            # still import the rest of this module (they just can't use cache).
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

            # Never cache error responses — they should be retried fresh
            if not result.startswith("ERROR:"):
                await cache.set(key, result)

            return result

        return wrapper
    return decorator
