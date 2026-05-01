"""Enterprise AI Platform — Application base class."""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar, Optional

if TYPE_CHECKING:
    import structlog

from ..logging import get_logger

# RegistryClient is imported at module top so test code can do
# monkeypatch.setattr("platform_sdk.base.application.RegistryClient", ...).
# Constraint: platform_sdk.registry.client must NOT import from platform_sdk.base.*
# If a future refactor introduces such an edge, the test pattern needs revisiting.
from ..registry.client import RegistryClient


class Application(ABC):
    """Root base class for all Enterprise AI applications (agents, MCP services, registry)."""

    # ---- Class-level metadata about this Application ----
    service_type: ClassVar[str] = "other"           # "agent" | "mcp" | "registry" | "other"
    service_metadata: ClassVar[dict[str, Any]] = {}
    """Service-level metadata sent to the registry on registration.

    Override by ASSIGNMENT in subclasses (``service_metadata = {"owner": "team"}``),
    not by mutation. Mutating the inherited dict would leak across siblings via the
    shared class-level default.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.config = self.load_config(name)
        self.registry: Optional[RegistryClient] = None

    @property
    def logger(self) -> "structlog.BoundLogger":
        return get_logger(self.name)

    @abstractmethod
    def load_config(self, name: str) -> Any: ...

    async def startup(self) -> None: ...
    async def shutdown(self) -> None: ...

    # ------------------------------------------------------------------
    # Self-registration with the platform registry
    # ------------------------------------------------------------------

    def _self_url(self) -> str:
        """The URL this service is reachable at. Read from SERVICE_URL env, defaults to ''."""
        return os.environ.get("SERVICE_URL", "")

    def _version(self) -> str:
        """Service version. Subclasses MAY override; default reads SERVICE_VERSION env."""
        return os.environ.get("SERVICE_VERSION", "")

    async def _register(self) -> None:
        """If REGISTRY_URL is set and this isn't the registry itself, register self
        and start heartbeat + refresh background tasks. Called by lifespan after
        telemetry but before any business init.
        """
        registry_url = os.environ.get("REGISTRY_URL")
        if not registry_url:
            self.logger.info("registry_url_not_set", behavior="self_registration_disabled")
            return

        self_url = self._self_url()
        if not self_url:
            raise RuntimeError(
                "SERVICE_URL must be set when REGISTRY_URL is set. "
                "This service cannot register without knowing its own reachable URL — "
                "a missing SERVICE_URL would silently register the wrong URL with the "
                "registry. Set SERVICE_URL=http://<host>:<port> in your service's environment."
            )

        if registry_url.rstrip("/") == self_url.rstrip("/"):
            self.logger.info("registry_self_skip", reason="REGISTRY_URL == SERVICE_URL")
            return

        api_key = os.environ.get("INTERNAL_API_KEY", "")
        self.registry = RegistryClient(registry_url=registry_url, api_key=api_key)

        await self.registry.register_self({
            "name": self.name,
            "url": self_url,
            "type": self.service_type,
            "version": self._version() or None,
            "metadata": dict(self.service_metadata),
        })
        await self.registry.start_heartbeat(self.name)
        await self.registry.start_refresh()

    async def _deregister(self) -> None:
        """Stop background tasks and DELETE /api/services/{name}. Safe if registry is None."""
        if self.registry is None:
            return
        try:
            await self.registry.stop_heartbeat()
            await self.registry.stop_refresh()
            await self.registry.deregister(self.name)
        finally:
            await self.registry.aclose()
            self.registry = None
