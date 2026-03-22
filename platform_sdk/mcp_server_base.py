"""
Platform SDK — Base MCP Server infrastructure.

Extracts the common lifespan pattern, OPA/cache/pool initialization, and health
probes from individual MCP servers into a reusable base class.

Before (each MCP server): ~150 lines of boilerplate lifespan code.
After (each MCP server): ~20 lines of configuration + domain-specific tools.

Also provides make_health_router() for FastAPI agent services.

Usage (MCP server):
    from platform_sdk.mcp_server_base import BaseMCPServer

    class SalesforceMCPServer(BaseMCPServer):
        service_name = "salesforce-mcp"
        agent_role = "rm_prep_agent"
        cache_ttl_seconds = 1800
        requires_database = True

        def register_tools(self, mcp):
            @mcp.tool()
            async def get_salesforce_summary(client_name: str) -> str:
                ...  # Pure business logic

Usage (FastAPI agent health):
    from platform_sdk.mcp_server_base import make_health_router

    app.include_router(make_health_router({
        "agent": lambda: executor is not None,
        "mcp_bridge": bridge.is_connected,
    }))
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, Callable, Optional

from .config import MCPConfig
from .logging import configure_logging, get_logger
from .security import OpaClient
from .cache import ToolResultCache
from .telemetry import setup_telemetry

log = get_logger(__name__)


class BaseMCPServer:
    """
    Reusable base class that encapsulates the standard MCP server lifespan:
    - Structured logging + OpenTelemetry initialization
    - asyncpg connection pool (optional, controlled by requires_database)
    - OPA client (fail-closed authorization)
    - Redis tool-result cache (graceful degradation)
    - AgentContext middleware injection (for SSE transport)

    Subclasses override register_tools() to add domain-specific MCP tools.
    """

    # ── Subclass configuration (override in subclass) ────────────────────────
    service_name: str = "mcp-server"
    agent_role: str = "data_analyst_agent"
    cache_ttl_seconds: int = 300
    requires_database: bool = True
    default_port: int = 8080

    # ── Shared resources (populated during lifespan) ─────────────────────────
    opa: Optional[OpaClient] = None
    cache: Optional[ToolResultCache] = None
    db_pool: Any = None  # asyncpg.Pool or None

    @asynccontextmanager
    async def lifespan(self, server: Any):
        """Standard MCP server lifespan context manager.

        Initializes all cross-cutting infrastructure in the correct order:
        1. Logging + telemetry
        2. Database pool (if required)
        3. OPA client
        4. Redis cache
        5. AgentContext middleware

        Yields control to the MCP server, then cleans up on shutdown.
        """
        configure_logging()
        setup_telemetry(self.service_name)
        log.info(f"{self.service_name}_starting")

        config = MCPConfig.from_env()

        # Database pool (optional)
        if self.requires_database:
            try:
                import asyncpg
                db_url = os.environ.get("DATABASE_URL", "")
                if db_url:
                    self.db_pool = await asyncpg.create_pool(
                        db_url,
                        min_size=2,
                        max_size=10,
                        statement_cache_size=config.statement_cache_size,
                    )
                    log.info("db_pool_ready", min=2, max=10)
                else:
                    log.warning("db_pool_skipped", reason="DATABASE_URL not set")
            except ImportError:
                log.warning("db_pool_skipped", reason="asyncpg not installed")

        # OPA client
        self.opa = OpaClient(config)
        log.info("opa_client_ready")

        # Redis cache
        self.cache = ToolResultCache.from_env(ttl_seconds=self.cache_ttl_seconds)
        if self.cache:
            log.info("cache_ready", ttl=self.cache_ttl_seconds)

        log.info(f"{self.service_name}_ready")

        try:
            yield
        finally:
            log.info(f"{self.service_name}_stopping")
            if self.opa:
                await self.opa.aclose()
            if self.cache:
                await self.cache.aclose()
            if self.db_pool:
                await self.db_pool.close()
                log.info("db_pool_closed")
            log.info(f"{self.service_name}_stopped")

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
            except Exception:
                results[name] = "error"

        all_ok = all(v == "ok" for v in results.values())
        status = "ok" if all_ok else "degraded"
        return JSONResponse(
            status_code=200 if all_ok else 503,
            content={"status": status, "checks": results},
        )

    return router
