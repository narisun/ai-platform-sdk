"""Pytest plugin — shared fixtures for SDK consumers.

Auto-registered via [project.entry-points.pytest11] in pyproject.toml.
Any pytest run in a process where enterprise-ai-platform-sdk is installed
gets these fixtures.
"""
from __future__ import annotations

import os
import time
from typing import Callable

import pytest

from . import TEST_PERSONAS


@pytest.fixture(scope="session")
def jwt_secret() -> str:
    return os.environ.get("JWT_SECRET", "test-secret-change-in-prod")


@pytest.fixture(scope="session")
def hmac_secret() -> str:
    return os.environ.get("CONTEXT_HMAC_SECRET", "test-context-secret-change-in-prod")


@pytest.fixture(scope="session")
def internal_api_key() -> str:
    return os.environ.get("INTERNAL_API_KEY", "test-key")


def _make_jwt(payload: dict, secret: str) -> str:
    import jwt as pyjwt
    now = int(time.time())
    return pyjwt.encode(
        {"iat": now, "exp": now + 3600, **payload},
        secret,
        algorithm="HS256",
    )


def _persona_to_jwt_payload(persona: dict) -> dict:
    return {
        "sub": persona["rm_id"],
        "name": persona["rm_name"],
        "role": persona["role"],
        "team_id": persona["team_id"],
        "assigned_account_ids": persona["assigned_account_ids"],
        "compliance_clearance": persona["compliance_clearance"],
    }


@pytest.fixture(scope="session")
def make_persona_jwt(jwt_secret: str) -> Callable[[dict], str]:
    def _make(persona: dict) -> str:
        return _make_jwt(persona, jwt_secret)
    return _make


@pytest.fixture(scope="session")
def persona_manager() -> dict:
    return _persona_to_jwt_payload(TEST_PERSONAS["manager"])


@pytest.fixture(scope="session")
def persona_senior_rm() -> dict:
    return _persona_to_jwt_payload(TEST_PERSONAS["senior_rm"])


@pytest.fixture(scope="session")
def persona_rm() -> dict:
    return _persona_to_jwt_payload(TEST_PERSONAS["rm"])


@pytest.fixture(scope="session")
def persona_readonly() -> dict:
    return _persona_to_jwt_payload(TEST_PERSONAS["readonly"])


# ---- Registry fixtures ----

class _FakeRegistry:
    """In-memory fake of platform_sdk.registry.client.RegistryClient.

    Records every call in `self.calls` and serves lookups from `self._entries`.
    Use `fake_registry.seed(name, entry)` to pre-populate before lookup.
    Used by service-repo tests to verify their own registration without
    needing a real registry server.
    """

    def __init__(self) -> None:
        from platform_sdk.registry import RegistryEntry
        self._entries: dict[str, RegistryEntry] = {}
        self.calls: list = []

    def seed(self, name: str, entry) -> None:
        self._entries[name] = entry

    async def register_self(self, payload: dict) -> None:
        self.calls.append(("register_self", payload))

    async def deregister(self, name: str) -> None:
        self.calls.append(("deregister", name))

    async def start_heartbeat(self, name: str) -> None:
        self.calls.append(("start_heartbeat", name))

    async def stop_heartbeat(self) -> None:
        self.calls.append(("stop_heartbeat",))

    async def start_refresh(self) -> None:
        self.calls.append(("start_refresh",))

    async def stop_refresh(self) -> None:
        self.calls.append(("stop_refresh",))

    async def lookup(self, name: str):
        from platform_sdk.registry import ServiceNotFound
        if name not in self._entries:
            raise ServiceNotFound(name)
        return self._entries[name]

    async def aclose(self) -> None:
        self.calls.append(("aclose",))


@pytest.fixture
def fake_registry() -> _FakeRegistry:
    """In-memory fake of RegistryClient for unit/component tests."""
    return _FakeRegistry()
