"""Unit tests for RegistryClient.lookup — cache + soft-fail + circuit breaker."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx
import pytest

pytestmark = pytest.mark.unit


_ENTRY_JSON = {
    "name": "ai-mcp-data",
    "url": "http://data-mcp:8080",
    "expected_url": "http://data-mcp:8080",
    "type": "mcp",
    "state": "registered",
    "version": "0.5.0",
    "metadata": {},
    "last_heartbeat_at": "2026-04-30T12:00:00Z",
    "registered_at": "2026-04-30T11:55:00Z",
    "last_changed_at": "2026-04-30T12:00:00Z",
}


def _ok_handler(_req: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=_ENTRY_JSON)


def _503_handler(_req: httpx.Request) -> httpx.Response:
    return httpx.Response(503, json={"detail": "registry down"})


async def _make_client(handler, **kw):
    from platform_sdk.registry.client import RegistryClient
    transport = httpx.MockTransport(handler)
    return RegistryClient(
        registry_url="http://registry:8090",
        api_key="test-key",
        transport=transport,
        **kw,
    )


@pytest.mark.asyncio
async def test_lookup_returns_entry_on_success():
    client = await _make_client(_ok_handler)
    entry = await client.lookup("ai-mcp-data")
    assert entry.name == "ai-mcp-data"
    assert str(entry.url) == "http://data-mcp:8080/"


@pytest.mark.asyncio
async def test_lookup_returns_cache_when_fresh():
    calls = {"n": 0}
    def handler(req):
        calls["n"] += 1
        return _ok_handler(req)
    client = await _make_client(handler, refresh_seconds=30.0)
    a = await client.lookup("ai-mcp-data")
    b = await client.lookup("ai-mcp-data")
    assert a == b
    assert calls["n"] == 1  # second call was a cache hit


@pytest.mark.asyncio
async def test_lookup_returns_stale_cache_on_registry_outage():
    """First call succeeds and populates cache; second fails; cache still valid."""
    state = {"phase": "ok"}
    def handler(req):
        return _ok_handler(req) if state["phase"] == "ok" else _503_handler(req)
    client = await _make_client(handler, refresh_seconds=0.0)  # always treat cache as stale
    first = await client.lookup("ai-mcp-data")
    state["phase"] = "down"
    second = await client.lookup("ai-mcp-data")
    assert second == first  # served from stale cache


@pytest.mark.asyncio
async def test_lookup_raises_when_no_cache_and_registry_down():
    from platform_sdk.registry import ServiceNotFound
    client = await _make_client(_503_handler)
    with pytest.raises(ServiceNotFound):
        await client.lookup("ai-mcp-data")


@pytest.mark.asyncio
async def test_lookup_raises_when_stale_cache_too_old(monkeypatch):
    """Cache populated, then registry goes down for longer than stale_cache_max_seconds."""
    from platform_sdk.registry import ServiceNotFound
    state = {"phase": "ok", "now": 0.0}
    def handler(req):
        return _ok_handler(req) if state["phase"] == "ok" else _503_handler(req)
    monkeypatch.setattr("platform_sdk.registry.client.time.monotonic", lambda: state["now"])
    client = await _make_client(handler, refresh_seconds=0.0, stale_cache_max_seconds=10.0)
    await client.lookup("ai-mcp-data")  # populate cache
    state["phase"] = "down"
    state["now"] = 5.0
    # still within stale_cache_max → returns cached
    cached = await client.lookup("ai-mcp-data")
    assert cached.name == "ai-mcp-data"
    state["now"] = 11.0
    # now past stale_cache_max → raises
    with pytest.raises(ServiceNotFound):
        await client.lookup("ai-mcp-data")


@pytest.mark.asyncio
async def test_circuit_breaker_short_circuits_after_threshold():
    """5 sequential failures → circuit opens → next call doesn't make HTTP request."""
    calls = {"n": 0}
    def handler(req):
        calls["n"] += 1
        return _503_handler(req)
    client = await _make_client(handler)
    from platform_sdk.registry import ServiceNotFound
    for _ in range(5):
        with pytest.raises(ServiceNotFound):
            await client.lookup("ai-mcp-data")
    pre = calls["n"]
    # 6th call: circuit is open → no HTTP call
    with pytest.raises(ServiceNotFound):
        await client.lookup("ai-mcp-data")
    assert calls["n"] == pre, "circuit-open should suppress the HTTP call"
