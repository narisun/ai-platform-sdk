"""Test that McpService.run_with_registration registers, runs, and deregisters."""
from __future__ import annotations

import threading
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


def test_run_with_registration_calls_register_then_run_then_deregister(monkeypatch):
    """Happy path — register before mcp.run, deregister after."""
    monkeypatch.setenv("REGISTRY_URL", "http://r:8090")
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    monkeypatch.setenv("SERVICE_URL", "http://me:8080")

    fake = AsyncMock()
    monkeypatch.setattr("platform_sdk.base.application.RegistryClient", lambda **kw: fake)

    from platform_sdk.base import McpService

    class _Svc(McpService):
        service_type = "mcp"
        cache_ttl_seconds = 0
        requires_database = False
        enable_telemetry = False
        assert_secrets = False
        def register_tools(self, mcp):
            pass

    svc = _Svc("test-mcp")

    fake_mcp = MagicMock()
    fake_mcp.run = MagicMock()

    svc.run_with_registration(fake_mcp, transport="sse")

    fake_mcp.run.assert_called_once_with(transport="sse")
    fake.register_self.assert_awaited_once()
    fake.deregister.assert_awaited_once_with("test-mcp")


def test_run_with_registration_continues_when_register_fails(monkeypatch):
    """If registry is unreachable, mcp.run still happens — logs warning, continues."""
    monkeypatch.setenv("REGISTRY_URL", "http://r:8090")
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    monkeypatch.setenv("SERVICE_URL", "http://me:8080")

    fake = AsyncMock()
    fake.register_self.side_effect = Exception("registry unreachable")
    monkeypatch.setattr("platform_sdk.base.application.RegistryClient", lambda **kw: fake)

    from platform_sdk.base import McpService

    class _Svc(McpService):
        service_type = "mcp"
        cache_ttl_seconds = 0
        requires_database = False
        enable_telemetry = False
        assert_secrets = False
        def register_tools(self, mcp):
            pass

    svc = _Svc("test-mcp")

    fake_mcp = MagicMock()
    fake_mcp.run = MagicMock()

    # Should NOT raise — registration failure is logged and execution continues.
    svc.run_with_registration(fake_mcp, transport="sse")

    fake_mcp.run.assert_called_once_with(transport="sse")
    fake.register_self.assert_awaited_once()
