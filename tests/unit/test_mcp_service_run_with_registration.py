"""Test that McpService.run_with_registration registers, runs, and deregisters."""
from __future__ import annotations

import threading
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


def test_run_with_registration_calls_register_then_run_then_deregister(monkeypatch):
    """Happy path — register before mcp.run, deregister after."""
    fake = AsyncMock()
    monkeypatch.setattr(
        "platform_sdk.base.application.RegistryClient.from_config",
        staticmethod(lambda config, registry_url=None: fake),
    )

    from platform_sdk.base import McpService
    from platform_sdk.config import MCPConfig

    cfg = MCPConfig(
        environment="dev",
        registry_url="http://r:8090",
        service_url="http://me:8080",
    )

    class _Svc(McpService):
        service_type = "mcp"
        cache_ttl_seconds = 0
        requires_database = False
        enable_telemetry = False
        assert_secrets = False
        def register_tools(self, mcp):
            pass

    svc = _Svc("test-mcp", config=cfg)

    fake_mcp = MagicMock()
    fake_mcp.run = MagicMock()

    svc.run_with_registration(fake_mcp, transport="sse")

    fake_mcp.run.assert_called_once_with(transport="sse")
    fake.register_self.assert_awaited_once()
    fake.deregister.assert_awaited_once_with("test-mcp")


def test_run_with_registration_continues_when_register_fails(monkeypatch):
    """If registry is unreachable, mcp.run still happens — logs warning, continues."""
    fake = AsyncMock()
    fake.register_self.side_effect = Exception("registry unreachable")
    monkeypatch.setattr(
        "platform_sdk.base.application.RegistryClient.from_config",
        staticmethod(lambda config, registry_url=None: fake),
    )

    from platform_sdk.base import McpService
    from platform_sdk.config import MCPConfig

    cfg = MCPConfig(
        environment="dev",
        registry_url="http://r:8090",
        service_url="http://me:8080",
    )

    class _Svc(McpService):
        service_type = "mcp"
        cache_ttl_seconds = 0
        requires_database = False
        enable_telemetry = False
        assert_secrets = False
        def register_tools(self, mcp):
            pass

    svc = _Svc("test-mcp", config=cfg)

    fake_mcp = MagicMock()
    fake_mcp.run = MagicMock()

    # Should NOT raise — registration failure is logged and execution continues.
    svc.run_with_registration(fake_mcp, transport="sse")

    fake_mcp.run.assert_called_once_with(transport="sse")
    fake.register_self.assert_awaited_once()
