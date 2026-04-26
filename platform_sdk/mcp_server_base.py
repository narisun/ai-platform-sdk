"""
Platform SDK — Base MCP Server infrastructure.

Provides two approaches to eliminate MCP server boilerplate:

1. **Composition (recommended for incremental adoption)**:
   ``create_base_resources()`` — an async context manager that initialises
   OPA, cache, and optionally a DB pool.  Servers use it inside their own
   lifespan and keep their existing ServerContext / ContextVar pattern.

2. **Inheritance (for new servers)**:
   ``BaseMCPServer`` — a base class that encapsulates the full lifespan,
   context management, and FastMCP wiring.  Subclasses override
   ``register_tools()`` and optionally ``on_startup()`` / ``on_shutdown()``.

Also provides ``make_health_router()`` for FastAPI agent services.

Usage (composition — existing servers):
    from platform_sdk.mcp_server_base import create_base_resources

    @asynccontextmanager
    async def _lifespan(server):
        async with create_base_resources(
            service_name="payments-mcp",
            cache_ttl_seconds=3600,
            requires_database=True,
        ) as resources:
            ctx = ServerContext(
                opa=resources.opa, cache=resources.cache,
                db_pool=resources.db_pool, config=resources.config,
            )
            token = _ctx.set(ctx)
            yield
            _ctx.reset(token)

Usage (inheritance — new servers):
    from platform_sdk.mcp_server_base import BaseMCPServer

    class SalesforceMCPServer(BaseMCPServer):
        service_name = "salesforce-mcp"
        cache_ttl_seconds = 1800
        requires_database = True

        def register_tools(self, mcp):
            @mcp.tool()
            async def get_salesforce_summary(client_name: str) -> str:
                ctx = self.ctx  # ServerContext populated by lifespan
                ...

Usage (FastAPI agent health):
    from platform_sdk.mcp_server_base import make_health_router

    app.include_router(make_health_router({
        "agent": lambda: executor is not None,
        "mcp_bridge": bridge.is_connected,
    }))
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable, Optional

from .config import MCPConfig
from .logging import configure_logging, get_logger
from .protocols import Authorizer, CacheStore
from .security import OpaClient
from .cache import ToolResultCache
from .telemetry import setup_telemetry

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# BaseResources — the common infrastructure every MCP server needs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BaseResources:
    """Immutable container for the standard resources created by ``create_base_resources``.

    Servers can read these fields directly or copy them into their own
    ServerContext dataclass (which may include additional service-specific
    fields like ``tavily_client`` or ``tracer``).
    """
    config: MCPConfig
    opa: Authorizer
    cache: Optional[CacheStore]
    db_pool: Any  # asyncpg.Pool | None


@asynccontextmanager
async def create_base_resources(
    *,
    service_name: str = "mcp-server",
    cache_ttl_seconds: int = 300,
    requires_database: bool = True,
    db_min_size: int = 2,
    db_max_size: int = 10,
    enable_telemetry: bool = False,
    assert_secrets: bool = False,
) -> AsyncIterator[BaseResources]:
    """Create and tear down the standard MCP server resources.

    This is the **composition-first** alternative to ``BaseMCPServer``.
    Wrap it inside your existing ``_lifespan`` context manager to eliminate
    ~40 lines of duplicated OPA/cache/pool setup without changing your
    server's public interface.

    Args:
        service_name:       Passed to ``setup_telemetry`` and log messages.
        cache_ttl_seconds:  TTL for ``ToolResultCache``.  Ignored when
                            ``config.enable_tool_cache`` is False.
        requires_database:  If True, creates an ``asyncpg`` connection pool
                            using standard ``DB_*`` environment variables.
        db_min_size:        Minimum pool connections (default 2).
        db_max_size:        Maximum pool connections (default 10).
        enable_telemetry:   Call ``setup_telemetry(service_name)`` on startup.
        assert_secrets:     Call ``assert_secrets_configured()`` on startup.

    Yields:
        A frozen ``BaseResources`` dataclass.  On exit the context manager
        closes all resources in reverse order.
    """
    if enable_telemetry:
        setup_telemetry(service_name)

    if assert_secrets:
        from .auth import assert_secrets_configured
        assert_secrets_configured()

    # --- Configuration ---
    config = MCPConfig.from_env()

    # --- OPA client ---
    opa = OpaClient(config)
    log.info("opa_client_ready", service=service_name, url=config.opa_url)

    # --- Tool-result cache (graceful degradation) ---
    cache: Optional[CacheStore] = None
    if config.enable_tool_cache:
        cache = ToolResultCache.from_config(config, ttl_seconds=cache_ttl_seconds)
        log.info("tool_cache_ready", service=service_name, ttl=cache_ttl_seconds)
    else:
        log.info("tool_cache_disabled", service=service_name)

    # --- Database pool (optional) ---
    db_pool = None
    if requires_database:
        try:
            import asyncpg

            db_pool = await asyncpg.create_pool(
                host=config.db_host,
                port=config.db_port,
                user=config.db_user,
                password=config.db_pass,
                database=config.db_name,
                ssl="require" if config.db_require_ssl else None,
                min_size=db_min_size,
                max_size=db_max_size,
                statement_cache_size=config.statement_cache_size,
            )
            log.info("db_pool_ready", service=service_name, host=config.db_host, db=config.db_name)
        except ImportError:
            log.warning("db_pool_skipped", service=service_name, reason="asyncpg not installed")

    resources = BaseResources(config=config, opa=opa, cache=cache, db_pool=db_pool)
    log.info("base_resources_ready", service=service_name)

    try:
        yield resources
    finally:
        # Teardown in reverse order
        if db_pool is not None:
            await db_pool.close()
            log.info("db_pool_closed", service=service_name)
        await opa.aclose()
        if cache is not None:
            await cache.aclose()
        log.info("base_resources_shutdown", service=service_name)


# ---------------------------------------------------------------------------
# BaseMCPServer — full-inheritance approach for new servers
# ---------------------------------------------------------------------------

class BaseMCPServer:
    """
    Reusable base class that encapsulates the standard MCP server lifespan:

    - Structured logging + OpenTelemetry initialization
    - asyncpg connection pool (optional, controlled by ``requires_database``)
    - OPA client (fail-closed authorization)
    - Redis tool-result cache (graceful degradation)

    Subclasses override ``register_tools()`` to add domain-specific MCP tools,
    and optionally ``on_startup()`` / ``on_shutdown()`` for service-specific
    resources (e.g. Tavily client, AgentContext middleware).
    """

    # ── Subclass configuration (override in subclass) ────────────────────────
    service_name: str = "mcp-server"
    cache_ttl_seconds: int = 300
    requires_database: bool = True
    default_port: int = 8080
    enable_telemetry: bool = False
    assert_secrets: bool = False

    # ── Shared resources (populated during lifespan) ─────────────────────────
    _resources: Optional[BaseResources] = None

    @property
    def opa(self) -> Authorizer:
        """OPA authorizer — available after lifespan startup."""
        assert self._resources is not None, "Accessed before lifespan startup"
        return self._resources.opa

    @property
    def cache(self) -> Optional[CacheStore]:
        """Tool-result cache — may be None when cache is disabled."""
        return self._resources.cache if self._resources else None

    @property
    def db_pool(self) -> Any:
        """asyncpg connection pool — None when ``requires_database`` is False."""
        return self._resources.db_pool if self._resources else None

    @property
    def config(self) -> MCPConfig:
        """Server configuration."""
        assert self._resources is not None, "Accessed before lifespan startup"
        return self._resources.config

    async def on_startup(self, resources: BaseResources) -> None:
        """Hook for subclass-specific initialization (e.g. Tavily client, middleware).

        Called after base resources are ready, before the server starts handling
        requests.  Override in subclass; default is a no-op.
        """

    async def on_shutdown(self) -> None:
        """Hook for subclass-specific cleanup.

        Called before base resources are torn down.  Override in subclass;
        default is a no-op.
        """

    @asynccontextmanager
    async def lifespan(self, server: Any) -> AsyncIterator[None]:
        """Standard MCP server lifespan context manager."""
        configure_logging()

        async with create_base_resources(
            service_name=self.service_name,
            cache_ttl_seconds=self.cache_ttl_seconds,
            requires_database=self.requires_database,
            enable_telemetry=self.enable_telemetry,
            assert_secrets=self.assert_secrets,
        ) as resources:
            self._resources = resources
            await self.on_startup(resources)
            log.info(f"{self.service_name}_ready")

            try:
                yield
            finally:
                await self.on_shutdown()
                self._resources = None

    def register_tools(self, mcp: Any) -> None:
        """Override in subclass to register domain-specific MCP tools."""
        raise NotImplementedError("Subclasses must implement register_tools()")


# ---------------------------------------------------------------------------
# Health Router Factory (for FastAPI agent services)
# ---------------------------------------------------------------------------

def make_health_router(
    checks: Optional[dict[str, Callable[[], bool]]] = None,
    prefix: str = "",
):
    """
    Create a FastAPI router with standardized health and readiness endpoints.

    Args:
        checks: Dict of component_name → callable returning bool.
                 All checks must return True for "ready" status.
        prefix: Optional URL prefix for the routes.

    Returns:
        FastAPI APIRouter with /health and /health/ready endpoints.

    Usage:
        from platform_sdk.mcp_server_base import make_health_router

        app.include_router(make_health_router({
            "agent": lambda: executor is not None,
            "mcp_bridge": lambda: bridge.is_connected,
        }))
    """
    from fastapi import APIRouter
    from fastapi.responses import JSONResponse

    router = APIRouter(prefix=prefix)
    _checks = checks or {}

    @router.get("/health")
    async def health():
        """Liveness probe — always returns ok if the process is running."""
        return {"status": "ok"}

    @router.get("/health/ready")
    async def readiness():
        """Readiness probe — checks all registered components."""
        results = {}
        for name, check_fn in _checks.items():
            try:
                results[name] = "ok" if check_fn() else "not_ready"
            except Exception as exc:
                log.warning("readiness_check_error", check=name, error=str(exc))
                results[name] = "error"

        all_ok = all(v == "ok" for v in results.values())
        status = "ok" if all_ok else "degraded"
        return JSONResponse(
            status_code=200 if all_ok else 503,
            content={"status": status, "checks": results},
        )

    return router
