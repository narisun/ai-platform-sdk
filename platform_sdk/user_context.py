"""SDK-side UserContext Protocol — structural typing for user identity.

Defines the minimum shape the SDK needs from a user-context object.
Consumer dataclasses (e.g. analytics-agent's UserContext) structurally
satisfy this Protocol via duck typing — the SDK does not import from
any consumer package, preserving Dependency Inversion.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class UserContext(Protocol):
    """Minimum user identity shape required by SDK adapters.

    Consumers may add additional fields (user_id, tenant_id, etc.); the
    SDK only requires ``auth_token``.
    """

    auth_token: str
