"""Tests for Application._register / _deregister hooks."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.unit


class _StubApp:
    """Minimal subclass we can drive directly in tests, bypassing BaseAgentApp lifespan."""
    def __init__(self, name: str = "test", service_type: str = "agent"):
        from platform_sdk.base.application import Application
        _service_type = service_type
        # Patch in a concrete __init_subclass__ replacement
        class _Concrete(Application):
            service_type = _service_type  # type: ignore[assignment]
            def load_config(self, name): return None
        self.app = _Concrete(name)

    @property
    def reg(self):
        return getattr(self.app, "registry", None)


@pytest.mark.asyncio
async def test_register_skipped_when_registry_url_unset(monkeypatch):
    monkeypatch.delenv("REGISTRY_URL", raising=False)
    s = _StubApp()
    await s.app._register()
    assert s.reg is None


@pytest.mark.asyncio
async def test_register_skipped_when_self_url_matches_registry(monkeypatch):
    """The registry itself never registers with itself."""
    monkeypatch.setenv("REGISTRY_URL", "http://ai-registry:8090")
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    monkeypatch.setenv("SERVICE_URL", "http://ai-registry:8090")
    s = _StubApp(name="ai-registry")
    await s.app._register()
    assert s.reg is None


@pytest.mark.asyncio
async def test_register_creates_client_and_calls_register_self(monkeypatch):
    monkeypatch.setenv("REGISTRY_URL", "http://r:8090")
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    monkeypatch.setenv("SERVICE_URL", "http://me:8000")

    fake = AsyncMock()
    fake.register_self = AsyncMock()
    fake.start_heartbeat = AsyncMock()
    fake.start_refresh = AsyncMock()
    monkeypatch.setattr(
        "platform_sdk.base.application.RegistryClient",
        lambda **kw: fake,
    )
    s = _StubApp(name="ai-mcp-data", service_type="mcp")
    await s.app._register()
    fake.register_self.assert_awaited_once()
    payload = fake.register_self.await_args.args[0]
    assert payload["name"] == "ai-mcp-data"
    assert payload["url"] == "http://me:8000"
    assert payload["type"] == "mcp"
    fake.start_heartbeat.assert_awaited_once_with("ai-mcp-data")
    fake.start_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_deregister_calls_deregister_then_aclose(monkeypatch):
    monkeypatch.setenv("REGISTRY_URL", "http://r:8090")
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    monkeypatch.setenv("SERVICE_URL", "http://me:8000")
    fake = AsyncMock()
    fake.register_self = AsyncMock()
    fake.start_heartbeat = AsyncMock()
    fake.start_refresh = AsyncMock()
    fake.deregister = AsyncMock()
    fake.stop_heartbeat = AsyncMock()
    fake.stop_refresh = AsyncMock()
    fake.aclose = AsyncMock()
    monkeypatch.setattr("platform_sdk.base.application.RegistryClient", lambda **kw: fake)
    s = _StubApp(name="ai-mcp-data")
    await s.app._register()
    await s.app._deregister()
    fake.stop_heartbeat.assert_awaited_once()
    fake.stop_refresh.assert_awaited_once()
    fake.deregister.assert_awaited_once_with("ai-mcp-data")
    fake.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_register_raises_when_service_url_unset_but_registry_url_set(monkeypatch):
    monkeypatch.setenv("REGISTRY_URL", "http://r:8090")
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    monkeypatch.delenv("SERVICE_URL", raising=False)
    s = _StubApp()
    with pytest.raises(RuntimeError, match="SERVICE_URL must be set"):
        await s.app._register()
