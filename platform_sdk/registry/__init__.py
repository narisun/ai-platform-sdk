"""Service registry — client API + shared wire models.

Server lives in narisun/ai-registry. This package provides the client used
by every Application subclass to register itself, heartbeat, and look up peers.
"""
from .exceptions import RegistryUnreachable, ServiceNotFound
from .models import (
    RegistrationRequest,
    RegistryEntry,
    ServiceState,
    ServiceType,
)

__all__ = [
    "RegistryEntry",
    "RegistrationRequest",
    "ServiceState",
    "ServiceType",
    "RegistryUnreachable",
    "ServiceNotFound",
]
