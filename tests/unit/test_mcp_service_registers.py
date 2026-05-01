"""Verify McpService.lifespan calls _register / _deregister around its hooks."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_mcp_service_registers_on_startup_and_deregisters_on_shutdown(monkeypatch):
    order: list[str] = []

    class FakeRegistry:
        def __init__(self, **kw): pass
        @classmethod
        def from_config(cls, config, registry_url=None): return cls()
        async def register_self(self, p): order.append("register")
        async def start_heartbeat(self, n): order.append("hb_start")
        async def start_refresh(self): order.append("rf_start")
        async def stop_heartbeat(self): order.append("hb_stop")
        async def stop_refresh(self): order.append("rf_stop")
        async def deregister(self, n): order.append("deregister")
        async def aclose(self): order.append("aclose")

    monkeypatch.setattr("platform_sdk.base.application.RegistryClient", FakeRegistry)

    from platform_sdk.base import McpService
    from platform_sdk.config import MCPConfig

    cfg = MCPConfig(
        environment="dev",
        registry_url="http://r:8090",
        service_url="http://me:8080",
    )

    class _MyMcpService(McpService):
        service_type = "mcp"
        cache_ttl_seconds = 0
        requires_database = False
        enable_telemetry = False
        assert_secrets = False
        def register_tools(self, mcp): pass
        async def on_startup(self):
            order.append("on_startup")
        async def on_shutdown(self):
            order.append("on_shutdown")

    svc = _MyMcpService("ai-mcp-test", config=cfg)

    async with svc.lifespan(server=None):
        order.append("yield")

    # Expected sequence:
    #   register → hb_start → rf_start → on_startup → yield → on_shutdown → hb_stop → rf_stop → deregister → aclose
    assert order[0] == "register"
    assert order[1] == "hb_start"
    assert order[2] == "rf_start"
    assert "on_startup" in order
    assert "yield" in order
    assert "on_shutdown" in order
    # Teardown ends with the deregister sequence:
    assert order[-4:] == ["hb_stop", "rf_stop", "deregister", "aclose"]
