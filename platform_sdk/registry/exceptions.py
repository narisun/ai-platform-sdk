"""Exceptions raised by the platform_sdk.registry client."""
from __future__ import annotations


class RegistryUnreachable(Exception):
    """Raised when the registry cannot be reached and no usable cache entry exists."""


class ServiceNotFound(Exception):
    """Raised when a service name is not in the registry (or only stale-too-old cache available)."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Service not found: {name!r}")
