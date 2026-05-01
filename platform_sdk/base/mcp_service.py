"""Enterprise AI Platform — MCP Service base class."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Optional

from .application import Application

if TYPE_CHECKING:
    from ..config import MCPConfig
    from ..protocols import Authorizer, CacheStore


class McpService(Application):
    """Base class for Enterprise AI MCP services."""

    # Subclass configuration
    cache_ttl_seconds: int = 300
    requires_database: bool = False
    assert_secrets: bool = False
    enable_telemetry: bool = False

    def __init__(
        self,
        name: str,
        *,
        config: Optional[MCPConfig] = None,
        authorizer: Optional[Authorizer] = None,
        cache: Optional[CacheStore] = None,
        db_pool: Any = None,
    ) -> None:
        """
        Initialize the MCP service.

        Args:
            name: The service name.
            config: Optional MCPConfig to inject. If not provided, will load from environment.
            authorizer: Optional Authorizer for authorization. If not provided, will be created.
            cache: Optional CacheStore for caching. If not provided, will be created if enabled.
            db_pool: Optional asyncpg database pool. If not provided, will be created if required.
        """
        self._config = config
        self._authorizer = authorizer
        self._cache = cache
        self._db_pool = db_pool
        self._owns_authorizer = False
        self._owns_cache = False
        self._owns_db_pool = False
        super().__init__(name)

    @property
    def mcp_config(self) -> MCPConfig:
        """Get the MCP configuration typed as MCPConfig."""
        return self.config

    @property
    def authorizer(self) -> Authorizer:
        """Get the authorizer instance."""
        if self._authorizer is None:
            raise RuntimeError(
                "Authorizer not available. Ensure it was injected or created during startup."
            )
        return self._authorizer

    @property
    def cache(self) -> CacheStore:
        """Get the cache store instance."""
        if self._cache is None:
            raise RuntimeError(
                "Cache not available. Ensure it was injected or created during startup."
            )
        return self._cache

    @property
    def db_pool(self) -> Any:
        """Get the database pool instance."""
        if self._db_pool is None:
            raise RuntimeError(
                "Database pool not available. Ensure it was injected or created during startup."
            )
        return self._db_pool

    def load_config(self, name: str) -> MCPConfig:
        """
        Load configuration for this MCP service.

        If config was injected via constructor, returns that.
        Otherwise loads from environment.

        Args:
            name: The service name.

        Returns:
            The loaded MCPConfig.
        """
        if self._config is not None:
            return self._config

        from ..config import MCPConfig

        return MCPConfig.from_env()

    @asynccontextmanager
    async def lifespan(self, server: Any) -> Any:
        """
        Context manager for service lifespan (startup/shutdown).

        Handles setup and teardown of telemetry, authorization, caching, and database resources.

        Args:
            server: The MCP server instance.

        Yields:
            None
        """
        # Setup telemetry
        if self.enable_telemetry:
            from ..telemetry import setup_telemetry

            setup_telemetry(self.name)

        # Assert secrets are configured
        if self.assert_secrets:
            from ..auth import assert_secrets_configured

            assert_secrets_configured()

        # Self-register with the platform registry (no-op if REGISTRY_URL unset)
        await self._register()

        # Create authorizer if not injected
        if self._authorizer is None:
            from ..security import OpaClient

            self._authorizer = OpaClient(self.mcp_config)
            self._owns_authorizer = True

        # Create cache if not injected and enabled
        if self._cache is None and self.mcp_config.enable_tool_cache:
            from ..cache import ToolResultCache

            self._cache = ToolResultCache.from_config(self.mcp_config)
            self._owns_cache = True

        # Create database pool if not injected and required
        if self._db_pool is None and self.requires_database:
            import asyncpg

            cfg = self.mcp_config
            ssl_mode = "require" if cfg.db_require_ssl else None
            self._db_pool = await asyncpg.create_pool(
                user=cfg.db_user,
                password=cfg.db_pass,
                database=cfg.db_name,
                host=cfg.db_host,
                port=cfg.db_port,
                min_size=getattr(cfg, "db_pool_min_size", 5),
                max_size=getattr(cfg, "db_pool_max_size", 20),
                statement_cache_size=cfg.statement_cache_size,
                ssl=ssl_mode,
            )
            self._owns_db_pool = True

        # Call startup hook
        await self.on_startup()

        try:
            yield
        finally:
            # Call shutdown hook
            await self.on_shutdown()

            # Deregister from the platform registry (no-op if not registered)
            await self._deregister()

            # Teardown only owned resources
            if self._owns_authorizer and self._authorizer is not None:
                if hasattr(self._authorizer, "aclose"):
                    await self._authorizer.aclose()
                elif hasattr(self._authorizer, "close"):
                    await self._authorizer.close()
                self._authorizer = None

            if self._owns_cache and self._cache is not None:
                if hasattr(self._cache, "aclose"):
                    await self._cache.aclose()
                elif hasattr(self._cache, "close"):
                    await self._cache.close()
                self._cache = None

            if self._owns_db_pool and self._db_pool is not None:
                await self._db_pool.close()
                self._db_pool = None

    async def on_startup(self) -> None:
        """
        Async startup hook. Override in subclasses if needed.
        """
        pass

    async def on_shutdown(self) -> None:
        """
        Async shutdown hook. Override in subclasses if needed.
        """
        pass

    def register_tools(self, mcp: Any) -> None:
        """
        Register MCP tools with the server.

        Subclasses must override to register their tools.

        Args:
            mcp: The MCP server instance.

        Raises:
            NotImplementedError: Always, as subclasses must implement.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement register_tools()"
        )
