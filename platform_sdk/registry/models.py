"""Pydantic models shared between the SDK client and the ai-registry server.

Both repositories import these symbols from platform_sdk.registry.models so the
wire format is type-checked at the source.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


ServiceType = Literal["agent", "mcp", "registry", "other"]
ServiceState = Literal["registered", "expected_unregistered", "stale"]


class RegistryEntry(BaseModel):
    """A single service entry as returned by the registry's GET endpoints."""

    model_config = ConfigDict(extra="forbid")

    name: str
    url: HttpUrl | None
    expected_url: HttpUrl | None
    type: ServiceType
    state: ServiceState
    version: str | None
    metadata: dict[str, Any] = Field(default_factory=dict)
    last_heartbeat_at: datetime | None
    registered_at: datetime | None
    last_changed_at: datetime

    @property
    def healthy(self) -> bool:
        """True only when the service is currently registered (heartbeats fresh)."""
        return self.state == "registered"


class RegistrationRequest(BaseModel):
    """Body of POST /api/services. Sent by services on startup."""

    model_config = ConfigDict(extra="forbid")

    name: str
    url: HttpUrl
    type: ServiceType
    version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
