# Service Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hardcoded MCP URLs in agents with a name-based service registry. Every component (agent, MCP, future runtime) registers itself with the registry on startup, heartbeats periodically, and resolves peers by name. The registry is itself an `Application` subclass — same SDK pattern as every other service.

**Architecture:** SDK 0.5.0 ships an additive `RegistryClient` and `Application` lifecycle hooks (`_register` / `_deregister`); the new `narisun/ai-registry` repo ships the server (`RegistryApp(BaseAgentApp)` + SQLite store + reaper + read-only HTML UI). Hybrid model: a YAML seed declares "expected" services for ops alerting, and runtime registrations capture what's actually running. Soft-fail with stale-cache (5 min) when the registry is unreachable. Migration is sequenced so each step is independently shippable and reversible — no big bang.

**Tech Stack:** Python 3.11, FastAPI (existing in SDK as `[fastapi]` extra), aiosqlite (new), httpx (existing), Pydantic v2 (existing), structlog (existing), pytest + pytest-asyncio (existing), Docker, GHCR.

---

## Glossary

| Item | Value |
|---|---|
| GitHub org | `narisun` |
| New repo (server) | `narisun/ai-registry` |
| New SDK package | `platform_sdk.registry` (in `narisun/ai-platform-sdk`) |
| SDK version (this milestone) | `0.5.0` (current is `0.4.0`) |
| Service container image | `ghcr.io/narisun/ai-registry:0.5.0` |
| Base image (post-bump) | `ghcr.io/narisun/ai-python-base:3.11-sdk0.5.0` |
| Registry default port (in compose) | `8090` |
| Heartbeat interval | 15 s (client) |
| Client refresh interval | 30 s |
| Stale-cache max | 300 s (5 min) — beyond this, lookup raises `ServiceNotFound` |
| Reaper grace | 60 s (registered → stale) |
| Reaper eviction | 300 s (stale → evicted or returned to `expected_unregistered`) |
| Auth model | `Authorization: Bearer ${INTERNAL_API_KEY}` for write ops; reads unauthenticated |

## Affected Repos

| Repo | What changes |
|---|---|
| `narisun/ai-platform-sdk` | New `platform_sdk/registry/` package; `Application` gains `_register` / `_deregister`; `BaseAgentApp` gains `mcp_dependencies` (deprecates `mcp_servers`); `fake_registry` pytest fixture; bump to 0.5.0 + new base image tag |
| `narisun/ai-registry` (NEW) | Whole repo: `RegistryApp`, SQLite store, reaper, routes, UI, Dockerfile, CI/release workflows |
| `narisun/ai-dev-stack` | `docker-compose.yml` adds `ai-registry` service + injects `REGISTRY_URL` into all services; bind-mounts `config/registry.yaml`; E2E workflow updated |
| `narisun/ai-agent-analytics` | Bump SDK pin to 0.5.0, base image to `3.11-sdk0.5.0`; replace `mcp_servers` dict with `mcp_dependencies` list |
| `narisun/ai-mcp-{data,salesforce,payments,news-search}` | Bump SDK pin + base image (each gets self-registration for free via `Application` base class change) |

## File Structure (post-implementation)

```
narisun/ai-platform-sdk
└── platform_sdk/
    ├── registry/                            (NEW)
    │   ├── __init__.py                      Re-exports RegistryClient, exceptions, models
    │   ├── client.py                        RegistryClient (httpx + cache + circuit breaker)
    │   ├── models.py                        RegistryEntry, RegistrationRequest (Pydantic v2)
    │   └── exceptions.py                    RegistryUnreachable, ServiceNotFound
    ├── base/
    │   └── application.py                   MODIFIED: gains _register / _deregister, service_type
    ├── fastapi_app/
    │   └── base.py                          MODIFIED: lifespan calls _register; mcp_dependencies
    ├── testing/
    │   └── plugin.py                        MODIFIED: adds fake_registry fixture
    └── __init__.py                          MODIFIED: re-exports new symbols
└── tests/unit/                              NEW test files for each module above
└── pyproject.toml                           MODIFIED: bump version to 0.5.0; add aiosqlite extra
└── CHANGELOG.md                             MODIFIED: 0.5.0 entry
└── docker/base/Dockerfile                   MODIFIED: tag becomes 3.11-sdk0.5.0

narisun/ai-registry                          (NEW REPO)
├── src/
│   ├── __init__.py
│   ├── app.py                               RegistryApp(BaseAgentApp)
│   ├── config.py                            RegistryConfig dataclass
│   ├── config_loader.py                     YAML → list[SeededEntry]
│   ├── store.py                             SqliteStore (aiosqlite); init_schema, CRUD, apply_seed
│   ├── reaper.py                            reaper_loop(store, config) async background task
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── _auth.py                         INTERNAL_API_KEY guard
│   │   ├── lookup.py                        GET /api/services, /api/services/{name}
│   │   ├── register.py                      POST /api/services, DELETE /api/services/{name}
│   │   ├── heartbeat.py                     POST /api/services/{name}/heartbeat
│   │   ├── health.py                        GET /health (registry's own)
│   │   └── ui.py                            GET / (serves index.html)
│   └── ui/
│       └── index.html                       Vanilla HTML+JS catalog
├── config/
│   └── registry.yaml                        Default seed (overridable via SEED_PATH env)
├── tests/
│   ├── conftest.py
│   ├── unit/
│   └── component/
├── Dockerfile                               FROM ghcr.io/narisun/ai-python-base:3.11-sdk0.5.0
├── pyproject.toml
├── requirements.txt                         enterprise-ai-platform-sdk[fastapi]==0.5.0 + aiosqlite + pyyaml
├── requirements-runtime.txt                 aiosqlite + pyyaml only (SDK is in base image)
├── README.md
├── CHANGELOG.md
└── .github/workflows/{ci.yml, release.yml}

narisun/ai-dev-stack
├── docker-compose.yml                       MODIFIED: ai-registry service + REGISTRY_URL injection
├── config/registry.yaml                     NEW: seed file declaring expected services
└── tests/integration/test_registry_e2e.py   NEW

narisun/ai-agent-analytics
├── src/app.py                               MODIFIED: mcp_servers → mcp_dependencies
├── requirements.txt                         MODIFIED: SDK pin → @v0.5.0
└── Dockerfile                               MODIFIED: BASE_TAG → 3.11-sdk0.5.0

narisun/ai-mcp-{data,salesforce,payments,news-search}
├── requirements.txt                         MODIFIED: SDK pin → @v0.5.0
└── Dockerfile                               MODIFIED: BASE_TAG → 3.11-sdk0.5.0
```

---

## Phase 1 — SDK 0.5.0: RegistryClient + Application hooks

All Phase 1 work happens in `narisun/ai-platform-sdk` on a feature branch `feature/registry`. After Tasks 1–8 land, merge to `main`, cut `release/0.5`, tag `v0.5.0`, and the release workflow publishes the SDK + the new base image `3.11-sdk0.5.0`.

### Task 1: Registry models + exceptions

**Files:**
- Create: `platform_sdk/registry/__init__.py`
- Create: `platform_sdk/registry/models.py`
- Create: `platform_sdk/registry/exceptions.py`
- Create: `tests/unit/test_registry_models.py`

- [ ] **Step 1.1: Write failing tests for models and exceptions**

Create `tests/unit/test_registry_models.py`:

```python
"""Unit tests for platform_sdk.registry models + exceptions."""
import pytest

pytestmark = pytest.mark.unit


def test_registry_entry_round_trip():
    from platform_sdk.registry import RegistryEntry
    payload = {
        "name": "ai-mcp-data",
        "url": "http://data-mcp:8080",
        "expected_url": "http://data-mcp:8080",
        "type": "mcp",
        "state": "registered",
        "version": "0.5.0",
        "metadata": {"owner": "data-team"},
        "last_heartbeat_at": "2026-04-30T12:00:00Z",
        "registered_at": "2026-04-30T11:55:00Z",
        "last_changed_at": "2026-04-30T12:00:00Z",
    }
    entry = RegistryEntry.model_validate(payload)
    assert entry.name == "ai-mcp-data"
    assert entry.type == "mcp"
    assert entry.state == "registered"
    # Round-trip should produce equivalent JSON
    again = RegistryEntry.model_validate(entry.model_dump(mode="json"))
    assert again == entry


def test_registry_entry_rejects_invalid_type():
    from platform_sdk.registry import RegistryEntry
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        RegistryEntry.model_validate({
            "name": "x", "type": "INVALID", "state": "registered",
            "url": None, "expected_url": None, "version": None,
            "last_heartbeat_at": None, "registered_at": None,
            "last_changed_at": "2026-04-30T12:00:00Z",
        })


def test_registry_entry_healthy_property():
    from platform_sdk.registry import RegistryEntry
    e = RegistryEntry.model_validate({
        "name": "x", "url": "http://x", "expected_url": None,
        "type": "mcp", "state": "registered", "version": None,
        "metadata": {}, "last_heartbeat_at": "2026-04-30T12:00:00Z",
        "registered_at": "2026-04-30T11:00:00Z",
        "last_changed_at": "2026-04-30T12:00:00Z",
    })
    assert e.healthy is True
    e2 = e.model_copy(update={"state": "stale"})
    assert e2.healthy is False
    e3 = e.model_copy(update={"state": "expected_unregistered"})
    assert e3.healthy is False


def test_registration_request_minimal():
    from platform_sdk.registry import RegistrationRequest
    req = RegistrationRequest.model_validate({
        "name": "ai-agent-analytics",
        "url": "http://analytics-agent:8000",
        "type": "agent",
    })
    assert req.version is None
    assert req.metadata == {}


def test_exceptions_importable():
    from platform_sdk.registry import RegistryUnreachable, ServiceNotFound
    err = RegistryUnreachable("network blew up")
    assert "blew up" in str(err)
    err2 = ServiceNotFound("ai-mcp-data")
    assert "ai-mcp-data" in str(err2)
```

- [ ] **Step 1.2: Run the test to confirm it fails**

```bash
cd /Users/admin-h26/carve-out/ai-platform-sdk
.venv/bin/pytest tests/unit/test_registry_models.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'platform_sdk.registry'`.

- [ ] **Step 1.3: Create `platform_sdk/registry/exceptions.py`**

```python
"""Exceptions raised by the platform_sdk.registry client."""
from __future__ import annotations


class RegistryUnreachable(Exception):
    """Raised when the registry cannot be reached and no usable cache entry exists."""


class ServiceNotFound(Exception):
    """Raised when a service name is not in the registry (or only stale-too-old cache available)."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Service not found: {name!r}")
```

- [ ] **Step 1.4: Create `platform_sdk/registry/models.py`**

```python
"""Pydantic models shared between the SDK client and the ai-registry server.

Both repositories import these symbols from platform_sdk.registry.models so the
wire format is type-checked at the source.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


ServiceType = Literal["agent", "mcp", "registry", "other"]
ServiceState = Literal["registered", "expected_unregistered", "stale"]


class RegistryEntry(BaseModel):
    """A single service entry as returned by the registry's GET endpoints."""

    model_config = ConfigDict(extra="forbid")

    name: str
    url: HttpUrl | None
    expected_url: HttpUrl | None
    type: ServiceType
    state: ServiceState
    version: str | None
    metadata: dict[str, Any] = Field(default_factory=dict)
    last_heartbeat_at: datetime | None
    registered_at: datetime | None
    last_changed_at: datetime

    @property
    def healthy(self) -> bool:
        """True only when the service is currently registered (heartbeats fresh)."""
        return self.state == "registered"


class RegistrationRequest(BaseModel):
    """Body of POST /api/services. Sent by services on startup."""

    model_config = ConfigDict(extra="forbid")

    name: str
    url: HttpUrl
    type: ServiceType
    version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 1.5: Create `platform_sdk/registry/__init__.py`**

```python
"""Service registry — client API + shared wire models.

Server lives in narisun/ai-registry. This package provides the client used
by every Application subclass to register itself, heartbeat, and look up peers.
"""
from .exceptions import RegistryUnreachable, ServiceNotFound
from .models import (
    RegistrationRequest,
    RegistryEntry,
    ServiceState,
    ServiceType,
)

__all__ = [
    "RegistryEntry",
    "RegistrationRequest",
    "ServiceState",
    "ServiceType",
    "RegistryUnreachable",
    "ServiceNotFound",
]
```

- [ ] **Step 1.6: Run the test to confirm it passes**

```bash
.venv/bin/pytest tests/unit/test_registry_models.py -v
```
Expected: 5 passed.

- [ ] **Step 1.7: Commit**

```bash
git checkout -b feature/registry
git add platform_sdk/registry/ tests/unit/test_registry_models.py
git commit -m "feat(registry): add Pydantic models + exceptions

RegistryEntry / RegistrationRequest are the shared wire format used by
both the SDK client and the (forthcoming) ai-registry server. Strict
extra='forbid' so unknown fields fail loudly. RegistryEntry.healthy is
sugar for state == 'registered'.

RegistryUnreachable / ServiceNotFound are the two error types the client
raises after exhausting its cache fallback path.

Refs: docs/specs/2026-04-30-service-registry-design.md"
```

---

### Task 2: RegistryClient — lookup with cache, soft-fail, circuit breaker

**Files:**
- Create: `platform_sdk/registry/client.py`
- Create: `tests/unit/test_registry_client_lookup.py`

The client owns: an httpx pool, a per-name cache, a circuit breaker, and (in Task 3) heartbeat / refresh tasks. This task focuses on `lookup()` — the read path that every consuming agent uses.

- [ ] **Step 2.1: Write failing tests for lookup behavior**

Create `tests/unit/test_registry_client_lookup.py`:

```python
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
```

- [ ] **Step 2.2: Run the test to confirm it fails**

```bash
.venv/bin/pytest tests/unit/test_registry_client_lookup.py -v
```
Expected: FAIL — `RegistryClient` not defined.

- [ ] **Step 2.3: Create `platform_sdk/registry/client.py`**

```python
"""Async client for the ai-registry service.

Owns:
  - lookup(name) -> RegistryEntry
      cache-first; refreshes on stale; soft-fails to stale cache
      on registry outages within stale_cache_max_seconds.
  - register_self(payload), deregister(), heartbeat task, refresh task
      (added in Task 3 alongside register/deregister and the background tasks)

The client is owned by Application._register() — every agent and MCP gets one
on startup automatically. Service code never instantiates this directly.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import httpx

from ..logging import get_logger
from ..resilience import CircuitBreaker
from .exceptions import RegistryUnreachable, ServiceNotFound
from .models import RegistryEntry

log = get_logger(__name__)


@dataclass
class _CacheEntry:
    entry: RegistryEntry
    fetched_at: float

    def fresh(self, refresh_seconds: float) -> bool:
        return (time.monotonic() - self.fetched_at) < refresh_seconds

    def age(self) -> float:
        return time.monotonic() - self.fetched_at


class RegistryClient:
    def __init__(
        self,
        *,
        registry_url: str,
        api_key: str,
        heartbeat_seconds: float = 15.0,
        refresh_seconds: float = 30.0,
        stale_cache_max_seconds: float = 300.0,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self._url = registry_url.rstrip("/")
        self._api_key = api_key
        self._heartbeat_seconds = heartbeat_seconds
        self._refresh_seconds = refresh_seconds
        self._stale_cache_max_seconds = stale_cache_max_seconds
        self._cache: dict[str, _CacheEntry] = {}
        self._client = httpx.AsyncClient(
            base_url=self._url,
            timeout=httpx.Timeout(connect=1.0, read=5.0),
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
        )
        self._cb = CircuitBreaker(
            name="registry",
            failure_threshold=5,
            recovery_timeout=30.0,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def lookup(self, name: str) -> RegistryEntry:
        cached = self._cache.get(name)
        if cached and cached.fresh(self._refresh_seconds):
            return cached.entry

        if self._cb.is_open:
            log.warning("registry_circuit_open", name=name)
            return self._stale_or_raise(name, cached)

        try:
            entry = await self._fetch(name)
        except (RegistryUnreachable, httpx.HTTPError) as exc:
            log.warning("registry_unreachable", name=name, error=str(exc))
            self._cb.record_failure()
            return self._stale_or_raise(name, cached)

        self._cb.record_success()
        self._cache[name] = _CacheEntry(entry=entry, fetched_at=time.monotonic())
        return entry

    def _stale_or_raise(self, name: str, cached: Optional[_CacheEntry]) -> RegistryEntry:
        if cached is not None and cached.age() < self._stale_cache_max_seconds:
            log.warning("registry_unreachable_using_stale", name=name, age=cached.age())
            return cached.entry
        raise ServiceNotFound(name)

    async def _fetch(self, name: str) -> RegistryEntry:
        try:
            r = await self._client.get(f"/api/services/{name}")
        except httpx.RequestError as exc:
            raise RegistryUnreachable(str(exc)) from exc
        if r.status_code == 404:
            raise ServiceNotFound(name)
        if r.status_code >= 500:
            raise RegistryUnreachable(f"registry {r.status_code}")
        r.raise_for_status()
        return RegistryEntry.model_validate(r.json())
```

- [ ] **Step 2.4: Run the tests to confirm they pass**

```bash
.venv/bin/pytest tests/unit/test_registry_client_lookup.py -v
```
Expected: 6 passed.

- [ ] **Step 2.5: Commit**

```bash
git add platform_sdk/registry/client.py tests/unit/test_registry_client_lookup.py
git commit -m "feat(registry): RegistryClient.lookup with cache + soft-fail + circuit breaker

lookup(name) returns a fresh cached entry within refresh_seconds; on miss it
hits GET /api/services/{name}. When the registry is unreachable, it falls
back to the cached entry as long as it is younger than stale_cache_max_seconds
(default 5min). After 5 consecutive failures the CircuitBreaker opens and
short-circuits subsequent calls, also returning stale cache or raising
ServiceNotFound.

Tests use httpx.MockTransport; no network."
```

---

### Task 3: RegistryClient — register / heartbeat / refresh / deregister

**Files:**
- Modify: `platform_sdk/registry/client.py` (extend the class)
- Create: `tests/unit/test_registry_client_lifecycle.py`

- [ ] **Step 3.1: Write failing tests for register / heartbeat / refresh / deregister**

Create `tests/unit/test_registry_client_lifecycle.py`:

```python
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
    """Build a handler that appends each request to `calls` and returns a 200 with given JSON."""
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
    initial_get_singles = sum(1 for m, p, _ in calls if m == "GET" and p.startswith("/api/services/"))
    await client.start_refresh()
    await asyncio.sleep(0.15)
    await client.stop_refresh()
    # Refresh task pulls /api/services (full list), so we expect at least one GET to the list endpoint
    list_gets = sum(1 for m, p, _ in calls if m == "GET" and p == "/api/services")
    assert list_gets >= 1
```

- [ ] **Step 3.2: Run the test to confirm it fails**

```bash
.venv/bin/pytest tests/unit/test_registry_client_lifecycle.py -v
```
Expected: FAIL — methods don't exist yet.

- [ ] **Step 3.3: Extend `platform_sdk/registry/client.py`**

Add these methods inside the `RegistryClient` class (alongside the existing `lookup` / `_fetch`):

```python
    # ------------------------------------------------------------------
    # Registration / deregistration
    # ------------------------------------------------------------------

    async def register_self(self, payload: dict) -> None:
        """POST /api/services with a RegistrationRequest. 409 is idempotent."""
        try:
            r = await self._client.post("/api/services", json=payload)
        except httpx.RequestError as exc:
            raise RegistryUnreachable(str(exc)) from exc
        if r.status_code == 409:
            log.info("registration_idempotent", name=payload["name"])
            return
        r.raise_for_status()
        log.info("registration", name=payload["name"], url=payload["url"], type=payload["type"])
        self._registered_name = payload["name"]

    async def deregister(self, name: str) -> None:
        """DELETE /api/services/{name}. Logs but does not raise on failure."""
        try:
            await self._client.delete(f"/api/services/{name}")
            log.info("deregistration", name=name)
        except httpx.HTTPError as exc:
            log.warning("deregistration_failed", name=name, error=str(exc))

    # ------------------------------------------------------------------
    # Heartbeat task
    # ------------------------------------------------------------------

    async def start_heartbeat(self, name: str) -> None:
        if getattr(self, "_heartbeat_task", None) is not None:
            return
        self._heartbeat_name = name

        async def _loop() -> None:
            while True:
                try:
                    r = await self._client.post(f"/api/services/{name}/heartbeat")
                    if r.status_code != 200:
                        log.warning("heartbeat_non_200", name=name, status=r.status_code)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.warning("heartbeat_failed", name=name, error=str(exc))
                await asyncio.sleep(self._heartbeat_seconds)

        self._heartbeat_task = asyncio.create_task(_loop())

    async def stop_heartbeat(self) -> None:
        task = getattr(self, "_heartbeat_task", None)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self._heartbeat_task = None

    # ------------------------------------------------------------------
    # Refresh task — repopulate full cache periodically
    # ------------------------------------------------------------------

    async def start_refresh(self) -> None:
        if getattr(self, "_refresh_task", None) is not None:
            return

        async def _loop() -> None:
            while True:
                await asyncio.sleep(self._refresh_seconds)
                try:
                    r = await self._client.get("/api/services")
                    if r.status_code == 200:
                        body = r.json()
                        services = body.get("services", body) if isinstance(body, dict) else body
                        for raw in services:
                            entry = RegistryEntry.model_validate(raw)
                            self._cache[entry.name] = _CacheEntry(
                                entry=entry, fetched_at=time.monotonic()
                            )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.warning("refresh_failed", error=str(exc))

        self._refresh_task = asyncio.create_task(_loop())

    async def stop_refresh(self) -> None:
        task = getattr(self, "_refresh_task", None)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self._refresh_task = None
```

Add to the top of the file (next to existing imports):

```python
import asyncio
```

- [ ] **Step 3.4: Run the lifecycle tests to confirm they pass**

```bash
.venv/bin/pytest tests/unit/test_registry_client_lifecycle.py -v
```
Expected: 6 passed.

- [ ] **Step 3.5: Run the full unit suite to confirm no regressions**

```bash
.venv/bin/pytest tests/unit -m unit -q
```
Expected: prior count + 11 new (5 from Task 1 models + 6 from Task 2 lookup + 6 from Task 3 — wait, 5+6+6=17, but the model file has 5 tests + lookup 6 + lifecycle 6 = 17 new tests). Confirm no failures.

- [ ] **Step 3.6: Commit**

```bash
git add platform_sdk/registry/client.py tests/unit/test_registry_client_lifecycle.py
git commit -m "feat(registry): RegistryClient lifecycle — register / heartbeat / refresh / deregister

register_self() POSTs /api/services and is idempotent on 409.
start_heartbeat(name) launches a background task POSTing /heartbeat every
heartbeat_seconds; transient failures are logged but do not crash the task.
start_refresh() pulls GET /api/services every refresh_seconds and refreshes
the entire client cache. deregister(name) sends DELETE /api/services/{name}
on graceful shutdown; failures are logged but never raise (we are tearing down).

All four lifecycle methods can be started/stopped independently and are safe
to call from BaseAgentApp.lifespan."
```

---

### Task 4: `Application` gains `_register` / `_deregister` hooks

**Files:**
- Modify: `platform_sdk/base/application.py`
- Create: `tests/unit/test_application_register.py`

The `Application` base class is where every agent and MCP server inherits from. Adding registration hooks here means service code does not have to know about the registry — extending `BaseAgentApp` or `McpService` is enough.

- [ ] **Step 4.1: Write failing tests for `_register` / `_deregister`**

Create `tests/unit/test_application_register.py`:

```python
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
        # Patch in a concrete __init_subclass__ replacement
        class _Concrete(Application):
            service_type = service_type  # type: ignore[assignment]
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
```

- [ ] **Step 4.2: Run the test to confirm it fails**

```bash
.venv/bin/pytest tests/unit/test_application_register.py -v
```
Expected: FAIL — `_register` / `_deregister` methods do not exist.

- [ ] **Step 4.3: Modify `platform_sdk/base/application.py`**

Replace the file with:

```python
"""Enterprise AI Platform — Application base class."""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar, Optional

if TYPE_CHECKING:
    import structlog
    from ..registry.client import RegistryClient

from ..logging import get_logger


class Application(ABC):
    """Root base class for all Enterprise AI applications (agents, MCP services, registry)."""

    # ---- Class-level metadata about this Application ----
    service_type: ClassVar[str] = "other"           # "agent" | "mcp" | "registry" | "other"
    service_metadata: ClassVar[dict[str, Any]] = {}

    def __init__(self, name: str) -> None:
        self.name = name
        self.config = self.load_config(name)
        self.registry: Optional["RegistryClient"] = None

    @property
    def logger(self) -> "structlog.BoundLogger":
        return get_logger(self.name)

    @abstractmethod
    def load_config(self, name: str) -> Any: ...

    async def startup(self) -> None: ...
    async def shutdown(self) -> None: ...

    # ------------------------------------------------------------------
    # Self-registration with the platform registry
    # ------------------------------------------------------------------

    def _self_url(self) -> str:
        """The URL this service is reachable at. Read from SERVICE_URL env, defaults to ''."""
        return os.environ.get("SERVICE_URL", "")

    def _version(self) -> str:
        """Service version. Subclasses MAY override; default reads SERVICE_VERSION env."""
        return os.environ.get("SERVICE_VERSION", "")

    async def _register(self) -> None:
        """If REGISTRY_URL is set and this isn't the registry itself, register self
        and start heartbeat + refresh background tasks. Called by lifespan after
        telemetry but before any business init.
        """
        registry_url = os.environ.get("REGISTRY_URL")
        if not registry_url:
            self.logger.info("registry_url_not_set", behavior="self_registration_disabled")
            return

        self_url = self._self_url()
        if self_url and registry_url.rstrip("/") == self_url.rstrip("/"):
            self.logger.info("registry_self_skip", reason="REGISTRY_URL == SERVICE_URL")
            return

        from ..registry.client import RegistryClient

        api_key = os.environ.get("INTERNAL_API_KEY", "")
        self.registry = RegistryClient(registry_url=registry_url, api_key=api_key)

        await self.registry.register_self({
            "name": self.name,
            "url": self_url or registry_url,  # SERVICE_URL is required for real services;
                                              # fallback prevents pydantic from rejecting an empty
            "type": self.service_type,
            "version": self._version() or None,
            "metadata": dict(self.service_metadata),
        })
        await self.registry.start_heartbeat(self.name)
        await self.registry.start_refresh()

    async def _deregister(self) -> None:
        """Stop background tasks and DELETE /api/services/{name}. Safe if registry is None."""
        if self.registry is None:
            return
        try:
            await self.registry.stop_heartbeat()
            await self.registry.stop_refresh()
            await self.registry.deregister(self.name)
        finally:
            await self.registry.aclose()
            self.registry = None
```

- [ ] **Step 4.4: Run tests to confirm they pass**

```bash
.venv/bin/pytest tests/unit/test_application_register.py -v
```
Expected: 4 passed.

- [ ] **Step 4.5: Run full unit suite — no regressions**

```bash
.venv/bin/pytest tests/unit -m unit -q
```
Expected: still green.

- [ ] **Step 4.6: Commit**

```bash
git add platform_sdk/base/application.py tests/unit/test_application_register.py
git commit -m "feat(registry): Application gains _register / _deregister hooks

Every Application subclass (Agent, McpService, RegistryApp itself, future
runtimes) now self-registers when REGISTRY_URL is set. The registry skips
self-registration when its own URL matches REGISTRY_URL (the registry IS
the registry). _register / _deregister are no-ops when REGISTRY_URL is
unset, preserving the existing behavior for any future caller that does
not want registry integration.

service_type and service_metadata become ClassVar attrs that subclasses
override (e.g., RegistryApp sets service_type='registry').

Wiring into BaseAgentApp.lifespan and McpService.lifespan lands in the
next two tasks."
```

---

### Task 5: Wire `_register` / `_deregister` into `BaseAgentApp.lifespan`

**Files:**
- Modify: `platform_sdk/fastapi_app/base.py`
- Create: `tests/unit/test_baseagentapp_registers.py`

- [ ] **Step 5.1: Write failing test for lifespan ordering**

Create `tests/unit/test_baseagentapp_registers.py`:

```python
"""Verify BaseAgentApp.lifespan calls _register before bridges and _deregister on teardown."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_lifespan_calls_register_before_bridges_and_deregister_on_teardown(monkeypatch):
    monkeypatch.setenv("REGISTRY_URL", "http://r:8090")
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    monkeypatch.setenv("SERVICE_URL", "http://me:8000")
    order: list[str] = []

    class FakeRegistry:
        def __init__(self, **kw): pass
        async def register_self(self, p): order.append("register")
        async def start_heartbeat(self, n): order.append("heartbeat_start")
        async def start_refresh(self): order.append("refresh_start")
        async def stop_heartbeat(self): order.append("heartbeat_stop")
        async def stop_refresh(self): order.append("refresh_stop")
        async def deregister(self, n): order.append("deregister")
        async def aclose(self): order.append("aclose")

    monkeypatch.setattr("platform_sdk.base.application.RegistryClient", FakeRegistry)

    from platform_sdk.fastapi_app import BaseAgentApp

    class TestApp(BaseAgentApp):
        service_name = "test-agent"
        service_type = "agent"
        mcp_dependencies: list[str] = []
        enable_telemetry = False
        requires_checkpointer = False
        requires_conversation_store = False
        def build_dependencies(self, *, bridges, checkpointer, store):
            order.append("build_deps")
            return {}
        def routes(self): return []

    app_obj = TestApp()
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
```

- [ ] **Step 5.2: Run the test to confirm it fails**

```bash
.venv/bin/pytest tests/unit/test_baseagentapp_registers.py -v
```
Expected: FAIL — `Application._register` is not called by `BaseAgentApp.lifespan` yet.

- [ ] **Step 5.3: Modify `platform_sdk/fastapi_app/base.py`**

Locate the `lifespan` method. Inject `await self._register()` after `setup_telemetry` and before bridge connection, and `await self._deregister()` in the `finally` block.

Find this section (around line 137-179):

```python
    @asynccontextmanager
    async def lifespan(self, app: "FastAPI"):
        log = get_logger(self.service_name)
        if self.enable_telemetry:
            from ..telemetry import setup_telemetry
            setup_telemetry(self.service_name)

        config = self.load_config()
        agent_ctx = self.service_agent_context()
        timeout = getattr(config, "mcp_startup_timeout", 30.0) if config else 30.0

        bridges = await self._connect_bridges(agent_ctx, timeout)
```

Insert `await self._register()` between `setup_telemetry(...)` and `config = self.load_config()`. This is critical: registration runs early so the agent self-announces before doing any heavy startup work.

Also locate the `finally:` block at the end of the lifespan and add `await self._deregister()` after `on_shutdown` and before `flush_langfuse`.

The patched section becomes:

```python
    @asynccontextmanager
    async def lifespan(self, app: "FastAPI"):
        log = get_logger(self.service_name)
        if self.enable_telemetry:
            from ..telemetry import setup_telemetry
            setup_telemetry(self.service_name)

        await self._register()    # <-- NEW

        config = self.load_config()
        agent_ctx = self.service_agent_context()
        timeout = getattr(config, "mcp_startup_timeout", 30.0) if config else 30.0

        bridges = await self._connect_bridges(agent_ctx, timeout)
        # ... unchanged through the yield ...
        try:
            yield
        finally:
            await self.on_shutdown(deps)
            await self._deregister()    # <-- NEW (before flush_langfuse so the registry sees the
                                        # deregistration before traces are torn down)
            if self.enable_telemetry:
                from ..telemetry import flush_langfuse
                flush_langfuse()
            if store is not None and hasattr(store, "disconnect"):
                await store.disconnect()
            for name, bridge in bridges.items():
                await bridge.disconnect()
                log.info("mcp_disconnected", server=name)
```

`BaseAgentApp` does not directly inherit from `Application` today. Add an explicit base by making `BaseAgentApp` extend `Application` so `_register` / `_deregister` are available:

Find the class declaration:
```python
class BaseAgentApp:
```

Replace with:
```python
from ..base.application import Application

class BaseAgentApp(Application):
```

Then update `__init__` so `Application.__init__` runs (it sets `self.name`, `self.config`, `self.registry = None`):

Add an `__init__` to `BaseAgentApp`:

```python
    def __init__(self) -> None:
        if not self.service_name:
            raise ValueError(f"{type(self).__name__} must set service_name (got empty string)")
        super().__init__(self.service_name)
```

`Application.load_config(name)` is abstract; `BaseAgentApp` already has `load_config(self) -> Any` (no `name` arg). Update `Application.load_config(name)` to be a no-arg method, OR adapt `BaseAgentApp.load_config` signature. **Pick the second** — keep `Application.load_config(name)` but have `BaseAgentApp.load_config` accept the name and ignore it:

```python
    def load_config(self, name: str | None = None) -> Any:    # match Application signature
        from ..config import AgentConfig
        return AgentConfig.from_env()
```

(The `name` parameter is the application name; `BaseAgentApp` does not currently use it but accepts it for protocol compatibility.)

- [ ] **Step 5.4: Run the test to confirm it passes**

```bash
.venv/bin/pytest tests/unit/test_baseagentapp_registers.py -v
```
Expected: 1 passed.

- [ ] **Step 5.5: Run full BaseAgentApp test suite — no regressions**

```bash
.venv/bin/pytest tests/unit/test_fastapi_app_base.py -v
```
Expected: same count as before (9 passed) — adding `_register` should not break any existing tests because they don't set REGISTRY_URL.

- [ ] **Step 5.6: Commit**

```bash
git add platform_sdk/fastapi_app/base.py tests/unit/test_baseagentapp_registers.py
git commit -m "feat(registry): wire _register / _deregister into BaseAgentApp.lifespan

BaseAgentApp now extends Application. lifespan() calls _register after
setup_telemetry and _deregister inside the finally block before
flush_langfuse. Existing tests are unaffected because REGISTRY_URL is
never set in the test environment.

Also fixes BaseAgentApp.load_config signature to accept name (per
Application's abstract contract)."
```

---

### Task 6: Wire `_register` / `_deregister` into `McpService.lifespan`

**Files:**
- Modify: `platform_sdk/base/mcp_service.py`
- Create: `tests/unit/test_mcp_service_registers.py`

- [ ] **Step 6.1: Write failing test mirroring Task 5**

Create `tests/unit/test_mcp_service_registers.py`:

```python
"""Verify McpService.lifespan calls _register / _deregister."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_mcp_service_registers_on_startup_and_deregisters_on_shutdown(monkeypatch):
    monkeypatch.setenv("REGISTRY_URL", "http://r:8090")
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    monkeypatch.setenv("SERVICE_URL", "http://me:8080")
    order: list[str] = []

    class FakeRegistry:
        def __init__(self, **kw): pass
        async def register_self(self, p): order.append("register")
        async def start_heartbeat(self, n): order.append("hb_start")
        async def start_refresh(self): order.append("rf_start")
        async def stop_heartbeat(self): order.append("hb_stop")
        async def stop_refresh(self): order.append("rf_stop")
        async def deregister(self, n): order.append("deregister")
        async def aclose(self): order.append("aclose")

    monkeypatch.setattr("platform_sdk.base.application.RegistryClient", FakeRegistry)

    from platform_sdk.base import McpService

    class TestService(McpService):
        service_type = "mcp"
        cache_ttl_seconds = 0
        requires_database = False
        enable_telemetry = False
        def register_tools(self, mcp): pass
        async def on_startup(self): order.append("on_startup")
        async def on_shutdown(self): order.append("on_shutdown")

    svc = TestService("ai-mcp-test")

    async with svc.lifespan(server=None):
        order.append("yield")

    assert order[:3] == ["register", "hb_start", "rf_start"]
    assert "on_startup" in order and "yield" in order and "on_shutdown" in order
    assert order[-3:] == ["hb_stop", "rf_stop", "deregister"] or order[-4:][:3] == ["hb_stop", "rf_stop", "deregister"]
```

- [ ] **Step 6.2: Run the test — confirm it fails**

```bash
.venv/bin/pytest tests/unit/test_mcp_service_registers.py -v
```
Expected: FAIL.

- [ ] **Step 6.3: Modify `platform_sdk/base/mcp_service.py`**

Open the file and locate the `lifespan` method. Add `await self._register()` immediately after `setup_telemetry` (or at the very top if telemetry is disabled). Add `await self._deregister()` in the `finally` block, *before* the existing teardown.

The patched lifespan body becomes:

```python
    @asynccontextmanager
    async def lifespan(self, server: Any) -> Any:
        # Setup telemetry
        if self.enable_telemetry:
            from ..telemetry import setup_telemetry
            setup_telemetry(self.name)

        await self._register()    # <-- NEW

        # ... unchanged: assert_secrets_configured, OPA, cache, db_pool, on_startup ...

        try:
            yield
        finally:
            await self.on_shutdown()
            await self._deregister()    # <-- NEW
            # ... unchanged teardown of authorizer / cache / db_pool ...
```

(Find the exact locations from `mcp_service.py:104-188` per the existing structure.)

- [ ] **Step 6.4: Run the test to confirm it passes**

```bash
.venv/bin/pytest tests/unit/test_mcp_service_registers.py -v
```
Expected: 1 passed.

- [ ] **Step 6.5: Commit**

```bash
git add platform_sdk/base/mcp_service.py tests/unit/test_mcp_service_registers.py
git commit -m "feat(registry): wire _register / _deregister into McpService.lifespan

Symmetric to BaseAgentApp. Every MCP server now self-registers on
startup and gracefully deregisters on shutdown when REGISTRY_URL is set."
```

---

### Task 7: `BaseAgentApp.mcp_dependencies` (with `mcp_servers` deprecation path)

**Files:**
- Modify: `platform_sdk/fastapi_app/base.py`
- Create: `tests/unit/test_mcp_dependencies.py`

- [ ] **Step 7.1: Write failing tests**

Create `tests/unit/test_mcp_dependencies.py`:

```python
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

    class TestApp(BaseAgentApp):
        service_name = "test"
        mcp_dependencies = ["ai-mcp-data", "ai-mcp-payments"]

        def build_dependencies(self, *, bridges, checkpointer, store): return {}
        def routes(self): return []

    app = TestApp()
    app.registry = _StubRegistry()

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

    class TestApp(BaseAgentApp):
        service_name = "t"
        mcp_dependencies = ["alive", "stale-one"]
        def build_dependencies(self, *, bridges, checkpointer, store): return {}
        def routes(self): return []

    app = TestApp()
    app.registry = _StubRegistry()
    bridges = await app._connect_bridges(agent_ctx=None, timeout=10.0)
    assert "alive" in bridges and "stale-one" not in bridges


def test_mcp_servers_emits_deprecation_warning():
    """Setting only mcp_servers (no mcp_dependencies) logs a DeprecationWarning."""
    from platform_sdk.fastapi_app import BaseAgentApp

    class TestApp(BaseAgentApp):
        service_name = "deprecated"
        mcp_servers = {"x": "http://x"}
        def build_dependencies(self, *, bridges, checkpointer, store): return {}
        def routes(self): return []

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        app = TestApp()
        app._warn_if_using_legacy_mcp_servers()
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)


def test_mcp_dependencies_takes_precedence_over_mcp_servers():
    """If both are set, mcp_dependencies wins (no warning fires)."""
    from platform_sdk.fastapi_app import BaseAgentApp

    class TestApp(BaseAgentApp):
        service_name = "both"
        mcp_dependencies = ["x"]
        mcp_servers = {"x": "http://x"}
        def build_dependencies(self, *, bridges, checkpointer, store): return {}
        def routes(self): return []

    app = TestApp()
    # _warn_if_using_legacy_mcp_servers should be a no-op when mcp_dependencies is non-empty
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        app._warn_if_using_legacy_mcp_servers()
    assert not any(issubclass(w.category, DeprecationWarning) for w in caught)
```

- [ ] **Step 7.2: Run the test — confirm it fails**

```bash
.venv/bin/pytest tests/unit/test_mcp_dependencies.py -v
```
Expected: FAIL — `mcp_dependencies` attr not defined.

- [ ] **Step 7.3: Modify `platform_sdk/fastapi_app/base.py`**

Add a class attribute and rewrite `_connect_bridges` to prefer the registry path:

Find:
```python
    mcp_servers: Mapping[str, str] = {}
```

Add immediately after:
```python
    mcp_dependencies: list[str] = []   # NEW: registry-driven peer discovery.
                                       # When non-empty, replaces mcp_servers entirely.
```

Replace `_connect_bridges` with:

```python
    async def _connect_bridges(self, agent_ctx, timeout: float) -> dict:
        from ..mcp_bridge import MCPToolBridge

        log = get_logger(self.service_name)
        bridges: dict = {}

        # Path 1: registry-driven (preferred).
        if self.mcp_dependencies:
            for name in self.mcp_dependencies:
                try:
                    entry = await self.registry.lookup(name)  # type: ignore[union-attr]
                except Exception as exc:
                    log.warning("registry_lookup_failed", name=name, error=str(exc))
                    continue
                if not entry.healthy:
                    log.warning("mcp_unhealthy_skipping", name=name, state=entry.state)
                    continue
                bridge_url = str(entry.url).rstrip("/") + "/sse"
                bridges[name] = MCPToolBridge(bridge_url, agent_context=agent_ctx)
            await self._connect_all(bridges, timeout, log)
            return bridges

        # Path 2: deprecated mcp_servers dict.
        self._warn_if_using_legacy_mcp_servers()
        if not self.mcp_servers:
            return {}
        bridges = {
            name: MCPToolBridge(self._resolve_mcp_url(name, default), agent_context=agent_ctx)
            for name, default in self.mcp_servers.items()
        }
        await self._connect_all(bridges, timeout, log)
        return bridges

    async def _connect_all(self, bridges: dict, timeout: float, log) -> None:
        if not bridges:
            return
        log.info("mcp_connecting_all", servers=list(bridges.keys()), timeout=timeout)
        await asyncio.gather(
            *[b.connect(startup_timeout=timeout) for b in bridges.values()],
            return_exceptions=True,
        )
        for name, bridge in bridges.items():
            log.info("mcp_startup_status", server=name, connected=bridge.is_connected)

    def _warn_if_using_legacy_mcp_servers(self) -> None:
        import warnings
        if self.mcp_dependencies:
            return  # new path is in use; nothing to warn about
        if self.mcp_servers:
            warnings.warn(
                f"{type(self).__name__}.mcp_servers is deprecated; use "
                "mcp_dependencies (list[str]) instead. mcp_servers will be removed in 0.6.0.",
                DeprecationWarning,
                stacklevel=2,
            )
```

- [ ] **Step 7.4: Run tests to confirm they pass**

```bash
.venv/bin/pytest tests/unit/test_mcp_dependencies.py -v
```
Expected: 4 passed.

- [ ] **Step 7.5: Commit**

```bash
git add platform_sdk/fastapi_app/base.py tests/unit/test_mcp_dependencies.py
git commit -m "feat(registry): BaseAgentApp.mcp_dependencies (registry-driven discovery)

mcp_dependencies: list[str] replaces the hardcoded mcp_servers: dict.
When set, _connect_bridges resolves each name via self.registry.lookup()
and skips entries that are not healthy (state != 'registered'). The
url returned by the registry is suffixed with /sse — same MCP wire path
the platform has used since v0.4.0.

mcp_servers is retained for one minor release. Setting it without
mcp_dependencies emits a DeprecationWarning. Setting both: mcp_dependencies
wins, no warning. Removal scheduled for SDK 0.6.0."
```

---

### Task 8: `fake_registry` pytest fixture in `platform_sdk.testing.plugin`

**Files:**
- Modify: `platform_sdk/testing/plugin.py`
- Create: `tests/unit/test_fake_registry_fixture.py`

- [ ] **Step 8.1: Write failing test**

Create `tests/unit/test_fake_registry_fixture.py`:

```python
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
```

- [ ] **Step 8.2: Run the test — confirm it fails**

```bash
.venv/bin/pytest tests/unit/test_fake_registry_fixture.py -v
```
Expected: FAIL — `fake_registry` fixture not defined.

- [ ] **Step 8.3: Add the fixture to `platform_sdk/testing/plugin.py`**

Append:

```python
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
```

- [ ] **Step 8.4: Reinstall the SDK so the plugin re-registers**

```bash
cd /Users/admin-h26/carve-out/ai-platform-sdk
.venv/bin/pip install -e . --quiet
```

- [ ] **Step 8.5: Run the test — confirm it passes**

```bash
.venv/bin/pytest tests/unit/test_fake_registry_fixture.py -v
```
Expected: 3 passed.

- [ ] **Step 8.6: Run the entire unit suite — no regressions**

```bash
.venv/bin/pytest tests/unit -m unit -q
```
Expected: all green.

- [ ] **Step 8.7: Commit**

```bash
git add platform_sdk/testing/plugin.py tests/unit/test_fake_registry_fixture.py
git commit -m "test(registry): add fake_registry pytest fixture

Auto-registered via the existing pytest11 entry point. Service-repo tests
that want to verify their own self-registration can do:

    async def test_my_service_registers(fake_registry, monkeypatch):
        monkeypatch.setattr('platform_sdk.base.application.RegistryClient',
                            lambda **kw: fake_registry)
        ...
        assert fake_registry.calls[0][0] == 'register_self'

The fake records every call and serves lookups from a seeded dict; tests
do not need to spin up a real registry."
```

---

### Task 9: Bump SDK to 0.5.0; tag and release

**Files:**
- Modify: `pyproject.toml` (version)
- Modify: `CHANGELOG.md`

- [ ] **Step 9.1: Bump version**

Edit `pyproject.toml`. Change `version = "0.4.0"` → `version = "0.5.0"`. Add `aiosqlite` to `[project.optional-dependencies]`:

```toml
[project.optional-dependencies]
fastapi = ["fastapi>=0.111.0"]
postgres-checkpointer = ["langgraph-checkpoint-postgres>=2.0.0"]
registry-server = ["aiosqlite>=0.20.0,<1.0.0", "pyyaml>=6.0,<7.0"]   # NEW
```

`registry-server` is for the ai-registry repo to install via `pip install enterprise-ai-platform-sdk[fastapi,registry-server]`. Service repos that only consume the registry (every agent / MCP) don't need it.

- [ ] **Step 9.2: Update CHANGELOG**

Add a new section at the top of `CHANGELOG.md`:

```markdown
## 0.5.0 — 2026-04-30

### Added
- `platform_sdk.registry` package — `RegistryClient` (lookup with cache,
  soft-fail, circuit breaker; register_self / deregister; heartbeat and
  refresh background tasks), `RegistryEntry` / `RegistrationRequest` Pydantic
  models, `RegistryUnreachable` / `ServiceNotFound` exceptions.
- `Application._register()` / `_deregister()` lifecycle hooks. Every
  Application subclass (Agent, McpService, BaseAgentApp) self-registers with
  the platform registry on startup when `REGISTRY_URL` is set, and
  gracefully deregisters on shutdown.
- `BaseAgentApp.mcp_dependencies: list[str]` — registry-driven peer
  discovery. Replaces the hardcoded `mcp_servers` dict.
- `service_type` and `service_metadata` ClassVars on `Application`.
- `fake_registry` pytest fixture (auto-registered via plugin).
- Optional extra `[registry-server]` (aiosqlite + pyyaml) for the
  ai-registry server repo.

### Changed
- `BaseAgentApp` now extends `Application` directly. `BaseAgentApp.load_config`
  signature accepts an optional `name` parameter for compatibility with
  `Application.load_config(name)`.
- `BaseAgentApp.mcp_servers` is deprecated. Setting it without
  `mcp_dependencies` emits a `DeprecationWarning`. Removal scheduled for 0.6.0.

### Migration notes
- Existing services on 0.4.0 keep working — both `mcp_servers` and the
  absence of `REGISTRY_URL` are fully backwards-compatible. When you bump
  to 0.5.0 and set `REGISTRY_URL` in your environment, your service
  self-registers automatically. Migrate `mcp_servers` → `mcp_dependencies`
  on your own schedule before 0.6.0.
```

- [ ] **Step 9.3: Run the full unit suite as a smoke check**

```bash
.venv/bin/pytest tests/unit -m unit -q
```
Expected: all green.

- [ ] **Step 9.4: Commit, push feature branch, open PR**

```bash
git add pyproject.toml CHANGELOG.md
git commit -m "chore(release): bump to 0.5.0; add registry-server optional extra

0.5.0 ships the platform service registry — RegistryClient + Application
hooks (additive). See CHANGELOG.md for the full list of additions and
the mcp_servers deprecation."
git push -u origin feature/registry
gh pr create --base main --title "feat(registry): SDK 0.5.0 — service registry client + Application hooks" \
  --body "Implements Tasks 1-9 of docs/plans/2026-04-30-service-registry.md. Additive only; no breaking changes."
```

- [ ] **Step 9.5: After PR merge, cut release branch and tag**

```bash
git checkout main
git pull origin main
git checkout -b release/0.5
git push -u origin release/0.5
git tag -a v0.5.0 -m "Release 0.5.0 — service registry SDK + Application self-registration"
git push origin v0.5.0
```

The release workflow builds and pushes:
- `ghcr.io/narisun/ai-python-base:3.11-sdk0.5.0`
- `ghcr.io/narisun/ai-python-base:3.11-sdk-latest`

- [ ] **Step 9.6: Verify the workflow succeeded**

```bash
sleep 10
gh run list --repo narisun/ai-platform-sdk --workflow=release.yml --limit 3
gh run watch --repo narisun/ai-platform-sdk
docker pull ghcr.io/narisun/ai-python-base:3.11-sdk0.5.0
docker run --rm ghcr.io/narisun/ai-python-base:3.11-sdk0.5.0 \
  pip show enterprise-ai-platform-sdk | grep -E "^(Name|Version)"
```

Expected: `Name: enterprise-ai-platform-sdk`, `Version: 0.5.0`.

---

## Phase 2 — `narisun/ai-registry` repo

All Phase 2 work happens in a fresh repo. Use the SDK's own scaffolding CLI to start, then customize.

### Task 10: Scaffold the `ai-registry` repo

**Files:**
- Create: entire repo at `/Users/admin-h26/carve-out/ai-registry/`

- [ ] **Step 10.1: Scaffold from the SDK CLI**

```bash
mkdir -p /Users/admin-h26/carve-out
cd /Users/admin-h26/carve-out
rm -rf ai-registry
/Users/admin-h26/carve-out/ai-platform-sdk/.venv/bin/platform-sdk \
  new agent --name registry --target /Users/admin-h26/carve-out/ai-registry
cd ai-registry
ls
```

Expected: `Dockerfile`, `pyproject.toml`, `requirements.txt`, `src/`, `tests/`, `conftest.py`, `.gitignore`, `README.md`.

- [ ] **Step 10.2: Pin SDK to 0.5.0 + create runtime requirements**

Edit `requirements.txt`:

```
enterprise-ai-platform-sdk[fastapi,registry-server] @ git+ssh://git@github.com/narisun/ai-platform-sdk.git@v0.5.0
uvicorn[standard]>=0.30.0,<1.0.0
```

Create `requirements-runtime.txt` (Docker-only — SDK provided by base image):

```
aiosqlite>=0.20.0,<1.0.0
pyyaml>=6.0,<7.0
uvicorn[standard]>=0.30.0,<1.0.0
```

Edit `Dockerfile`:

```dockerfile
ARG BASE_TAG=3.11-sdk0.5.0
FROM ghcr.io/narisun/ai-python-base:${BASE_TAG}

WORKDIR /app
COPY requirements-runtime.txt .
RUN pip install --no-cache-dir -r requirements-runtime.txt
COPY src/ /app/src/

USER appuser
EXPOSE 8090
CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8090"]
```

Edit `pyproject.toml`:

```toml
[project]
name = "ai-registry"
version = "0.5.0"
description = "Enterprise AI Platform — service registry (catalog + health + discovery)"
requires-python = ">=3.11"
dependencies = [
    "enterprise-ai-platform-sdk[fastapi,registry-server] @ git+ssh://git@github.com/narisun/ai-platform-sdk.git@v0.5.0",
    "uvicorn[standard]>=0.30.0,<1.0.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = [
    "unit: fast unit tests (no I/O, no Docker)",
    "component: multi-class tests with faked external systems",
    "integration: docker-compose stack required",
]
```

- [ ] **Step 10.3: Initialize git, install deps, run smoke**

```bash
cd /Users/admin-h26/carve-out/ai-registry
git init -b main
python3 -m venv .venv
.venv/bin/pip install --upgrade pip --quiet
# For dev, install SDK editably so SDK changes show up immediately
.venv/bin/pip install -e /Users/admin-h26/carve-out/ai-platform-sdk
.venv/bin/pip install -r requirements-runtime.txt
.venv/bin/pip install pytest pytest-asyncio
.venv/bin/python -c "import sys; sys.path.insert(0, '.'); from src.app import app; print(app.title)"
```

- [ ] **Step 10.4: First commit**

```bash
git add -A
git commit -m "chore: scaffold ai-registry from platform-sdk new agent template

Initial structure generated by 'platform-sdk new agent --name registry'.
Customizations: project name, SDK pin includes [registry-server] extra,
requirements-runtime.txt for Docker, BASE_TAG=3.11-sdk0.5.0, EXPOSE 8090.

src/app.py is the placeholder generated by the scaffolder. The real
RegistryApp lands in Task 16 after we have config / store / routes
in place."
```

---

### Task 11: `RegistryConfig` + `ConfigLoader`

**Files:**
- Create: `src/config.py`
- Create: `src/config_loader.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/unit/test_config.py`
- Create: `tests/unit/test_config_loader.py`

- [ ] **Step 11.1: Write failing tests**

Create `tests/unit/test_config.py`:

```python
"""Tests for RegistryConfig — fail-fast validation, env loading."""
import pytest

pytestmark = pytest.mark.unit


def test_defaults_construct(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "test")
    for k in ("REGISTRY_PORT", "SQLITE_PATH", "SEED_PATH",
              "HEARTBEAT_GRACE_SECONDS", "EVICTION_SECONDS",
              "REAPER_INTERVAL_SECONDS"):
        monkeypatch.delenv(k, raising=False)
    from src.config import RegistryConfig
    cfg = RegistryConfig.from_env()
    assert cfg.port == 8090
    assert cfg.heartbeat_grace_seconds == 60
    assert cfg.eviction_seconds == 300
    assert cfg.reaper_interval_seconds == 30


def test_validation_rejects_negative_grace():
    from src.config import RegistryConfig
    with pytest.raises(ValueError, match="heartbeat_grace_seconds"):
        RegistryConfig(
            port=8090, sqlite_path="/tmp/x.db", internal_api_key="k",
            heartbeat_grace_seconds=-1, eviction_seconds=300, reaper_interval_seconds=30,
        )


def test_validation_lists_all_errors_at_once():
    from src.config import RegistryConfig
    with pytest.raises(ValueError) as exc:
        RegistryConfig(
            port=-1, sqlite_path="/tmp/x.db", internal_api_key="",
            heartbeat_grace_seconds=10, eviction_seconds=5,  # eviction < grace = invalid
            reaper_interval_seconds=30,
        )
    msg = str(exc.value)
    assert "port" in msg
    assert "internal_api_key" in msg
    assert "eviction_seconds" in msg
```

Create `tests/unit/test_config_loader.py`:

```python
"""Tests for ConfigLoader (YAML seed parser)."""
import textwrap
import pytest

pytestmark = pytest.mark.unit


def test_load_returns_empty_when_path_is_none():
    from src.config_loader import ConfigLoader
    assert ConfigLoader(seed_path=None).load() == []


def test_load_returns_empty_when_file_missing(tmp_path):
    from src.config_loader import ConfigLoader
    assert ConfigLoader(seed_path=tmp_path / "missing.yaml").load() == []


def test_load_parses_seeded_entries(tmp_path):
    from src.config_loader import ConfigLoader
    p = tmp_path / "registry.yaml"
    p.write_text(textwrap.dedent("""
    services:
      - name: ai-mcp-data
        type: mcp
        expected_url: http://data-mcp:8080
        metadata:
          owner: data-team
      - name: ai-agent-analytics
        type: agent
        expected_url: http://analytics-agent:8000
    """))
    entries = ConfigLoader(seed_path=p).load()
    assert {e.name for e in entries} == {"ai-mcp-data", "ai-agent-analytics"}


def test_load_raises_on_invalid_yaml(tmp_path):
    from src.config_loader import ConfigLoader
    p = tmp_path / "registry.yaml"
    p.write_text("[broken yaml")
    with pytest.raises(ValueError, match="(?i)parse"):
        ConfigLoader(seed_path=p).load()


def test_load_validates_entry_shape(tmp_path):
    from src.config_loader import ConfigLoader
    p = tmp_path / "registry.yaml"
    p.write_text("services:\n  - name: x\n")
    with pytest.raises(ValueError, match="(type|expected_url)"):
        ConfigLoader(seed_path=p).load()
```

- [ ] **Step 11.2: Run — confirm fail**

```bash
.venv/bin/pytest tests/unit -v
```

- [ ] **Step 11.3: Create `src/config.py`**

```python
"""RegistryConfig — typed config with fail-fast validation."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RegistryConfig:
    port: int = 8090
    sqlite_path: Path = field(default_factory=lambda: Path("/var/lib/registry/registry.db"))
    seed_path: Path | None = None
    internal_api_key: str = ""
    heartbeat_grace_seconds: int = 60
    eviction_seconds: int = 300
    reaper_interval_seconds: int = 30
    service_url: str = ""
    enable_ui: bool = True

    def __post_init__(self) -> None:
        errors: list[str] = []
        if self.port <= 0 or self.port > 65535:
            errors.append(f"port={self.port} must be in 1..65535")
        if not self.internal_api_key:
            errors.append("internal_api_key must not be empty (set INTERNAL_API_KEY env)")
        if self.heartbeat_grace_seconds < 0:
            errors.append(f"heartbeat_grace_seconds={self.heartbeat_grace_seconds} cannot be negative")
        if self.eviction_seconds < self.heartbeat_grace_seconds:
            errors.append(
                f"eviction_seconds={self.eviction_seconds} must be >= "
                f"heartbeat_grace_seconds={self.heartbeat_grace_seconds}"
            )
        if self.reaper_interval_seconds <= 0:
            errors.append(f"reaper_interval_seconds={self.reaper_interval_seconds} must be positive")
        if isinstance(self.sqlite_path, str):
            self.sqlite_path = Path(self.sqlite_path)
        if self.seed_path is not None and isinstance(self.seed_path, str):
            self.seed_path = Path(self.seed_path)
        if errors:
            raise ValueError(f"RegistryConfig validation failed: {'; '.join(errors)}")

    @classmethod
    def from_env(cls) -> "RegistryConfig":
        seed = os.environ.get("SEED_PATH", "")
        return cls(
            port=int(os.environ.get("REGISTRY_PORT", "8090")),
            sqlite_path=Path(os.environ.get("SQLITE_PATH", "/var/lib/registry/registry.db")),
            seed_path=Path(seed) if seed else None,
            internal_api_key=os.environ.get("INTERNAL_API_KEY", ""),
            heartbeat_grace_seconds=int(os.environ.get("HEARTBEAT_GRACE_SECONDS", "60")),
            eviction_seconds=int(os.environ.get("EVICTION_SECONDS", "300")),
            reaper_interval_seconds=int(os.environ.get("REAPER_INTERVAL_SECONDS", "30")),
            service_url=os.environ.get("SERVICE_URL", ""),
            enable_ui=os.environ.get("ENABLE_UI", "true").lower() != "false",
        )
```

- [ ] **Step 11.4: Create `src/config_loader.py`**

```python
"""ConfigLoader — parses optional registry.yaml seed."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class SeededEntry:
    name: str
    type: str
    expected_url: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ConfigLoader:
    def __init__(self, seed_path: Path | None) -> None:
        self.seed_path = seed_path

    def load(self) -> list[SeededEntry]:
        if self.seed_path is None or not self.seed_path.exists():
            return []
        try:
            data = yaml.safe_load(self.seed_path.read_text()) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"Failed to parse {self.seed_path}: {exc}") from exc

        services_raw = data.get("services", []) or []
        if not isinstance(services_raw, list):
            raise ValueError(f"{self.seed_path}: 'services' must be a list")

        entries: list[SeededEntry] = []
        errors: list[str] = []
        for i, raw in enumerate(services_raw):
            if not isinstance(raw, dict):
                errors.append(f"[{i}] entry must be a mapping")
                continue
            for required in ("name", "type", "expected_url"):
                if required not in raw:
                    errors.append(f"[{i}] missing required field: {required}")
            if errors:
                continue
            entries.append(SeededEntry(
                name=raw["name"], type=raw["type"],
                expected_url=raw["expected_url"],
                metadata=raw.get("metadata", {}) or {},
            ))
        if errors:
            raise ValueError(f"Seed validation failed: {'; '.join(errors)}")
        return entries
```

- [ ] **Step 11.5: Run tests + commit**

```bash
.venv/bin/pytest tests/unit/test_config.py tests/unit/test_config_loader.py -v
git add src/config.py src/config_loader.py tests/unit/
git commit -m "feat(registry): RegistryConfig + ConfigLoader

RegistryConfig: typed dataclass with multi-error fail-fast __post_init__.
ConfigLoader: optional YAML seed parser; missing-file is a no-op."
```

---

### Task 12: `SqliteStore`

**Files:**
- Create: `src/store.py`
- Create: `tests/unit/test_store.py`

- [ ] **Step 12.1: Write failing tests**

Create `tests/unit/test_store.py`:

```python
"""Tests for SqliteStore — schema, CRUD, idempotent apply_seed, reaper queries."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_init_schema_creates_db(tmp_path):
    from src.store import SqliteStore
    store = SqliteStore(tmp_path / "r.db")
    await store.init_schema()
    assert (tmp_path / "r.db").exists()


@pytest.mark.asyncio
async def test_register_then_get(tmp_path):
    from src.store import SqliteStore
    store = SqliteStore(tmp_path / "r.db")
    await store.init_schema()
    await store.register("ai-mcp-data", url="http://data-mcp:8080", type_="mcp", version="0.5.0")
    row = await store.get("ai-mcp-data")
    assert row["state"] == "registered"
    assert row["url"] == "http://data-mcp:8080"


@pytest.mark.asyncio
async def test_register_is_upsert(tmp_path):
    from src.store import SqliteStore
    store = SqliteStore(tmp_path / "r.db")
    await store.init_schema()
    await store.register("x", url="http://x:1", type_="mcp", version="1")
    await store.register("x", url="http://x:2", type_="mcp", version="2")
    row = await store.get("x")
    assert row["url"] == "http://x:2" and row["version"] == "2"


@pytest.mark.asyncio
async def test_heartbeat_bumps_timestamp(tmp_path):
    from src.store import SqliteStore
    store = SqliteStore(tmp_path / "r.db")
    await store.init_schema()
    await store.register("x", url="http://x", type_="mcp", version=None)
    pre = (await store.get("x"))["last_heartbeat_at"]
    await asyncio.sleep(0.05)
    await store.heartbeat("x")
    post = (await store.get("x"))["last_heartbeat_at"]
    assert post > pre


@pytest.mark.asyncio
async def test_heartbeat_returns_false_when_unknown(tmp_path):
    from src.store import SqliteStore
    store = SqliteStore(tmp_path / "r.db")
    await store.init_schema()
    assert (await store.heartbeat("missing")) is False


@pytest.mark.asyncio
async def test_deregister_unseeded_deletes(tmp_path):
    from src.store import SqliteStore
    store = SqliteStore(tmp_path / "r.db")
    await store.init_schema()
    await store.register("x", url="http://x", type_="mcp", version=None)
    await store.deregister("x")
    assert (await store.get("x")) is None


@pytest.mark.asyncio
async def test_deregister_seeded_returns_to_expected_unregistered(tmp_path):
    from src.store import SqliteStore
    from src.config_loader import SeededEntry
    store = SqliteStore(tmp_path / "r.db")
    await store.init_schema()
    await store.apply_seed([SeededEntry(name="x", type="mcp", expected_url="http://x:8080")])
    await store.register("x", url="http://x:8080", type_="mcp", version=None)
    await store.deregister("x")
    assert (await store.get("x"))["state"] == "expected_unregistered"


@pytest.mark.asyncio
async def test_apply_seed_is_idempotent(tmp_path):
    from src.store import SqliteStore
    from src.config_loader import SeededEntry
    store = SqliteStore(tmp_path / "r.db")
    await store.init_schema()
    seed = [SeededEntry(name="a", type="mcp", expected_url="http://a"),
            SeededEntry(name="b", type="agent", expected_url="http://b")]
    await store.apply_seed(seed)
    await store.apply_seed(seed)
    assert len(await store.list_all()) == 2


@pytest.mark.asyncio
async def test_reaper_query_helpers(tmp_path):
    from src.store import SqliteStore
    store = SqliteStore(tmp_path / "r.db")
    await store.init_schema()
    await store.register("x", url="http://x", type_="mcp", version=None)
    # Backdate
    import aiosqlite
    async with aiosqlite.connect(tmp_path / "r.db") as db:
        old = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        await db.execute("UPDATE services SET last_heartbeat_at=?", (old,))
        await db.commit()
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    candidates = await store.find_stale_candidates(older_than_iso=cutoff)
    assert "x" in candidates
```

- [ ] **Step 12.2: Run — fails**

```bash
.venv/bin/pytest tests/unit/test_store.py -v
```

- [ ] **Step 12.3: Create `src/store.py`**

```python
"""SqliteStore — single-table catalog (aiosqlite)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import aiosqlite

from .config_loader import SeededEntry

_DDL = """
CREATE TABLE IF NOT EXISTS services (
    name              TEXT PRIMARY KEY,
    url               TEXT,
    expected_url      TEXT,
    type              TEXT NOT NULL,
    state             TEXT NOT NULL,
    version           TEXT,
    metadata_json     TEXT,
    last_heartbeat_at TEXT,
    registered_at     TEXT,
    last_changed_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_services_state ON services (state);
CREATE INDEX IF NOT EXISTS idx_services_type  ON services (type);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    out = dict(row)
    out["metadata"] = json.loads(out.pop("metadata_json") or "{}")
    return out


class SqliteStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    async def _conn(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(self.path)
        conn.row_factory = aiosqlite.Row
        return conn

    async def init_schema(self) -> None:
        async with await self._conn() as db:
            await db.executescript(_DDL)
            await db.commit()

    async def apply_seed(self, seed: Iterable[SeededEntry]) -> None:
        rows = [(s.name, s.expected_url, s.type, "expected_unregistered",
                 json.dumps(s.metadata), _now()) for s in seed]
        if not rows:
            return
        async with await self._conn() as db:
            await db.executemany(
                "INSERT OR IGNORE INTO services "
                "(name, expected_url, type, state, metadata_json, last_changed_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )
            await db.commit()

    async def register(self, name: str, *, url: str, type_: str,
                       version: str | None, metadata: dict | None = None) -> None:
        now = _now()
        meta_json = json.dumps(metadata or {})
        async with await self._conn() as db:
            await db.execute(
                """
                INSERT INTO services (
                    name, url, type, state, version, metadata_json,
                    registered_at, last_heartbeat_at, last_changed_at
                ) VALUES (?, ?, ?, 'registered', ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    url=excluded.url,
                    type=excluded.type,
                    state='registered',
                    version=excluded.version,
                    metadata_json=excluded.metadata_json,
                    registered_at=COALESCE(services.registered_at, ?),
                    last_heartbeat_at=?,
                    last_changed_at=?
                """,
                (name, url, type_, version, meta_json, now, now, now, now, now, now),
            )
            await db.commit()

    async def heartbeat(self, name: str) -> bool:
        now = _now()
        async with await self._conn() as db:
            cur = await db.execute(
                "UPDATE services SET last_heartbeat_at=?, state='registered', last_changed_at=? "
                "WHERE name=? AND state IN ('registered', 'stale')",
                (now, now, name),
            )
            await db.commit()
            return cur.rowcount > 0

    async def deregister(self, name: str) -> None:
        now = _now()
        async with await self._conn() as db:
            cur = await db.execute("SELECT expected_url FROM services WHERE name=?", (name,))
            row = await cur.fetchone()
            if row is None:
                return
            if row["expected_url"]:
                await db.execute(
                    "UPDATE services SET state='expected_unregistered', "
                    "url=NULL, last_heartbeat_at=NULL, last_changed_at=? WHERE name=?",
                    (now, name),
                )
            else:
                await db.execute("DELETE FROM services WHERE name=?", (name,))
            await db.commit()

    async def mark_stale(self, name: str) -> None:
        async with await self._conn() as db:
            await db.execute(
                "UPDATE services SET state='stale', last_changed_at=? WHERE name=?",
                (_now(), name),
            )
            await db.commit()

    async def evict(self, name: str) -> None:
        await self.deregister(name)

    async def get(self, name: str) -> dict | None:
        async with await self._conn() as db:
            cur = await db.execute("SELECT * FROM services WHERE name=?", (name,))
            row = await cur.fetchone()
            return _row_to_dict(row) if row else None

    async def list_all(self) -> list[dict]:
        async with await self._conn() as db:
            cur = await db.execute("SELECT * FROM services ORDER BY name")
            rows = await cur.fetchall()
            return [_row_to_dict(r) for r in rows]

    async def find_stale_candidates(self, *, older_than_iso: str) -> list[str]:
        async with await self._conn() as db:
            cur = await db.execute(
                "SELECT name FROM services WHERE state='registered' "
                "AND (last_heartbeat_at IS NULL OR last_heartbeat_at < ?)",
                (older_than_iso,),
            )
            return [r["name"] for r in await cur.fetchall()]

    async def find_eviction_candidates(self, *, older_than_iso: str) -> list[str]:
        async with await self._conn() as db:
            cur = await db.execute(
                "SELECT name FROM services WHERE state='stale' "
                "AND (last_heartbeat_at IS NULL OR last_heartbeat_at < ?)",
                (older_than_iso,),
            )
            return [r["name"] for r in await cur.fetchall()]
```

- [ ] **Step 12.4: Run + commit**

```bash
.venv/bin/pytest tests/unit/test_store.py -v
git add src/store.py tests/unit/test_store.py
git commit -m "feat(registry): SqliteStore — schema + CRUD + apply_seed + reaper queries"
```

---

### Task 13: Reaper background task

**Files:**
- Create: `src/reaper.py`
- Create: `tests/unit/test_reaper.py`

- [ ] **Step 13.1: Write failing test**

Create `tests/unit/test_reaper.py`:

```python
"""Tests for reaper — drives state transitions on schedule."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_reaper_one_pass_marks_stale_then_evicts(tmp_path):
    from src.config import RegistryConfig
    from src.config_loader import SeededEntry
    from src.reaper import _run_one_pass
    from src.store import SqliteStore
    import aiosqlite

    store = SqliteStore(tmp_path / "r.db")
    await store.init_schema()
    await store.apply_seed([SeededEntry(name="seeded", type="mcp", expected_url="http://x")])
    await store.register("seeded", url="http://x", type_="mcp", version=None)
    await store.register("unseeded", url="http://y", type_="mcp", version=None)

    # Backdate heartbeats past the grace window
    async with aiosqlite.connect(tmp_path / "r.db") as db:
        old = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        await db.execute("UPDATE services SET last_heartbeat_at=?", (old,))
        await db.commit()

    config = RegistryConfig(
        port=8090, sqlite_path=tmp_path / "r.db", internal_api_key="k",
        heartbeat_grace_seconds=60, eviction_seconds=300, reaper_interval_seconds=30,
    )
    await _run_one_pass(store, config)
    assert (await store.get("seeded"))["state"] == "stale"
    assert (await store.get("unseeded"))["state"] == "stale"

    # Backdate further (past eviction)
    async with aiosqlite.connect(tmp_path / "r.db") as db:
        old2 = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
        await db.execute("UPDATE services SET last_heartbeat_at=?", (old2,))
        await db.commit()
    await _run_one_pass(store, config)
    seeded = await store.get("seeded")
    unseeded = await store.get("unseeded")
    assert seeded is not None and seeded["state"] == "expected_unregistered"
    assert unseeded is None
```

- [ ] **Step 13.2: Create `src/reaper.py`**

```python
"""Reaper background task — drives state transitions on schedule."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta

from .config import RegistryConfig
from .store import SqliteStore


async def _run_one_pass(store: SqliteStore, config: RegistryConfig) -> None:
    now = datetime.now(timezone.utc)
    stale_cutoff = (now - timedelta(seconds=config.heartbeat_grace_seconds)).isoformat()
    for name in await store.find_stale_candidates(older_than_iso=stale_cutoff):
        await store.mark_stale(name)
    evict_cutoff = (now - timedelta(seconds=config.eviction_seconds)).isoformat()
    for name in await store.find_eviction_candidates(older_than_iso=evict_cutoff):
        await store.evict(name)


async def reaper_loop(store: SqliteStore, config: RegistryConfig) -> None:
    """Forever loop. Cancel the asyncio.Task to stop."""
    while True:
        try:
            await _run_one_pass(store, config)
        except asyncio.CancelledError:
            raise
        except Exception:
            from platform_sdk.logging import get_logger
            get_logger("ai-registry").warning("reaper_pass_failed", exc_info=True)
        await asyncio.sleep(config.reaper_interval_seconds)
```

- [ ] **Step 13.3: Run + commit**

```bash
.venv/bin/pytest tests/unit/test_reaper.py -v
git add src/reaper.py tests/unit/test_reaper.py
git commit -m "feat(registry): reaper background task

Marks registered → stale after grace_seconds; evicts after eviction_seconds
(seeded → expected_unregistered; unseeded → DELETE). Reaper failures are
logged but never crash the loop."
```

---

### Task 14: Write routes (register / deregister / heartbeat) + auth gate

**Files:**
- Create: `src/routes/__init__.py`
- Create: `src/routes/_auth.py`
- Create: `src/routes/register.py`
- Create: `src/routes/heartbeat.py`
- Create: `tests/unit/test_routes_register.py`
- Create: `tests/unit/test_routes_heartbeat.py`

- [ ] **Step 14.1: Write failing tests**

Create `tests/unit/test_routes_register.py`:

```python
"""Tests for the register/deregister routes."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


@pytest.fixture
def client(tmp_path):
    from src.routes.register import register_router
    from src.store import SqliteStore
    store = SqliteStore(tmp_path / "r.db")
    import asyncio
    asyncio.get_event_loop().run_until_complete(store.init_schema())
    app = FastAPI()
    app.state.store = store
    app.state.api_key = "test-key"
    app.include_router(register_router)
    return TestClient(app)


def test_post_services_requires_auth(client):
    r = client.post("/api/services", json={
        "name": "x", "url": "http://x", "type": "mcp",
    })
    assert r.status_code == 401


def test_post_services_creates_entry(client):
    r = client.post(
        "/api/services",
        headers={"Authorization": "Bearer test-key"},
        json={"name": "ai-mcp-data", "url": "http://data-mcp:8080", "type": "mcp"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "ai-mcp-data"
    assert body["state"] == "registered"


def test_post_services_idempotent_on_repeat(client):
    headers = {"Authorization": "Bearer test-key"}
    body = {"name": "x", "url": "http://x:1", "type": "mcp"}
    r1 = client.post("/api/services", headers=headers, json=body)
    r2 = client.post("/api/services", headers=headers, json={**body, "url": "http://x:2"})
    assert r1.status_code == 200
    assert r2.status_code == 200
    # Re-registration with new URL should win
    assert r2.json()["url"].rstrip("/") == "http://x:2"


def test_delete_services_removes_or_unregisters(client):
    headers = {"Authorization": "Bearer test-key"}
    client.post("/api/services", headers=headers, json={
        "name": "x", "url": "http://x", "type": "mcp",
    })
    r = client.delete("/api/services/x", headers=headers)
    assert r.status_code == 204
```

Create `tests/unit/test_routes_heartbeat.py`:

```python
"""Tests for POST /api/services/{name}/heartbeat."""
from __future__ import annotations

import asyncio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


@pytest.fixture
def client(tmp_path):
    from src.routes.heartbeat import heartbeat_router
    from src.store import SqliteStore
    store = SqliteStore(tmp_path / "r.db")
    asyncio.get_event_loop().run_until_complete(store.init_schema())
    app = FastAPI()
    app.state.store = store
    app.state.api_key = "test-key"
    app.include_router(heartbeat_router)
    return TestClient(app)


def test_heartbeat_requires_auth(client):
    r = client.post("/api/services/x/heartbeat")
    assert r.status_code == 401


def test_heartbeat_404_when_unknown(client):
    r = client.post("/api/services/missing/heartbeat",
                     headers={"Authorization": "Bearer test-key"})
    assert r.status_code == 404


def test_heartbeat_200_when_registered(client, tmp_path):
    from src.store import SqliteStore
    store: SqliteStore = client.app.state.store
    asyncio.get_event_loop().run_until_complete(
        store.register("x", url="http://x", type_="mcp", version=None)
    )
    r = client.post("/api/services/x/heartbeat",
                     headers={"Authorization": "Bearer test-key"})
    assert r.status_code == 200
```

- [ ] **Step 14.2: Create `src/routes/__init__.py`**

```python
"""HTTP route modules for the registry server."""
```

- [ ] **Step 14.3: Create `src/routes/_auth.py`**

```python
"""Bearer-token guard. Reads the expected key off app.state.api_key (set in lifespan)."""
from __future__ import annotations

from fastapi import HTTPException, Request, status


async def require_api_key(request: Request) -> None:
    expected = getattr(request.app.state, "api_key", None)
    auth = request.headers.get("authorization", "")
    if not expected or not auth.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid Authorization header")
    token = auth.split(" ", 1)[1]
    if token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
```

- [ ] **Step 14.4: Create `src/routes/register.py`**

```python
"""POST /api/services and DELETE /api/services/{name}."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from platform_sdk.registry import RegistrationRequest

from ._auth import require_api_key

register_router = APIRouter()


@register_router.post("/api/services", dependencies=[Depends(require_api_key)])
async def register(request: Request, body: RegistrationRequest):
    store = request.app.state.store
    await store.register(
        body.name, url=str(body.url), type_=body.type,
        version=body.version, metadata=body.metadata,
    )
    row = await store.get(body.name)
    return row


@register_router.delete(
    "/api/services/{name}",
    dependencies=[Depends(require_api_key)],
    status_code=status.HTTP_204_NO_CONTENT,
)
async def deregister(name: str, request: Request):
    await request.app.state.store.deregister(name)
    return Response(status_code=204)
```

- [ ] **Step 14.5: Create `src/routes/heartbeat.py`**

```python
"""POST /api/services/{name}/heartbeat."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ._auth import require_api_key

heartbeat_router = APIRouter()


@heartbeat_router.post(
    "/api/services/{name}/heartbeat",
    dependencies=[Depends(require_api_key)],
)
async def heartbeat(name: str, request: Request):
    bumped = await request.app.state.store.heartbeat(name)
    if not bumped:
        raise HTTPException(status_code=404, detail=f"Service not registered: {name}")
    return {"ok": True}
```

- [ ] **Step 14.6: Run + commit**

```bash
.venv/bin/pytest tests/unit/test_routes_register.py tests/unit/test_routes_heartbeat.py -v
git add src/routes/ tests/unit/test_routes_register.py tests/unit/test_routes_heartbeat.py
git commit -m "feat(registry): write routes — register / deregister / heartbeat (auth-gated)

Reads expected key from app.state.api_key (set by RegistryApp.lifespan).
Pydantic-validates the registration body via platform_sdk.registry.RegistrationRequest.
DELETE returns 204; heartbeat 404 when name is not currently registered."
```

---

### Task 15: Read routes (lookup + health) + UI

**Files:**
- Create: `src/routes/lookup.py`
- Create: `src/routes/health.py`
- Create: `src/routes/ui.py`
- Create: `src/ui/index.html`
- Create: `tests/unit/test_routes_lookup.py`
- Create: `tests/unit/test_routes_health.py`

- [ ] **Step 15.1: Write failing tests**

Create `tests/unit/test_routes_lookup.py`:

```python
"""Tests for the read endpoints (no auth required)."""
from __future__ import annotations

import asyncio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


@pytest.fixture
def client(tmp_path):
    from src.routes.lookup import lookup_router
    from src.store import SqliteStore
    store = SqliteStore(tmp_path / "r.db")
    asyncio.get_event_loop().run_until_complete(store.init_schema())
    asyncio.get_event_loop().run_until_complete(
        store.register("ai-mcp-data", url="http://data-mcp:8080", type_="mcp", version="0.5.0")
    )
    app = FastAPI()
    app.state.store = store
    app.include_router(lookup_router)
    return TestClient(app)


def test_get_services_returns_list(client):
    r = client.get("/api/services")
    assert r.status_code == 200
    assert "services" in r.json()
    names = [s["name"] for s in r.json()["services"]]
    assert "ai-mcp-data" in names


def test_get_service_by_name_returns_entry(client):
    r = client.get("/api/services/ai-mcp-data")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "ai-mcp-data"
    assert body["state"] == "registered"


def test_get_unknown_returns_404(client):
    r = client.get("/api/services/missing")
    assert r.status_code == 404


def test_read_endpoints_unauthenticated(client):
    """Read endpoints do not require Authorization."""
    r = client.get("/api/services")
    assert r.status_code == 200
```

Create `tests/unit/test_routes_health.py`:

```python
"""Tests for GET /health."""
from __future__ import annotations

import asyncio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


def test_health_reports_db_reachable(tmp_path):
    from src.routes.health import health_router
    from src.store import SqliteStore
    store = SqliteStore(tmp_path / "r.db")
    asyncio.get_event_loop().run_until_complete(store.init_schema())
    app = FastAPI()
    app.state.store = store
    app.include_router(health_router)
    c = TestClient(app)
    r = c.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "degraded")
    assert "db_ok" in body
```

- [ ] **Step 15.2: Create `src/routes/lookup.py`**

```python
"""GET /api/services and /api/services/{name} — unauthenticated reads."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

lookup_router = APIRouter()


@lookup_router.get("/api/services")
async def list_services(request: Request):
    rows = await request.app.state.store.list_all()
    return {"services": rows}


@lookup_router.get("/api/services/{name}")
async def get_service(name: str, request: Request):
    row = await request.app.state.store.get(name)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Service not found: {name}")
    return row
```

- [ ] **Step 15.3: Create `src/routes/health.py`**

```python
"""Registry's own /health endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Request

health_router = APIRouter()


@health_router.get("/health")
async def health(request: Request):
    store = request.app.state.store
    try:
        await store.list_all()
        db_ok = True
    except Exception:
        db_ok = False
    reaper_ok = getattr(request.app.state, "reaper_task", None) is not None
    status_str = "ok" if (db_ok and reaper_ok) else "degraded"
    return {"status": status_str, "db_ok": db_ok, "reaper_ok": reaper_ok}
```

- [ ] **Step 15.4: Create `src/routes/ui.py`**

```python
"""GET / — serve the read-only HTML catalog."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

ui_router = APIRouter()
_INDEX = Path(__file__).parent.parent / "ui" / "index.html"


@ui_router.get("/", response_class=HTMLResponse)
async def index():
    return _INDEX.read_text()
```

- [ ] **Step 15.5: Create `src/ui/index.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>ai-registry</title>
  <style>
    body { font: 14px -apple-system, system-ui, sans-serif; padding: 20px; max-width: 1100px; margin: auto; }
    h1 { font-size: 18px; margin: 0 0 16px; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 8px 12px; border-bottom: 1px solid #eee; text-align: left; vertical-align: top; }
    th { font-weight: 600; background: #fafafa; }
    .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
    .badge.registered { background: #d4edda; color: #155724; }
    .badge.stale { background: #fff3cd; color: #856404; }
    .badge.expected_unregistered { background: #f8d7da; color: #721c24; }
    .meta { color: #666; font-size: 12px; }
    .url { font-family: ui-monospace, monospace; }
  </style>
</head>
<body>
  <h1>ai-registry — service catalog</h1>
  <div class="meta">Auto-refreshing every 5s. Read-only.</div>
  <table>
    <thead>
      <tr>
        <th>Name</th><th>Type</th><th>State</th><th>URL</th><th>Version</th>
        <th>Last heartbeat</th><th>Metadata</th>
      </tr>
    </thead>
    <tbody id="rows"></tbody>
  </table>

  <script>
  function relTime(iso) {
    if (!iso) return "—";
    const ageSec = (new Date() - new Date(iso)) / 1000;
    if (ageSec < 60) return Math.round(ageSec) + "s ago";
    if (ageSec < 3600) return Math.round(ageSec / 60) + "m ago";
    return Math.round(ageSec / 3600) + "h ago";
  }
  async function load() {
    const r = await fetch("/api/services");
    const body = await r.json();
    const rows = body.services || [];
    document.getElementById("rows").innerHTML = rows.map(s => `
      <tr>
        <td><strong>${s.name}</strong></td>
        <td>${s.type}</td>
        <td><span class="badge ${s.state}">${s.state}</span></td>
        <td class="url">${s.url || s.expected_url || "—"}</td>
        <td>${s.version || "—"}</td>
        <td>${relTime(s.last_heartbeat_at)}</td>
        <td class="meta"><code>${JSON.stringify(s.metadata || {})}</code></td>
      </tr>
    `).join("");
  }
  load();
  setInterval(load, 5000);
  </script>
</body>
</html>
```

- [ ] **Step 15.6: Run tests + commit**

```bash
.venv/bin/pytest tests/unit/test_routes_lookup.py tests/unit/test_routes_health.py -v
git add src/routes/ src/ui/ tests/unit/
git commit -m "feat(registry): read routes (lookup + health) + read-only HTML UI

GET /api/services and /api/services/{name} are unauthenticated by design
(internal-network discovery). GET /health reports db + reaper status.
GET / serves a single index.html with vanilla JS that fetches the catalog
every 5s — no frontend build required."
```

---

### Task 16: `RegistryApp(BaseAgentApp)` wiring + component smoke test

**Files:**
- Modify: `src/app.py` (replace scaffolder placeholder)
- Create: `tests/component/__init__.py`
- Create: `tests/component/test_registry_app_lifecycle.py`

- [ ] **Step 16.1: Replace `src/app.py`**

```python
"""ai-registry — service catalog + health-aware lookup.

Subclasses BaseAgentApp so we get the same lifecycle wiring (logging, telemetry,
graceful shutdown, optional auto-registration). RegistryApp does NOT register
itself with itself — Application._register checks REGISTRY_URL == SERVICE_URL
and skips.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from platform_sdk import BaseAgentApp

from .config import RegistryConfig
from .config_loader import ConfigLoader
from .reaper import reaper_loop
from .routes.health import health_router
from .routes.heartbeat import heartbeat_router
from .routes.lookup import lookup_router
from .routes.register import register_router
from .routes.ui import ui_router
from .store import SqliteStore


@dataclass
class RegistryDeps:
    store: SqliteStore
    config: RegistryConfig


class RegistryApp(BaseAgentApp):
    service_name = "ai-registry"
    service_title = "ai-registry"
    service_description = "Enterprise AI Platform — service catalog, health, discovery"
    service_type = "registry"
    enable_telemetry = True
    requires_checkpointer = False
    requires_conversation_store = False

    def load_config(self, name: str | None = None):
        return RegistryConfig.from_env()

    def routes(self):
        # Order: UI router last so /api/* take precedence (defensive — FastAPI matches
        # by route definition not order, but consistent ordering helps readers).
        return [register_router, heartbeat_router, lookup_router, health_router, ui_router]

    def build_dependencies(self, *, bridges, checkpointer, store):
        cfg: RegistryConfig = self.config
        return RegistryDeps(store=SqliteStore(cfg.sqlite_path), config=cfg)

    async def on_started(self, deps: RegistryDeps, *, bridges, config, checkpointer, store):
        # Make config / store available to route handlers via app.state
        from fastapi import FastAPI
        app: FastAPI = self._app  # set in create_app override below

        await deps.store.init_schema()
        seed = ConfigLoader(seed_path=deps.config.seed_path).load()
        await deps.store.apply_seed(seed)

        app.state.store = deps.store
        app.state.api_key = deps.config.internal_api_key
        app.state.reaper_task = asyncio.create_task(reaper_loop(deps.store, deps.config))

    async def on_shutdown(self, deps: RegistryDeps):
        from fastapi import FastAPI
        app: FastAPI = self._app
        task = getattr(app.state, "reaper_task", None)
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            app.state.reaper_task = None

    def create_app(self, deps=None):
        # Capture the FastAPI instance so on_started can write to app.state
        app = super().create_app(deps=deps)
        self._app = app
        return app


_registry = RegistryApp()
app = _registry.create_app()
```

- [ ] **Step 16.2: Write component-level smoke test**

Create `tests/component/test_registry_app_lifecycle.py`:

```python
"""Component-level smoke test — full RegistryApp lifecycle in-process."""
from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.component


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "test-key")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "r.db"))
    monkeypatch.setenv("REGISTRY_PORT", "8090")
    monkeypatch.setenv("ENABLE_TELEMETRY", "false")
    monkeypatch.delenv("REGISTRY_URL", raising=False)  # prevent self-registration loop
    monkeypatch.delenv("SEED_PATH", raising=False)

    # Re-import the app module so RegistryConfig.from_env() picks up our env
    import importlib
    import src.app as app_mod
    importlib.reload(app_mod)
    return app_mod.app


def test_full_register_heartbeat_lookup_deregister(app):
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer test-key"}

        # 1. List is empty (no seed)
        r = client.get("/api/services")
        assert r.status_code == 200
        assert r.json()["services"] == []

        # 2. Register
        r = client.post("/api/services", headers=headers, json={
            "name": "ai-mcp-data", "url": "http://data-mcp:8080", "type": "mcp",
        })
        assert r.status_code == 200

        # 3. Lookup
        r = client.get("/api/services/ai-mcp-data")
        assert r.status_code == 200
        assert r.json()["state"] == "registered"

        # 4. Heartbeat
        r = client.post("/api/services/ai-mcp-data/heartbeat", headers=headers)
        assert r.status_code == 200

        # 5. Health
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["db_ok"] is True

        # 6. UI returns HTML
        r = client.get("/")
        assert r.status_code == 200
        assert "ai-registry" in r.text

        # 7. Deregister
        r = client.delete("/api/services/ai-mcp-data", headers=headers)
        assert r.status_code == 204

        r = client.get("/api/services/ai-mcp-data")
        assert r.status_code == 404
```

- [ ] **Step 16.3: Run tests**

```bash
.venv/bin/pytest tests/component -v
```
Expected: 1 passed.

- [ ] **Step 16.4: Run full unit + component suite**

```bash
.venv/bin/pytest tests -v
```
Expected: ~30+ tests, all green.

- [ ] **Step 16.5: Commit**

```bash
git add src/app.py tests/component/
git commit -m "feat(registry): RegistryApp(BaseAgentApp) — wires routes, store, reaper

RegistryApp.on_started:
  1. SqliteStore.init_schema()
  2. apply_seed() (idempotent)
  3. publish store + api_key on app.state for route handlers
  4. spawn reaper background task

on_shutdown cancels the reaper. service_type='registry' tells the SDK's
Application._register to skip self-registration when REGISTRY_URL points
at this very service.

Component-level smoke test exercises the full register → heartbeat →
lookup → deregister cycle in-process via TestClient."
```

---

### Task 17: CI + release workflows; first push, branch, tag, image publish

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/release.yml`
- Create: `README.md` (replace scaffolder default)
- Create: `CHANGELOG.md`

- [ ] **Step 17.1: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main, "release/*"]
  pull_request:

jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies (rewrite SDK pin to https for CI)
        run: |
          sed 's|git+ssh://git@github.com/|git+https://github.com/|g' requirements.txt > /tmp/requirements-ci.txt
          pip install -r /tmp/requirements-ci.txt
          pip install -r requirements-runtime.txt
          pip install pytest pytest-asyncio
      - name: Run tests
        run: pytest tests -v
```

- [ ] **Step 17.2: Create `.github/workflows/release.yml`**

```yaml
name: Release

on:
  push:
    tags:
      - 'v*.*.*'

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      - name: Extract version
        id: ver
        run: echo "v=${GITHUB_REF_NAME#v}" >> "$GITHUB_OUTPUT"
      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Build & push
        uses: docker/build-push-action@v5
        with:
          context: .
          file: Dockerfile
          push: true
          tags: |
            ghcr.io/narisun/ai-registry:${{ steps.ver.outputs.v }}
            ghcr.io/narisun/ai-registry:latest
          labels: |
            org.opencontainers.image.version=${{ steps.ver.outputs.v }}
            org.opencontainers.image.revision=${{ github.sha }}
            org.opencontainers.image.created=${{ github.event.head_commit.timestamp }}
```

- [ ] **Step 17.3: Replace `README.md`**

```markdown
# ai-registry

Enterprise AI Platform — service catalog, health monitoring, and name-based discovery for the platform's runtime services. Every agent and MCP server self-registers on startup; this service is the single bootstrap URL the rest of the platform uses to find peers.

## Quick start

```bash
pip install -r requirements.txt
INTERNAL_API_KEY=$(openssl rand -hex 32) uvicorn src.app:app --host 0.0.0.0 --port 8090
```

Open the read-only catalog UI at http://localhost:8090.

## Configuration (env vars)

| Var | Default | Purpose |
|---|---|---|
| `REGISTRY_PORT` | `8090` | Listen port |
| `INTERNAL_API_KEY` | (required) | Bearer token required for write ops |
| `SQLITE_PATH` | `/var/lib/registry/registry.db` | SQLite file path |
| `SEED_PATH` | (unset) | Optional `registry.yaml` seed |
| `HEARTBEAT_GRACE_SECONDS` | `60` | Time before heartbeat-less services go `stale` |
| `EVICTION_SECONDS` | `300` | Time before stale services are evicted |
| `REAPER_INTERVAL_SECONDS` | `30` | How often the reaper runs |

## Endpoints

- `GET /api/services` — list catalog (no auth)
- `GET /api/services/{name}` — single entry (no auth)
- `POST /api/services` — register (Bearer auth)
- `DELETE /api/services/{name}` — deregister (Bearer auth)
- `POST /api/services/{name}/heartbeat` — heartbeat (Bearer auth)
- `GET /health` — registry's own liveness (no auth)
- `GET /` — read-only catalog UI

## Container

```bash
docker pull ghcr.io/narisun/ai-registry:0.5.0
docker run --rm -p 8090:8090 \
  -e INTERNAL_API_KEY=secret \
  -v ai-registry-data:/var/lib/registry \
  ghcr.io/narisun/ai-registry:0.5.0
```

## See also

- Spec: [`docs/specs/2026-04-30-service-registry-design.md` in narisun/ai-platform-sdk](https://github.com/narisun/ai-platform-sdk/blob/main/docs/specs/2026-04-30-service-registry-design.md)
- Client API: `platform_sdk.registry.RegistryClient` (in narisun/ai-platform-sdk)
```

- [ ] **Step 17.4: Create `CHANGELOG.md`**

```markdown
# Changelog

## 0.5.0 — 2026-04-30

Initial release. Registry server + read-only HTML UI. Hybrid model:
optional YAML seed declares "expected" services; live registrations
happen via POST /api/services on each component's startup.

Built against `enterprise-ai-platform-sdk` 0.5.0 + the
`ghcr.io/narisun/ai-python-base:3.11-sdk0.5.0` base image.
```

- [ ] **Step 17.5: Create the GitHub repo and push**

```bash
gh repo create narisun/ai-registry --public \
  --description "Enterprise AI Platform — service registry (catalog + health + discovery)"
git remote add origin git@github.com:narisun/ai-registry.git
git add -A
git commit -m "chore: add CI + release workflows + README + CHANGELOG"
git push -u origin main
```

If the gh OAuth token lacks the `workflow` scope (the same issue we hit during the multi-repo carve-out), the push fails with "refusing to allow an OAuth App to create or update workflow". Recovery is the same pattern: switch the remote to SSH (`git@github.com:...`) and push via the SSH key. The `gh repo create` step still works because it doesn't push files.

- [ ] **Step 17.6: Cut release branch and tag**

```bash
git checkout -b release/0.5
git push -u origin release/0.5
git tag -a v0.5.0 -m "Release 0.5.0 — initial registry"
git push origin v0.5.0
```

- [ ] **Step 17.7: Verify the workflow succeeded**

```bash
sleep 10
gh run list --repo narisun/ai-registry --limit 5
gh run watch --repo narisun/ai-registry
```

After success:

```bash
docker pull ghcr.io/narisun/ai-registry:0.5.0
docker images ghcr.io/narisun/ai-registry
```

Confirm the image is pullable.

---

## Phase 3 — `narisun/ai-dev-stack` integration

### Task 18: Add `ai-registry` to compose; inject `REGISTRY_URL` everywhere; add seed file

**Files:**
- Modify: `docker-compose.yml`
- Create: `config/registry.yaml`
- Create: `tests/integration/test_registry_e2e.py`
- Modify: `.github/workflows/e2e.yml` (or whatever the existing E2E workflow is called) to validate registry liveness

- [ ] **Step 18.1: Clone the dev-stack repo**

```bash
cd /Users/admin-h26/carve-out
rm -rf ai-dev-stack
git clone git@github.com:narisun/ai-dev-stack.git
cd ai-dev-stack
git checkout -b feature/registry
```

- [ ] **Step 18.2: Add the `ai-registry` service block to `docker-compose.yml`**

Insert this block alongside the other services (place it BEFORE the agent and MCP services so the dependency graph is honest — agents implicitly depend on the registry):

```yaml
  ai-registry:
    image: ghcr.io/narisun/ai-registry:0.5.0
    container_name: ai-registry
    ports:
      - "127.0.0.1:8090:8090"
    environment:
      REGISTRY_PORT: 8090
      INTERNAL_API_KEY: ${INTERNAL_API_KEY}
      SQLITE_PATH: /var/lib/registry/registry.db
      SEED_PATH: /etc/registry/registry.yaml
      HEARTBEAT_GRACE_SECONDS: "60"
      EVICTION_SECONDS: "300"
      REAPER_INTERVAL_SECONDS: "30"
    volumes:
      - ai-registry-data:/var/lib/registry
      - ./config/registry.yaml:/etc/registry/registry.yaml:ro
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8090/health"]
      interval: 10s
      timeout: 3s
      start_period: 10s
      retries: 3
    restart: unless-stopped
```

Add the named volume to the file's `volumes:` section at the bottom:

```yaml
volumes:
  ai-registry-data:
  # ... existing volumes ...
```

- [ ] **Step 18.3: Inject `REGISTRY_URL` and `SERVICE_URL` into every service**

For each service block (analytics-agent, data-mcp, salesforce-mcp, payments-mcp, news-search-mcp), add to its `environment:`:

```yaml
      REGISTRY_URL: http://ai-registry:8090
      SERVICE_URL: http://<container_name>:<container_port>   # e.g., http://analytics-agent:8000
      INTERNAL_API_KEY: ${INTERNAL_API_KEY}                   # if not already set
```

For each service, also add `depends_on: { ai-registry: { condition: service_healthy } }` so the registry comes up first. (If your existing compose uses the simple `depends_on: [list]` form, switch the affected entries to the long form.)

- [ ] **Step 18.4: Create `config/registry.yaml`**

```yaml
# config/registry.yaml — seed entries declaring the services this stack expects.
# Services that have NOT registered themselves (POST /api/services on startup)
# show as state='expected_unregistered' in the catalog UI — useful ops alert.
services:
  - name: ai-agent-analytics
    type: agent
    expected_url: http://analytics-agent:8000
    metadata:
      owner: analytics-team
  - name: ai-mcp-data
    type: mcp
    expected_url: http://data-mcp:8080
  - name: ai-mcp-salesforce
    type: mcp
    expected_url: http://salesforce-mcp:8081
  - name: ai-mcp-payments
    type: mcp
    expected_url: http://payments-mcp:8082
  - name: ai-mcp-news-search
    type: mcp
    expected_url: http://news-search-mcp:8083
```

- [ ] **Step 18.5: Add an integration test**

Create `tests/integration/test_registry_e2e.py`:

```python
"""E2E test — verifies all expected services register against the live registry."""
from __future__ import annotations

import os
import time

import httpx
import pytest

pytestmark = pytest.mark.integration


REGISTRY_URL = os.environ.get("REGISTRY_URL", "http://localhost:8090")


def _wait_for(predicate, timeout: float = 30.0, interval: float = 1.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("timeout")


def test_registry_sees_all_seeded_services():
    expected = {
        "ai-agent-analytics", "ai-mcp-data", "ai-mcp-salesforce",
        "ai-mcp-payments", "ai-mcp-news-search",
    }

    def _all_registered() -> bool:
        r = httpx.get(f"{REGISTRY_URL}/api/services", timeout=5)
        if r.status_code != 200:
            return False
        registered = {s["name"] for s in r.json().get("services", [])
                      if s["state"] == "registered"}
        return expected.issubset(registered)

    _wait_for(_all_registered, timeout=60.0)


def test_registry_health_endpoint():
    r = httpx.get(f"{REGISTRY_URL}/health", timeout=5)
    assert r.status_code == 200
    body = r.json()
    assert body["db_ok"] is True
```

- [ ] **Step 18.6: Update the E2E workflow**

Find `.github/workflows/e2e.yml`. Add a step before the integration tests run:

```yaml
      - name: Wait for registry
        run: |
          for i in {1..30}; do
            if curl -fsS http://localhost:8090/health > /dev/null; then break; fi
            sleep 2
          done
```

The integration test step is already in place from earlier work — just make sure it picks up `tests/integration/test_registry_e2e.py`.

- [ ] **Step 18.7: Smoke locally with `make setup`**

```bash
make setup    # bring up everything including the new ai-registry
docker compose ps
curl -s http://localhost:8090/api/services | jq .
```

Expected: 6+ services in the catalog (5 from the seed + the registry itself if it ever registered, but it's seeded as expected_unregistered for self → confirm it shows so). All 5 platform services should transition to `state=registered` within ~30s of `make setup` completing.

- [ ] **Step 18.8: Commit, push, tag**

```bash
git add docker-compose.yml config/registry.yaml tests/integration/test_registry_e2e.py .github/workflows/
git commit -m "feat(dev-stack): add ai-registry service + REGISTRY_URL injection

- ai-registry @ ghcr.io/narisun/ai-registry:0.5.0 in compose; bind-mounts
  config/registry.yaml as the seed file; persists SQLite to a named volume.
- Every existing service gains REGISTRY_URL and SERVICE_URL env vars;
  depends_on: { ai-registry: { condition: service_healthy } } so the
  registry is up before consumers boot.
- config/registry.yaml seeds the 5 platform services (analytics-agent + 4 MCPs).
- New integration test verifies all 5 transition to state=registered within 60s
  of the compose stack coming up."
git push -u origin feature/registry
gh pr create --title "feat: integrate ai-registry into dev-stack" \
  --body "Implements Task 18 of docs/plans/2026-04-30-service-registry.md"
# After merge:
git checkout main && git pull
git checkout -b release/0.5 && git push -u origin release/0.5
git tag -a v0.5.0 -m "Release 0.5.0 — registry-aware orchestration"
git push origin v0.5.0
```

---

## Phase 4 — Per-service SDK bumps + analytics-agent migration

### Task 19: Bump SDK pin in 5 service repos (mechanical, sequential)

**Files** (per repo):
- Modify: `requirements.txt` (SDK pin)
- Modify: `Dockerfile` (BASE_TAG)

The repos are: `narisun/ai-agent-analytics`, `narisun/ai-mcp-data`, `narisun/ai-mcp-salesforce`, `narisun/ai-mcp-payments`, `narisun/ai-mcp-news-search`. Same pattern in each.

- [ ] **Step 19.1: Per-repo pattern (run for each of the 5 repos)**

```bash
cd /Users/admin-h26/carve-out
for repo in ai-agent-analytics ai-mcp-data ai-mcp-salesforce ai-mcp-payments ai-mcp-news-search; do
  rm -rf "$repo"
  git clone "git@github.com:narisun/$repo.git"
  cd "$repo"
  git checkout -b feature/sdk-0.5.0

  # Bump SDK pin in requirements.txt
  sed -i.bak 's|@v0.4.0|@v0.5.0|g' requirements.txt && rm -f requirements.txt.bak
  # Bump base image tag in Dockerfile
  sed -i.bak 's|3.11-sdk0.4.0|3.11-sdk0.5.0|g' Dockerfile && rm -f Dockerfile.bak

  # Verify exactly one diff per file
  git diff requirements.txt Dockerfile

  git add requirements.txt Dockerfile
  git commit -m "chore: bump SDK to 0.5.0; base image to 3.11-sdk0.5.0

The platform service registry (Application._register hooks) lands in
0.5.0 as additive behavior — this service self-registers on startup
when REGISTRY_URL is set in the environment. mcp_servers (if used)
still works with a DeprecationWarning until 0.6.0."
  git push -u origin feature/sdk-0.5.0
  gh pr create --title "chore: bump SDK to 0.5.0" --body "Mechanical bump. Self-registration via Application._register starts working when REGISTRY_URL is set."
  cd ..
done
```

- [ ] **Step 19.2: Merge each PR after CI passes; tag each repo**

For each repo, after the PR merges:

```bash
cd /Users/admin-h26/carve-out/<repo>
git checkout main && git pull
git checkout -b release/0.5 && git push -u origin release/0.5
git tag -a v0.5.0 -m "Release 0.5.0 — SDK 0.5.0; service self-registration via Application hooks"
git push origin v0.5.0
```

Each tag triggers the per-repo release workflow, which builds and pushes `ghcr.io/narisun/<repo>:0.5.0`.

- [ ] **Step 19.3: Bump compose pins in `ai-dev-stack`**

After all 5 service images are published, edit `ai-dev-stack/docker-compose.yml` to change each `image:` from `:0.4.0` to `:0.5.0`. Open a small PR (e.g., `chore(compose): pin services to 0.5.0`), merge, tag `ai-dev-stack` v0.5.1.

- [ ] **Step 19.4: Smoke `make setup`**

```bash
cd /Users/admin-h26/carve-out/ai-dev-stack
git pull
make stop && make setup
sleep 60
curl -s http://localhost:8090/api/services | jq '.services[] | {name, state, last_heartbeat_at}'
```

Expected: every one of the 5 platform services shows `state: "registered"` and a recent `last_heartbeat_at` (within the last 30 s). Open http://localhost:8090 in a browser to see the catalog UI.

If a service shows `state: "expected_unregistered"` (and has had >60s to register), check that service's container logs for `registry_register_failed` warnings.

---

### Task 20: Migrate `ai-agent-analytics` from `mcp_servers` to `mcp_dependencies`

The first agent to actually consume the registry for URL resolution. Easy to revert — flip back to `mcp_servers` if it misbehaves; SDK version is unaffected.

**Files:**
- Modify: `narisun/ai-agent-analytics/src/app.py`

- [ ] **Step 20.1: Pull and branch**

```bash
cd /Users/admin-h26/carve-out/ai-agent-analytics
git checkout main && git pull
git checkout -b feature/registry-driven-mcp
```

- [ ] **Step 20.2: Replace the `mcp_servers` dict with `mcp_dependencies`**

In `src/app.py`, find the class body (today):

```python
class AnalyticsAgentApp(BaseAgentApp):
    service_name = "ai-agent-analytics"
    mcp_servers = {
        "data-mcp":          os.getenv("DATA_MCP_URL", "http://data-mcp:8000/sse"),
        "salesforce-mcp":    os.getenv("SALESFORCE_MCP_URL", "http://salesforce-mcp:8000/sse"),
        "payments-mcp":      os.getenv("PAYMENTS_MCP_URL", "http://payments-mcp:8000/sse"),
        "news-search-mcp":   os.getenv("NEWS_SEARCH_MCP_URL", "http://news-search-mcp:8000/sse"),
    }
    # ... rest of class ...
```

Replace with:

```python
class AnalyticsAgentApp(BaseAgentApp):
    service_name = "ai-agent-analytics"
    mcp_dependencies = [
        "ai-mcp-data",
        "ai-mcp-salesforce",
        "ai-mcp-payments",
        "ai-mcp-news-search",
    ]
    # ... rest of class unchanged ...
```

(Note: the names match the seed YAML in `ai-dev-stack/config/registry.yaml`. The base class translates each name → registry lookup → URL + /sse path.)

If the class still references the OLD logical names (e.g., `bridges["data-mcp"]` somewhere), update those references to the new names (`bridges["ai-mcp-data"]`). Search and replace:

```bash
grep -rn "bridges\[\"data-mcp\"\]\|bridges\[\"salesforce-mcp\"\]\|bridges\[\"payments-mcp\"\]\|bridges\[\"news-search-mcp\"\]" src/
# For each hit, change the name to the registry-canonical form (ai-mcp-...).
```

- [ ] **Step 20.3: Update tests if they reference logical names**

```bash
grep -rn "data-mcp\|salesforce-mcp\|payments-mcp\|news-search-mcp" tests/ | grep -v "/integration/"
# Some tests may use these names as keys; update to ai-mcp-* form.
```

For test fakes that simulate the registry, the `fake_registry` fixture from the SDK accepts any name; just `seed()` the names you want.

- [ ] **Step 20.4: Run tests**

```bash
.venv/bin/pytest tests -m "not integration" -v
```

Expected: same passing count as before. The XFAILed tests (the 3 pre-existing baseline failures from earlier work) stay XFAIL.

- [ ] **Step 20.5: Smoke against the live dev-stack**

```bash
cd /Users/admin-h26/carve-out/ai-dev-stack
make restart
sleep 30
# Check that analytics-agent connected its bridges via the registry:
docker compose logs analytics-agent | grep -E "mcp_connecting_all|mcp_startup_status"
# Should show servers=['ai-mcp-data','ai-mcp-salesforce','ai-mcp-payments','ai-mcp-news-search']
# And state=connected for each.
```

If any bridge fails to connect, check the registry's UI (http://localhost:8090) — that MCP probably isn't `state: registered`.

- [ ] **Step 20.6: Commit, PR, tag**

```bash
cd /Users/admin-h26/carve-out/ai-agent-analytics
git add src/ tests/
git commit -m "feat(analytics-agent): resolve MCP URLs via the registry

Replaces the hardcoded mcp_servers dict with mcp_dependencies (list of
registry names). The base class (BaseAgentApp._connect_bridges) calls
self.registry.lookup(name) for each entry and skips entries whose state
is not 'registered'. Bridge URL is the entry's url + /sse.

Net effect: deploying a renamed or relocated MCP requires no change in
this repo — update registry.yaml in dev-stack and the new URL is picked
up on the next refresh tick (within ~30s)."
git push -u origin feature/registry-driven-mcp
gh pr create --title "feat: resolve MCP URLs via registry (drops mcp_servers dict)" \
  --body "Implements Task 20 of the service registry plan. Reversible — if anything misbehaves, flip back to mcp_servers without an SDK release."
# After merge:
git checkout main && git pull
git checkout release/0.5
git pull origin release/0.5
git cherry-pick <merge-sha-from-main>
git push origin release/0.5
git tag -a v0.5.1 -m "Release 0.5.1 — registry-driven MCP discovery"
git push origin v0.5.1
```

The release workflow builds and pushes `ghcr.io/narisun/ai-agent-analytics:0.5.1`. Bump the dev-stack compose pin to `:0.5.1` in a follow-up PR.

---

## Self-Review Checklist

Run through these before starting implementation.

| Item | Confirmed? |
|---|---|
| Spec coverage: every section of `docs/specs/2026-04-30-service-registry-design.md` maps to a task. | ✅ Architecture → Tasks 1–17. Hybrid model → Tasks 11 (loader) + 18 (seed). Soft-fail with stale cache → Task 2. Active polling on registry → Task 13. Periodic client refresh → Task 3. UI → Task 15. Auth → Task 14 (`_auth.py`). Threat model (`service_url_changed`) → emitted by store on URL change (covered in Task 12 by the warning log on URL update). Persistence + restart behavior → Task 12 + Task 16 (init_schema runs every startup; SQLite reopens stale rows). Reaper transitions → Task 13. Migration sequence → Tasks 9 + 17 + 18 + 19 + 20 (each phase). |
| Placeholder scan: no "TBD" / "TODO" / "implement later" anywhere. | ✅ |
| Type consistency: `RegistryEntry` / `RegistrationRequest` field names match between client (Task 1), server routes (Tasks 14–15), store (Task 12), and reaper (Task 13). | ✅ Fields: `name`, `url`, `expected_url`, `type`, `state`, `version`, `metadata`, `last_heartbeat_at`, `registered_at`, `last_changed_at`. |
| `mcp_servers` deprecation path: not removed in 0.5.0 (Task 7 keeps it as a `DeprecationWarning`); removal scheduled for 0.6.0 (mentioned in CHANGELOG, not part of this plan). | ✅ |
| Failure-recovery for each phase is documented and reversible. | ✅ Phase 1 (SDK additive only). Phase 2 (new repo, no consumers yet). Phase 3 (compose change; revert by removing the service block). Phase 4 SDK bump (revert pin). Phase 4 mcp_dependencies migration (revert one file). |
| The registry never registers with itself — `_register` short-circuits when `REGISTRY_URL == SERVICE_URL` (Task 4). | ✅ |
| Test coverage: every new code path has at least one failing test before implementation (TDD per the writing-plans skill). | ✅ |
| `BaseAgentApp` extends `Application` so the `_register` / `_deregister` hooks are reachable (added in Task 5). | ✅ |
| The `gh repo create` + SSH-push workaround (from the multi-repo carve-out) is referenced in Task 17. | ✅ |
| Integration test (Task 18) requires the dev-stack live; correctly marked `@pytest.mark.integration`. | ✅ |
| Plan length is comparable to the multi-repo restructure plan (which the user already executed successfully). | ✅ |

---

## Execution Handoff

Plan complete and saved to `narisun/ai-platform-sdk:docs/plans/2026-04-30-service-registry.md`.

Two execution options when ready:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, two-stage review (spec compliance + code quality) between tasks, fast iteration. This is what worked smoothly during the multi-repo restructure.
2. **Inline Execution** — execute tasks in this session via `superpowers:executing-plans`, batched with checkpoints for review.

Which approach when you're ready to start?







