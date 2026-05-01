"""Base FastAPI application class for Enterprise AI agents."""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any, ClassVar, Iterable, Mapping, Optional

try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
except ImportError as exc:
    raise ImportError(
        "platform_sdk.fastapi_app requires the 'fastapi' optional extra. "
        "Install with: pip install enterprise-ai-platform-sdk[fastapi]"
    ) from exc

from ..auth import AgentContext
from ..base.application import Application
from ..config import AgentConfig
from ..logging import configure_logging, get_logger


class BaseAgentApp(Application):
    """Base class for Enterprise AI FastAPI agents.

    Subclass declares class attributes:
        service_name: str (required)
        mcp_servers: Mapping[str, str]  — logical-name -> default SSE URL
        enable_telemetry: bool = True
        requires_checkpointer: bool = False
        requires_conversation_store: bool = False

    And overrides:
        build_dependencies(*, bridges, checkpointer, store) -> Any
        routes() -> Iterable[APIRouter]

    Optional overrides:
        async on_started(deps, *, bridges, config, checkpointer, store) -> None
        async on_shutdown(deps) -> None
        service_agent_context() -> AgentContext
        build_conversation_store() -> Any
        load_config() -> Any
        register_exception_handlers(app) -> None
    """

    service_name: str = ""
    service_title: str = ""        # OpenAPI title; falls back to service_name
    service_description: str = ""  # OpenAPI description; empty by default
    mcp_servers: Mapping[str, str] = {}
    mcp_dependencies: list[str] = []   # NEW: registry-driven peer discovery.
                                       # When non-empty, replaces mcp_servers entirely.
    enable_telemetry: bool = True
    requires_checkpointer: bool = False
    requires_conversation_store: bool = False

    # Auto-load AgentConfig when no explicit config= is passed to __init__.
    config_model: ClassVar[type] = AgentConfig

    def __init__(self, *, config: Optional[AgentConfig] = None) -> None:
        if not self.service_name:
            raise ValueError(f"{type(self).__name__} must set service_name (got empty string)")
        super().__init__(self.service_name, config=config)

    # ---- Required hooks ----
    def build_dependencies(self, *, bridges: Mapping[str, Any], checkpointer: Any, store: Any) -> Any:
        raise NotImplementedError(
            f"{type(self).__name__} must implement build_dependencies()"
        )

    def routes(self) -> Iterable[Any]:
        return []

    # ---- Optional hooks ----
    async def on_started(
        self,
        deps: Any,
        *,
        bridges: Mapping[str, Any],
        config: Any,
        checkpointer: Any,
        store: Any,
    ) -> None:
        """Async hook that runs after build_dependencies(). Override for async post-init."""
        return None

    async def on_shutdown(self, deps: Any) -> None:
        return None

    def service_agent_context(self) -> AgentContext:
        """Default service identity for outbound MCP calls. Override in subclasses for elevated clearance — defaults to readonly (minimum-privilege)."""
        return AgentContext(
            rm_id=self.service_name,
            rm_name=self.service_name,
            role="readonly",
            team_id="platform",
            assigned_account_ids=(),
            compliance_clearance=("standard",),
        )

    def build_conversation_store(self) -> Any:
        return None

    # ---- Internals ----
    def _resolve_mcp_url(self, name: str, default: str) -> str:
        env_var = name.upper().replace("-", "_") + "_URL"
        return os.getenv(env_var, default)

    async def _connect_bridges(self, agent_ctx, timeout: float) -> dict:
        from ..mcp_bridge import MCPToolBridge

        log = get_logger(self.service_name)
        bridges: dict = {}

        # Path 1: registry-driven (preferred).
        if self.mcp_dependencies:
            for name in self.mcp_dependencies:
                try:
                    entry = await self.registry.lookup(name)  # type: ignore[union-attr]
                except Exception as exc:
                    log.warning("registry_lookup_failed", name=name, error=str(exc))
                    continue
                if not entry.healthy:
                    log.warning("mcp_unhealthy_skipping", name=name, state=entry.state)
                    continue
                bridge_url = str(entry.url).rstrip("/") + "/sse"
                bridges[name] = MCPToolBridge(bridge_url, agent_context=agent_ctx)
            await self._connect_all(bridges, timeout, log)
            return bridges

        # Path 2: deprecated mcp_servers dict.
        self._warn_if_using_legacy_mcp_servers()
        if not self.mcp_servers:
            return {}
        bridges = {
            name: MCPToolBridge(self._resolve_mcp_url(name, default), agent_context=agent_ctx)
            for name, default in self.mcp_servers.items()
        }
        await self._connect_all(bridges, timeout, log)
        return bridges

    async def _connect_all(self, bridges: dict, timeout: float, log) -> None:
        if not bridges:
            return
        log.info("mcp_connecting_all", servers=list(bridges.keys()), timeout=timeout)
        await asyncio.gather(
            *[b.connect(startup_timeout=timeout) for b in bridges.values()],
            return_exceptions=True,
        )
        for name, bridge in bridges.items():
            log.info("mcp_startup_status", server=name, connected=bridge.is_connected)

    def _warn_if_using_legacy_mcp_servers(self) -> None:
        import warnings
        if self.mcp_dependencies:
            return  # new path is in use; nothing to warn about
        if self.mcp_servers:
            warnings.warn(
                f"{type(self).__name__}.mcp_servers is deprecated; use "
                "mcp_dependencies (list[str]) instead. mcp_servers will be removed in 0.6.0.",
                DeprecationWarning,
                stacklevel=2,
            )

    async def _make_checkpointer(self, config: Any) -> Any:
        if not self.requires_checkpointer:
            return None
        from ..agent import setup_checkpointer
        return await setup_checkpointer(config)

    async def _make_store(self) -> Any:
        if not self.requires_conversation_store:
            return None
        store = self.build_conversation_store()
        if store is None:
            raise NotImplementedError(
                f"{type(self).__name__} declares requires_conversation_store=True "
                f"but build_conversation_store() returned None"
            )
        return store

    @asynccontextmanager
    async def lifespan(self, app: "FastAPI"):
        log = get_logger(self.service_name)
        if self.enable_telemetry:
            from ..telemetry import setup_telemetry
            setup_telemetry(self.service_name)

        await self._register()    # NEW: register self before any business init

        config = self.config
        agent_ctx = self.service_agent_context()
        timeout = getattr(config, "mcp_startup_timeout", 30.0) if config else 30.0

        bridges = await self._connect_bridges(agent_ctx, timeout)
        checkpointer = await self._make_checkpointer(config)
        store = await self._make_store()
        if store is not None and hasattr(store, "connect"):
            await store.connect()

        deps = self.build_dependencies(bridges=bridges, checkpointer=checkpointer, store=store)
        app.state.deps = deps
        app.state.bridges = bridges
        app.state.config = config

        await self.on_started(
            deps,
            bridges=bridges,
            config=config,
            checkpointer=checkpointer,
            store=store,
        )

        log.info(f"{self.service_name.replace('-', '_')}_ready")
        try:
            yield
        finally:
            await self.on_shutdown(deps)
            await self._deregister()    # NEW: deregister before tearing down telemetry
            if self.enable_telemetry:
                from ..telemetry import flush_langfuse
                flush_langfuse()
            if store is not None and hasattr(store, "disconnect"):
                await store.disconnect()
            for name, bridge in bridges.items():
                await bridge.disconnect()
                log.info("mcp_disconnected", server=name)

    def add_cors(self, app: "FastAPI") -> None:
        log = get_logger(self.service_name)
        raw_origins = os.getenv("ALLOWED_ORIGINS")
        if raw_origins and raw_origins != "*":
            origins = [o.strip() for o in raw_origins.split(",") if o.strip()]
            allow_credentials = True
        else:
            origins = ["*"]
            allow_credentials = False
            log.warning(
                "cors_wildcard_no_credentials",
                hint="set ALLOWED_ORIGINS=https://your.dashboard.example to enable credentials",
            )
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=allow_credentials,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def register_exception_handlers(self, app: "FastAPI") -> None:
        return None

    def create_app(self, deps: Optional[Any] = None) -> "FastAPI":
        configure_logging()
        app = FastAPI(
            title=self.service_title or self.service_name,
            description=self.service_description,
            version="1.0.0",
            lifespan=self.lifespan,
        )
        app.state.deps = deps
        self.add_cors(app)
        self.register_exception_handlers(app)
        for router in self.routes():
            app.include_router(router)
        return app
