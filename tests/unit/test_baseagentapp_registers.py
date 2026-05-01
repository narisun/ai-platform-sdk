"""Verify BaseAgentApp.lifespan calls _register before bridges and _deregister on teardown."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_lifespan_calls_register_before_bridges_and_deregister_on_teardown(monkeypatch):
    order: list[str] = []

    class FakeRegistry:
        def __init__(self, **kw): pass
        @classmethod
        def from_config(cls, config, registry_url=None): return cls()
        async def register_self(self, p): order.append("register")
        async def start_heartbeat(self, n): order.append("heartbeat_start")
        async def start_refresh(self): order.append("refresh_start")
        async def stop_heartbeat(self): order.append("heartbeat_stop")
        async def stop_refresh(self): order.append("refresh_stop")
        async def deregister(self, n): order.append("deregister")
        async def aclose(self): order.append("aclose")

    monkeypatch.setattr("platform_sdk.base.application.RegistryClient", FakeRegistry)

    from platform_sdk.config import AgentConfig
    from platform_sdk.fastapi_app import BaseAgentApp

    cfg = AgentConfig(
        environment="dev",
        registry_url="http://r:8090",
        service_url="http://me:8000",
    )

    class TestApp(BaseAgentApp):
        service_name = "test-agent"
        service_type = "agent"
        mcp_servers: dict = {}    # No bridges in this minimal app
        enable_telemetry = False
        requires_checkpointer = False
        requires_conversation_store = False
        def build_dependencies(self, *, bridges, checkpointer, store):
            order.append("build_deps")
            return {}
        def routes(self): return []

    app_obj = TestApp(config=cfg)
    fastapi_app = app_obj.create_app()
    async with fastapi_app.router.lifespan_context(fastapi_app):
        order.append("yield")
    # Expected order: register → heartbeat_start → refresh_start →
    # build_deps → yield → heartbeat_stop → refresh_stop → deregister → aclose
    assert order == [
        "register", "heartbeat_start", "refresh_start",
        "build_deps", "yield",
        "heartbeat_stop", "refresh_stop", "deregister", "aclose",
    ]
