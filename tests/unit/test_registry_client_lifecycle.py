"""Lifecycle tests for RegistryClient — register / heartbeat / refresh / deregister."""
from __future__ import annotations

import asyncio

import httpx
import pytest

pytestmark = pytest.mark.unit


_ENTRY_JSON = {
    "name": "ai-mcp-data", "url": "http://data-mcp:8080", "expected_url": None,
    "type": "mcp", "state": "registered", "version": "0.5.0", "metadata": {},
    "last_heartbeat_at": "2026-04-30T12:00:00Z",
    "registered_at": "2026-04-30T11:55:00Z",
    "last_changed_at": "2026-04-30T12:00:00Z",
}


async def _make_client(handler, **kw):
    from platform_sdk.registry.client import RegistryClient
    return RegistryClient(
        registry_url="http://registry:8090",
        api_key="test-key",
        transport=httpx.MockTransport(handler),
        **kw,
    )


def _record(calls):
    """Build a handler that appends each request to `calls` and returns canned responses."""
    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, req.url.path, req.content.decode() if req.content else ""))
        if req.method == "POST" and req.url.path == "/api/services":
            return httpx.Response(200, json=_ENTRY_JSON)
        if req.method == "POST" and req.url.path.endswith("/heartbeat"):
            return httpx.Response(200, json={"ok": True})
        if req.method == "DELETE":
            return httpx.Response(204)
        if req.method == "GET" and req.url.path == "/api/services":
            return httpx.Response(200, json={"services": [_ENTRY_JSON]})
        if req.method == "GET" and req.url.path.startswith("/api/services/"):
            return httpx.Response(200, json=_ENTRY_JSON)
        return httpx.Response(404)
    return handler


@pytest.mark.asyncio
async def test_register_self_posts_to_api_services():
    calls: list = []
    client = await _make_client(_record(calls))
    await client.register_self({
        "name": "ai-mcp-data",
        "url": "http://data-mcp:8080",
        "type": "mcp",
        "version": "0.5.0",
        "metadata": {"owner": "data"},
    })
    methods = [(m, p) for m, p, _ in calls]
    assert ("POST", "/api/services") in methods


@pytest.mark.asyncio
async def test_register_self_is_idempotent_on_409():
    """If the registry returns 409 (already registered with same name), treat as success."""
    def handler(req):
        if req.method == "POST" and req.url.path == "/api/services":
            return httpx.Response(409, json={"detail": "already registered"})
        return httpx.Response(404)
    client = await _make_client(handler)
    # Should not raise
    await client.register_self({
        "name": "ai-mcp-data", "url": "http://x", "type": "mcp",
    })


@pytest.mark.asyncio
async def test_deregister_sends_delete():
    calls: list = []
    client = await _make_client(_record(calls))
    await client.register_self({"name": "ai-mcp-data", "url": "http://x", "type": "mcp"})
    await client.deregister("ai-mcp-data")
    deletes = [p for m, p, _ in calls if m == "DELETE"]
    assert "/api/services/ai-mcp-data" in deletes


@pytest.mark.asyncio
async def test_heartbeat_task_runs_periodically():
    """Start heartbeat with 0.05s interval; after 0.2s expect ~3-4 calls; stop cleanly."""
    calls: list = []
    client = await _make_client(_record(calls), heartbeat_seconds=0.05)
    await client.start_heartbeat("ai-mcp-data")
    await asyncio.sleep(0.2)
    await client.stop_heartbeat()
    hb_calls = [p for m, p, _ in calls if m == "POST" and p.endswith("/heartbeat")]
    assert 2 <= len(hb_calls) <= 6  # interval 0.05s over 0.2s = ~4; allow scheduler jitter


@pytest.mark.asyncio
async def test_heartbeat_task_continues_through_transient_failures():
    state = {"fail_next": True}
    calls: list = []
    def handler(req):
        if req.method == "POST" and req.url.path.endswith("/heartbeat"):
            calls.append(req.url.path)
            if state["fail_next"]:
                state["fail_next"] = False
                return httpx.Response(503)
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)
    from platform_sdk.registry.client import RegistryClient
    client = RegistryClient(
        registry_url="http://r", api_key="k",
        transport=httpx.MockTransport(handler),
        heartbeat_seconds=0.05,
    )
    await client.start_heartbeat("ai-mcp-data")
    await asyncio.sleep(0.2)
    await client.stop_heartbeat()
    # First failed; subsequent attempts succeeded; task did not crash
    assert len(calls) >= 2


@pytest.mark.asyncio
async def test_refresh_task_repopulates_cache():
    """Pre-populate cache via lookup, then start refresh task; after one tick the cache
    should be re-fetched (we verify by counting GET /api/services calls)."""
    calls: list = []
    client = await _make_client(_record(calls), refresh_seconds=0.05)
    # Pre-warm cache
    await client.lookup("ai-mcp-data")
    await client.start_refresh()
    await asyncio.sleep(0.15)
    await client.stop_refresh()
    # Refresh task pulls /api/services (full list), so we expect at least one GET to the list endpoint
    list_gets = sum(1 for m, p, _ in calls if m == "GET" and p == "/api/services")
    assert list_gets >= 1
