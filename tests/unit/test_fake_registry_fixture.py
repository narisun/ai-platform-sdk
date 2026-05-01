"""Tests that the fake_registry pytest fixture is exposed and behaves as advertised."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_fake_registry_records_register_self(fake_registry):
    payload = {"name": "ai-mcp-data", "url": "http://x", "type": "mcp"}
    await fake_registry.register_self(payload)
    assert fake_registry.calls == [("register_self", payload)]


@pytest.mark.asyncio
async def test_fake_registry_lookup_returns_pre_seeded(fake_registry):
    from platform_sdk.registry import RegistryEntry
    from datetime import datetime, timezone
    e = RegistryEntry.model_validate({
        "name": "x", "url": "http://x", "expected_url": None,
        "type": "mcp", "state": "registered", "version": None, "metadata": {},
        "last_heartbeat_at": datetime.now(timezone.utc).isoformat(),
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "last_changed_at": datetime.now(timezone.utc).isoformat(),
    })
    fake_registry.seed("x", e)
    out = await fake_registry.lookup("x")
    assert out == e


@pytest.mark.asyncio
async def test_fake_registry_lookup_missing_raises(fake_registry):
    from platform_sdk.registry import ServiceNotFound
    with pytest.raises(ServiceNotFound):
        await fake_registry.lookup("missing")
