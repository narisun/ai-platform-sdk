"""Tests for BaseAgentApp.mcp_dependencies (registry-driven) and the mcp_servers deprecation path."""
from __future__ import annotations

import warnings

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_mcp_dependencies_resolves_via_registry(monkeypatch):
    """When mcp_dependencies is set, _connect_bridges asks the registry by name."""
    from platform_sdk.fastapi_app import BaseAgentApp

    class _StubBridge:
        is_connected = True
        def __init__(self, url, agent_context=None):
            self.url = url
        async def connect(self, startup_timeout=30.0): pass

    monkeypatch.setattr("platform_sdk.mcp_bridge.MCPToolBridge", _StubBridge)

    looked_up: list[str] = []

    class _StubRegistry:
        async def lookup(self, name):
            looked_up.append(name)
            from platform_sdk.registry import RegistryEntry
            from datetime import datetime, timezone
            return RegistryEntry.model_validate({
                "name": name, "url": f"http://{name}:8000", "expected_url": None,
                "type": "mcp", "state": "registered", "version": None, "metadata": {},
                "last_heartbeat_at": datetime.now(timezone.utc).isoformat(),
                "registered_at": datetime.now(timezone.utc).isoformat(),
                "last_changed_at": datetime.now(timezone.utc).isoformat(),
            })

    class _RegistryDrivenApp(BaseAgentApp):
        service_name = "test"
        mcp_dependencies = ["ai-mcp-data", "ai-mcp-payments"]

        def build_dependencies(self, *, bridges, checkpointer, store): return {}
        def routes(self): return []

    app = _RegistryDrivenApp()
    app.registry = _StubRegistry()  # type: ignore[assignment]

    bridges = await app._connect_bridges(agent_ctx=None, timeout=30.0)
    assert set(looked_up) == {"ai-mcp-data", "ai-mcp-payments"}
    assert "ai-mcp-data" in bridges
    # Bridge was constructed with url + /sse path
    assert "/sse" in bridges["ai-mcp-data"].url


@pytest.mark.asyncio
async def test_mcp_dependencies_skips_unhealthy_services(monkeypatch):
    """Services with healthy=False are logged and skipped (not connected)."""
    from platform_sdk.fastapi_app import BaseAgentApp
    from datetime import datetime, timezone

    class _StubBridge:
        is_connected = True
        def __init__(self, url, agent_context=None): self.url = url
        async def connect(self, startup_timeout=30.0): pass

    monkeypatch.setattr("platform_sdk.mcp_bridge.MCPToolBridge", _StubBridge)

    class _StubRegistry:
        async def lookup(self, name):
            from platform_sdk.registry import RegistryEntry
            return RegistryEntry.model_validate({
                "name": name, "url": "http://x:8000", "expected_url": None,
                "type": "mcp",
                "state": "registered" if name == "alive" else "stale",
                "version": None, "metadata": {},
                "last_heartbeat_at": None,
                "registered_at": datetime.now(timezone.utc).isoformat(),
                "last_changed_at": datetime.now(timezone.utc).isoformat(),
            })

    class _SkipUnhealthyApp(BaseAgentApp):
        service_name = "t"
        mcp_dependencies = ["alive", "stale-one"]
        def build_dependencies(self, *, bridges, checkpointer, store): return {}
        def routes(self): return []

    app = _SkipUnhealthyApp()
    app.registry = _StubRegistry()  # type: ignore[assignment]
    bridges = await app._connect_bridges(agent_ctx=None, timeout=10.0)
    assert "alive" in bridges and "stale-one" not in bridges


def test_mcp_servers_emits_deprecation_warning():
    """Setting only mcp_servers (no mcp_dependencies) logs a DeprecationWarning."""
    from platform_sdk.fastapi_app import BaseAgentApp

    class _DeprecatedApp(BaseAgentApp):
        service_name = "deprecated"
        mcp_servers = {"x": "http://x"}
        def build_dependencies(self, *, bridges, checkpointer, store): return {}
        def routes(self): return []

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        app = _DeprecatedApp()
        app._warn_if_using_legacy_mcp_servers()
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)


def test_mcp_dependencies_takes_precedence_over_mcp_servers():
    """If both are set, mcp_dependencies wins (no warning fires)."""
    from platform_sdk.fastapi_app import BaseAgentApp

    class _BothApp(BaseAgentApp):
        service_name = "both"
        mcp_dependencies = ["x"]
        mcp_servers = {"x": "http://x"}
        def build_dependencies(self, *, bridges, checkpointer, store): return {}
        def routes(self): return []

    app = _BothApp()
    # _warn_if_using_legacy_mcp_servers should be a no-op when mcp_dependencies is non-empty
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        app._warn_if_using_legacy_mcp_servers()
    assert not any(issubclass(w.category, DeprecationWarning) for w in caught)
