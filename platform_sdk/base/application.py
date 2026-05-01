"""Enterprise AI Platform — Application base class."""
from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Any, ClassVar, Optional

if TYPE_CHECKING:
    import structlog
    from pydantic import BaseModel

from ..logging import get_logger

# RegistryClient is imported at module top so test code can do
# monkeypatch.setattr("platform_sdk.base.application.RegistryClient", ...).
from ..registry.client import RegistryClient


class Application(ABC):
    """Root base class for all Enterprise AI applications.

    Subclasses MUST set `config_model` to a Pydantic BaseModel subclass
    that defines the service's configuration shape.  The model is
    expected to expose:
      - environment: Environment Literal
      - registry_url: str
      - service_url: str
      - service_version: str
      - internal_api_key: str

    On construction, if no `config=` is passed, the SDK calls
    `cls.config_model.load()` and stores the result on `self.config`.
    """

    # ---- Class-level metadata ----
    service_type: ClassVar[str] = "other"
    service_metadata: ClassVar[dict[str, Any]] = {}

    # MUST be overridden by subclasses.
    config_model: ClassVar[Optional[type["BaseModel"]]] = None

    def __init__(self, name: str, *, config: Optional["BaseModel"] = None) -> None:
        self.name = name
        if config is not None:
            self.config = config
        else:
            if self.config_model is None:
                raise NotImplementedError(
                    f"{type(self).__name__} must set the `config_model` "
                    f"class attribute or pass an explicit `config=` to __init__."
                )
            self.config = self.config_model.load()
        # Convenience handle — every config has `environment`.
        self.environment: str = self.config.environment
        self.registry: Optional[RegistryClient] = None

    @property
    def logger(self) -> "structlog.BoundLogger":
        return get_logger(self.name)

    async def startup(self) -> None: ...
    async def shutdown(self) -> None: ...

    # ------------------------------------------------------------------
    # Self-registration
    # ------------------------------------------------------------------

    async def _register(self) -> None:
        """If `config.registry_url` is set and this isn't the registry itself,
        register self and start heartbeat + refresh background tasks.
        """
        registry_url = (self.config.registry_url or "").rstrip("/")
        if not registry_url:
            self.logger.info("registry_url_not_set", behavior="self_registration_disabled")
            return

        self_url = (self.config.service_url or "").rstrip("/")
        if not self_url:
            raise RuntimeError(
                "SERVICE_URL must be set when REGISTRY_URL is set. "
                "This service cannot register without knowing its own reachable URL — "
                "set service_url in the service's config (or via the SERVICE_URL env "
                "var that config/dev.yaml resolves)."
            )

        if registry_url == self_url:
            self.logger.info("registry_self_skip", reason="registry_url == service_url")
            return

        self.registry = RegistryClient.from_config(self.config, registry_url=registry_url)

        await self.registry.register_self({
            "name": self.name,
            "url": self.config.service_url,
            "type": self.service_type,
            "version": self.config.service_version or None,
            "metadata": dict(self.service_metadata),
        })
        await self.registry.start_heartbeat(self.name)
        await self.registry.start_refresh()

    async def _deregister(self) -> None:
        """Stop background tasks and DELETE /api/services/{name}."""
        if self.registry is None:
            return
        try:
            await self.registry.stop_heartbeat()
            await self.registry.stop_refresh()
            await self.registry.deregister(self.name)
        finally:
            await self.registry.aclose()
            self.registry = None
