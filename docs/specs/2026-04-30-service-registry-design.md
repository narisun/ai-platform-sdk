# Service Registry — Design Specification

**Date:** 2026-04-30
**Status:** Approved (post-brainstorm); ready for implementation planning.
**Owners:** Platform team.

## Goal

Replace the hardcoded `mcp_servers` dict in every agent (and any future need to know "where is service X?" or "is service Y healthy?") with a single platform-wide registry. Every runtime component (agent, MCP server, future runtime processes) registers itself with the registry on startup, heartbeats periodically, and looks up peers by name. The registry is itself an `Application` subclass — same SDK pattern as every other component.

## Why this exists

The platform today has 7 service repos plus dev-stack orchestration. Each agent declares its MCP dependencies as a Python dict mapping logical names to URLs (`{"data-mcp": "http://data-mcp:8000/sse", ...}`), with per-name `<NAME>_URL` env vars as overrides. This works for one agent talking to a fixed set of MCPs in compose, but it scales poorly:

- Every new MCP requires editing the dict in every consuming agent.
- Renames, port changes, or topology shifts ripple through every service's env vars.
- There's no single inventory of "what's running" or "is it healthy" — each component sees only its own bridges.
- Cloud deployment (Azure/AWS — out of scope today, but planned) needs service discovery.

A registry fixes all of these by being the single source of truth for the platform's runtime topology and health.

## Decisions made during brainstorming

| Question | Choice | Rationale |
|---|---|---|
| What problem does the registry solve? | **E — full registry as platform infrastructure** | User wants a permanent component, not a tactical fix. |
| Static config or dynamic registration? | **Hybrid — seed config + dynamic self-registration** | YAML seed declares "expected" services; runtime registration captures what's actually running. Useful for ops alerts ("expected service X has not registered"). |
| Health-check & refresh model? | **C — active polling on registry side + periodic refresh on clients** | Clients cache + refresh every 30s; registry tracks heartbeats. Topology changes propagate within ~30s without per-call latency cost. |
| Failure mode when registry is unreachable from a client? | **B — soft fail with stale cache** | Stale cache up to 5 minutes; beyond that, calls fail. Treats registry as proper infrastructure without making it a fragile single point of failure. Aligns with existing graceful-degradation patterns. |
| UI scope? | **A — read-only catalog** | List + detail + health badges. Mirrors the public registry.modelcontextprotocol.io pattern. Mutating UI deferred to v2. |
| Where does the server live as a repo? | **New `narisun/ai-registry` repo** | Matches the established multi-repo pattern. Independent versioning. Image at `ghcr.io/narisun/ai-registry`. |

## Architecture

### Repo layout (post-implementation)

```
narisun/ai-registry                       NEW — the registry server
├── src/
│   ├── app.py                            RegistryApp(BaseAgentApp)
│   ├── routes/
│   │   ├── register.py                   POST   /api/services
│   │   │                                 DELETE /api/services/{name}
│   │   ├── heartbeat.py                  POST   /api/services/{name}/heartbeat
│   │   ├── lookup.py                     GET    /api/services
│   │   │                                 GET    /api/services/{name}
│   │   ├── health.py                     GET    /health
│   │   └── _auth.py                      INTERNAL_API_KEY guard for write ops
│   ├── store/
│   │   ├── sqlite_store.py               SQLite (aiosqlite) — file-backed in volume
│   │   └── models.py                     RegistryEntry ORM + Pydantic
│   ├── reaper.py                         background asyncio task; staleness handler
│   ├── config_loader.py                  YAML → list[SeededEntry]
│   └── ui/index.html                     vanilla HTML+JS read-only catalog
├── config/registry.yaml                  (mounted as a volume in compose)
├── Dockerfile                            FROM ghcr.io/narisun/ai-python-base:3.11-sdk0.5.0
└── (standard CI / release / pyproject scaffolding)

narisun/ai-platform-sdk                   CHANGES (additive in 0.5.0)
└── platform_sdk/
    ├── registry/                         NEW
    │   ├── client.py                     RegistryClient
    │   ├── models.py                     RegistryEntry, RegistrationRequest (shared with server)
    │   └── exceptions.py                 RegistryUnreachable, ServiceNotFound
    ├── base/application.py               Application gains:
    │                                     - service_type: "agent"|"mcp"|"registry"|"other" class attr
    │                                     - service_metadata: dict (subclass override)
    │                                     - _register() / _deregister() lifecycle hooks
    │                                     - heartbeat task management
    └── fastapi_app/base.py               BaseAgentApp:
                                          - mcp_dependencies: list[str] (replaces mcp_servers dict)
                                          - resolves URLs via self.registry.lookup()

narisun/ai-dev-stack                      CHANGES
├── docker-compose.yml                    Adds ai-registry service; injects REGISTRY_URL into all
└── config/registry.yaml                  bind-mounted into ai-registry container

(All 7 existing service repos)            BUMP — pin SDK to 0.5.0; bump base image
                                          to 3.11-sdk0.5.0. Self-registration is automatic
                                          via the Application base class.
```

### Bootstrap chain

```
docker-compose.yml sets:                   every container reads:
  REGISTRY_URL=http://ai-registry:8090     ↳ REGISTRY_URL → bootstraps RegistryClient
  INTERNAL_API_KEY=<shared-secret>         ↳ INTERNAL_API_KEY → for write ops
                                           ↳ ai-registry has SEED_PATH=/etc/registry/registry.yaml
                                              + SQLITE_PATH=/var/lib/registry/registry.db
                                              + REGISTRY_PORT=8090
```

**Every component knows exactly one URL: `REGISTRY_URL`.** The registry knows everyone else either via its YAML seed (declarations) or via dynamic registrations (live state).

## Lifecycle

```
SERVICE STARTUP
  1. Application.startup() reads REGISTRY_URL from env.
  2. Application._register() → POST /api/services
     { name, url, type, version, metadata }
  3. Heartbeat task starts: POST /api/services/{name}/heartbeat every 15s.
  4. Refresh task starts: GET /api/services every 30s, repopulates client cache.

LOOKUP
  Agent boots → RegistryClient.lookup("ai-mcp-data") → cache hit OR
                GET /api/services/ai-mcp-data
  ← { url, type, healthy: true, last_heartbeat: 3s ago, metadata: {...} }
  Cached locally for 30s; refresh task pulls latest.

REGISTRY-SIDE REAPER
  Background task: every 30s.
    - state='registered' AND last_heartbeat > grace_seconds (60s) → state='stale'
    - state='stale' AND last_heartbeat > eviction_seconds (300s):
        if seeded:    state='expected_unregistered', clear url + heartbeat
        else:         DELETE row

GRACEFUL SHUTDOWN
  Application.shutdown() → RegistryClient.deregister() → DELETE /api/services/{name}.
  If process is killed without graceful shutdown, reaper handles cleanup.

UI
  GET / serves index.html. Fetches GET /api/services every 5s. Renders table:
  name, type, state badge, URL, version, last heartbeat, expandable metadata.
```

## Server-side design — `narisun/ai-registry`

### `RegistryApp(BaseAgentApp)`

```python
class RegistryApp(BaseAgentApp):
    service_name = "ai-registry"
    service_type = "registry"
    enable_telemetry = True
    requires_database = False           # uses SQLite via aiosqlite, not asyncpg
    requires_checkpointer = False

    def load_config(self):
        return RegistryConfig.from_env()

    def routes(self):
        return [register_router, heartbeat_router, lookup_router, health_router, ui_router]

    def build_dependencies(self, *, bridges, checkpointer, store):
        store = SqliteStore(self.config.sqlite_path)
        seed = ConfigLoader(self.config.seed_path).load()
        return RegistryDeps(store=store, seed=seed)

    async def on_started(self, deps, *, bridges, config, checkpointer, store):
        await deps.store.init_schema()
        await deps.store.apply_seed(deps.seed)  # idempotent
        self._reaper = asyncio.create_task(reaper_loop(deps.store, config))
```

The registry does **not** register itself — it IS the registry. The SDK client checks `REGISTRY_URL.rstrip("/") == self_url` and skips self-registration in that case.

### `RegistryConfig` (new dataclass)

```python
@dataclass
class RegistryConfig:
    port: int                       = 8090
    sqlite_path: Path               = Path("/var/lib/registry/registry.db")
    seed_path: Path | None          = None
    internal_api_key: str           = ""              # required for write ops
    heartbeat_grace_seconds: int    = 60              # registered → stale
    eviction_seconds: int           = 300             # stale → evicted
    reaper_interval_seconds: int    = 30
    
    @classmethod
    def from_env(cls) -> "RegistryConfig": ...

    def __post_init__(self) -> None:
        # Validate all fields; raise ValueError listing every problem at once.
        # (Same pattern as existing AgentConfig / MCPConfig validation.)
        ...
```

### YAML seed format

```yaml
# config/registry.yaml — declares "expected" services.
# Marked unregistered=true until they POST /api/services on startup.
services:
  - name: ai-agent-analytics
    type: agent
    expected_url: http://analytics-agent:8000
    metadata:
      owner: analytics-team
      version_constraint: ">=0.4.0"
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

`ConfigLoader.load()` returns `list[SeededEntry]`; `store.apply_seed()` upserts rows with `state='expected_unregistered'`. Seed is fully optional — registry works without it (pure dynamic).

### `SqliteStore` schema

```sql
CREATE TABLE IF NOT EXISTS services (
    name              TEXT PRIMARY KEY,
    url               TEXT,
    expected_url      TEXT,
    type              TEXT NOT NULL,
    state             TEXT NOT NULL,
    version           TEXT,
    metadata_json     TEXT,
    last_heartbeat_at TIMESTAMP,
    registered_at     TIMESTAMP,
    last_changed_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_services_state ON services (state);
CREATE INDEX idx_services_type  ON services (type);
```

State values: `registered` | `expected_unregistered` | `stale`. The schema is small and migration-friendly; swap to Postgres later (`aiosqlite` → `asyncpg`) if scale demands it.

### Routes

| Route | Method | Auth | Behavior |
|---|---|---|---|
| `/api/services` | GET | none | List all entries (filter by state/type via query params, future). |
| `/api/services/{name}` | GET | none | Lookup one entry. 404 if unknown. |
| `/api/services` | POST | API key | Register self. Idempotent — upserts by `name`. Logs `service_url_changed` if URL differs from previous registration (impersonation signal). |
| `/api/services/{name}` | DELETE | API key | Graceful deregister. Returns to `expected_unregistered` if seeded; deletes if not. |
| `/api/services/{name}/heartbeat` | POST | API key | Bumps `last_heartbeat_at` and ensures state is `registered`. 404 if not registered. |
| `/health` | GET | none | Registry's own health: SQLite reachable, reaper task alive. |
| `/` | GET | none | UI: read-only HTML catalog. |

Reads are unauthenticated (anyone on the internal network discovers the topology). Writes require `Authorization: Bearer ${INTERNAL_API_KEY}`. Reuses `platform_sdk.security.make_api_key_verifier()`.

### `reaper_loop()`

```
every reaper_interval_seconds (30s):
  for entry in store.entries():
    if state == 'registered' and last_heartbeat < now - grace_seconds (60s):
      transition to 'stale'
    elif state == 'stale' and last_heartbeat < now - eviction_seconds (300s):
      if entry.expected_url is not None:                   # seeded
        transition to 'expected_unregistered'; clear url + heartbeat
      else:                                                # not seeded
        DELETE
```

### UI

A single `index.html` served from `/`. Fetches `GET /api/services` every 5s via vanilla JS. Renders a table:
- columns: name, type, state badge (green=registered, yellow=stale, red=expected_unregistered), URL, version, last heartbeat (relative time), metadata (expandable JSON)
- no frontend build step — keeps the registry repo small
- if the UI grows beyond a single page, it can be carved out to `narisun/ai-frontend-registry` later (out of scope for v1)

## Client-side design — `platform_sdk.registry`

### `RegistryClient`

```python
class RegistryClient:
    """Async client for the ai-registry service.

    Owns:
      - register_self(payload)        POST /api/services
      - start_heartbeat() / stop_heartbeat()
                                      background task; POST /heartbeat every 15s
      - start_refresh() / stop_refresh()
                                      background task; pulls /api/services every 30s
      - lookup(name) -> RegistryEntry cache-first; refreshes on stale;
                                      soft-fails to stale cache on registry outage
      - deregister()                  DELETE /api/services/{self_name}
      - aclose()                      cancels tasks, closes httpx pool
    """

    def __init__(self, *, registry_url: str, api_key: str,
                 heartbeat_seconds: float = 15.0,
                 refresh_seconds: float = 30.0,
                 stale_cache_max_seconds: float = 300.0):
        ...

    async def lookup(self, name: str) -> RegistryEntry:
        cached = self._cache.get(name)
        if cached and cached.fresh:
            return cached.entry
        try:
            entry = await self._fetch(name)
            self._cache[name] = _CacheEntry(entry, fetched_at=now())
            return entry
        except (RegistryUnreachable, httpx.RequestError):
            if cached and cached.age < self._stale_cache_max_seconds:
                log.warning("registry_unreachable_using_stale", name=name, age=cached.age)
                return cached.entry
            raise ServiceNotFound(name)
```

Uses `platform_sdk.resilience.CircuitBreaker` to fail-fast when the registry is known down (saves the per-call timeout cost).

### `Application` lifecycle integration

```python
class Application(ABC):
    name: str
    service_type: ClassVar[str] = "other"           # NEW class attr
    service_metadata: ClassVar[dict] = {}           # NEW class attr

    async def _register(self) -> None:
        registry_url = os.environ.get("REGISTRY_URL")
        if not registry_url:
            log.info("registry_url_not_set", behavior="self-registration disabled")
            return
        if registry_url.rstrip("/") == self._self_url():
            return  # I AM the registry
        self.registry = RegistryClient(
            registry_url=registry_url,
            api_key=os.environ["INTERNAL_API_KEY"],
        )
        await self.registry.register_self({
            "name": self.name,
            "url": self._self_url(),
            "type": self.service_type,
            "version": self._version(),
            "metadata": self.service_metadata,
        })
        await self.registry.start_heartbeat()
        await self.registry.start_refresh()

    async def _deregister(self) -> None:
        if hasattr(self, "registry"):
            await self.registry.deregister()
            await self.registry.aclose()
```

### `BaseAgentApp.lifespan` order (modified)

```
1. configure_logging()
2. setup_telemetry()
3. await self._register()                        ← NEW (additive)
4. await self._connect_bridges(...)              ← uses self.registry.lookup()
5. await self._make_checkpointer(...)
6. await self._make_store()
7. deps = self.build_dependencies(...)
8. app.state.deps = deps
9. await self.on_started(deps, ...)
10. yield (serve traffic)
11. await self.on_shutdown(deps)
12. await self._deregister()                     ← NEW (additive)
13. flush_langfuse() etc.
```

`McpService.lifespan` gains the same `_register` / `_deregister` calls in equivalent positions.

### `BaseAgentApp.mcp_dependencies` replaces `mcp_servers` dict

**Before (today):**

```python
class AnalyticsAgentApp(BaseAgentApp):
    mcp_servers = {
        "data-mcp": "http://data-mcp:8000/sse",
        "salesforce-mcp": "http://salesforce-mcp:8000/sse",
        "payments-mcp": "http://payments-mcp:8000/sse",
        "news-search-mcp": "http://news-search-mcp:8000/sse",
    }
```

**After (registry-driven):**

```python
class AnalyticsAgentApp(BaseAgentApp):
    mcp_dependencies = ["ai-mcp-data", "ai-mcp-salesforce", "ai-mcp-payments", "ai-mcp-news-search"]
```

`_connect_bridges` becomes:

```python
async def _connect_bridges(self, agent_ctx, timeout):
    if not self.mcp_dependencies:
        return {}
    bridges = {}
    for name in self.mcp_dependencies:
        entry = await self.registry.lookup(name)
        if not entry.healthy:
            log.warning("mcp_unhealthy_skipping", name=name)
            continue
        bridge_url = entry.url.rstrip("/") + "/sse"
        bridges[name] = MCPToolBridge(bridge_url, agent_context=agent_ctx)
    # ... gather + connect (unchanged)
    return bridges
```

The `mcp_servers` dict is **kept for one minor release as a deprecation path**. If both are set, `mcp_dependencies` wins. If only `mcp_servers` is set, the SDK logs a `DeprecationWarning` and uses it. Removed in 0.6.0.

### `RegistryEntry` and `RegistrationRequest` Pydantic models

Both `narisun/ai-registry` (server) and consuming services import these from `platform_sdk.registry.models` — wire compatibility enforced by the type checker.

```python
class RegistryEntry(BaseModel):
    name: str
    url: HttpUrl | None
    expected_url: HttpUrl | None
    type: Literal["agent", "mcp", "registry", "other"]
    state: Literal["registered", "expected_unregistered", "stale"]
    version: str | None
    metadata: dict[str, Any] = Field(default_factory=dict)
    last_heartbeat_at: datetime | None
    registered_at: datetime | None
    last_changed_at: datetime

class RegistrationRequest(BaseModel):
    name: str
    url: HttpUrl
    type: Literal["agent", "mcp", "registry", "other"]
    version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
```

## Operational & security concerns

### Authentication

- Reads (`GET /api/services*`, `GET /health`, UI at `/`): unauthenticated by design. Anything on the internal network can discover what's running. Matches public MCP registry pattern.
- Writes (`POST /api/services`, `DELETE`, `POST /heartbeat`): require `Authorization: Bearer ${INTERNAL_API_KEY}`. Reuses `platform_sdk.security.make_api_key_verifier()`.

### Threat model — name impersonation

A malicious actor on the internal network with `INTERNAL_API_KEY` could register a fake `ai-mcp-data` pointing at an attacker-controlled URL. Agents would then route queries through the attacker.

**v1 mitigation: trust boundary inheritance.** `INTERNAL_API_KEY` is the platform's existing trust boundary. Anyone with it can already do worse damage (mint JWTs, OPA bypass, etc.). Adding per-service deploy keys is defense-in-depth; tracked as v2.

**What v1 enforces:**
- Registration request `url` field must be a valid `HttpUrl` (Pydantic-validated).
- Re-registration with a different URL logs `service_url_changed` at WARN.
- Reaper only changes state, never invents new entries.

**Tracked for v2 (out of scope):**
- mTLS between services and registry.
- Per-service deploy keys signed by a small CA.
- Allow-list: drift from the seed config triggers ops alert.

### Persistence & restart behavior

SQLite file lives in a Docker volume:

```yaml
ai-registry:
  image: ghcr.io/narisun/ai-registry:0.5.0
  ports: ["127.0.0.1:8090:8090"]
  environment:
    REGISTRY_PORT: 8090
    SEED_PATH: /etc/registry/registry.yaml
    SQLITE_PATH: /var/lib/registry/registry.db
    INTERNAL_API_KEY: ${INTERNAL_API_KEY}
  volumes:
    - ai-registry-data:/var/lib/registry
    - ./config/registry.yaml:/etc/registry/registry.yaml:ro
```

When the registry restarts:
1. SQLite reopens. `state='registered'` rows are stale (no recent heartbeats).
2. Reaper marks them `stale` after 60s, evicts after 5min.
3. Real services re-register on next heartbeat tick (~15s) → state returns to `registered`.
4. Client cache shields agents from this transient gap (5min stale-cache-max).

Net: ~30s of "everything is stale" in the UI after a registry restart, then steady-state.

### Observability

Structured logs for every state transition + every API call:

```python
log.info("registration", name=name, url=url, type=type)
log.info("heartbeat", name=name, latency_ms=ms)
log.info("deregistration", name=name, reason="graceful")
log.info("reaper_state_change", name=name, from_state="registered", to="stale")
log.warning("service_url_changed", name=name, old_url=old, new_url=new)
log.warning("registry_unreachable", consumer=consumer_name)  # client-side
```

Metrics (via `platform_sdk.metrics`):

```python
record_counter("registry_register_total", labels={"name", "type"})
record_counter("registry_heartbeat_total", labels={"name", "outcome"})
record_counter("registry_lookup_total", labels={"name", "cache_status"})
record_gauge("registry_services_by_state", labels={"state"})
record_histogram("registry_heartbeat_age_seconds", labels={"name"})
```

### Rate limiting

v1: none. Heartbeats × 8 services = ~32 writes/min; SQLite handles 4-digit writes/sec comfortably. Internal-only network. If abuse becomes a concern, add `slowapi` later.

### Concurrent / racing registrations

Last-write-wins on `name` PK. URL change emits `service_url_changed` warning. Operators decide if it's an honest re-deploy or impersonation. Stronger options (require deregister-before-re-register, registration tokens) tracked as v2.

## Testing strategy

### Unit tests — `narisun/ai-registry/tests/unit/`

Pure logic, sub-second, no Docker, no HTTP server:

| File | Coverage |
|---|---|
| `test_config_loader.py` | YAML parse, missing file behavior, all required fields validated |
| `test_sqlite_store.py` | CRUD, idempotent `apply_seed()`, state transitions |
| `test_reaper.py` | Time-mocked staleness/eviction, hybrid behavior (seeded vs unseeded) |
| `test_routes_register.py` | Schema validation, 401 / 200 paths, idempotency |
| `test_routes_lookup.py` | 404 / 200 paths, response shape |
| `test_routes_heartbeat.py` | 404 if not registered, 200 + timestamp bump |

### Unit tests — `narisun/ai-platform-sdk/tests/unit/test_registry_client.py`

Use `httpx.MockTransport` so we never start a real server:

- `test_lookup_returns_cache_when_fresh`
- `test_lookup_returns_stale_cache_on_registry_outage`
- `test_lookup_raises_when_stale_cache_too_old`
- `test_circuit_breaker_short_circuits_after_5_failures`
- `test_register_self_is_idempotent_on_409`
- `test_heartbeat_task_continues_through_transient_failures`
- `test_self_registration_skipped_when_registry_url_matches_self_url`

### Component tests — `narisun/ai-registry/tests/component/`

`RegistryApp` end-to-end inside one process — real FastAPI, real SQLite (in-memory or temp file), fake clock for the reaper. Full register→heartbeat→stale→evict cycle in <1s with mocked time.

### Application tests — `narisun/ai-platform-sdk/tests/application/test_application_registers_self.py`

Verify lifespan ordering: telemetry → register → bridges → on_started → yield → deregister → flush.

```python
async def test_baseagentapp_registers_before_bridges_connect(fake_registry, monkeypatch):
    ...
    assert fake_registry.calls == ["register_self", "lookup", "deregister"]


async def test_application_skips_self_registration_if_no_registry_url(monkeypatch):
    monkeypatch.delenv("REGISTRY_URL", raising=False)
    # Service starts cleanly, no registry calls, no errors
```

### Integration tests — `narisun/ai-dev-stack/tests/integration/test_registry_e2e.py`

Real Docker Compose stack:

- `test_registry_sees_all_seeded_services` — every service registers within 30s; UI shows green.
- `test_service_recovers_after_registry_restart` — soft-fail with stale cache validated end-to-end.

### Pytest fixtures — `platform_sdk.testing.plugin`

```python
@pytest.fixture
async def fake_registry():
    """In-memory fake of RegistryClient. Records calls; simulates outages.
    Used by service-repo tests verifying their own registration."""

@pytest.fixture
async def real_registry_server(tmp_path):
    """Spins up an actual RegistryApp in-process on a random port.
    Used by component tests that need the real server."""
```

### Coverage targets

- `ai-registry`: ≥85% line coverage on unit + component.
- SDK `RegistryClient`: ≥90% (cache + soft-fail + circuit-breaker are airtight).
- Integration: 2–3 tests max in `ai-dev-stack` (slow; trust unit/component for everything else).

## Migration & rollout

Every step independently shippable and reversible. No big-bang.

### Sequence

1. **SDK 0.5.0** (`narisun/ai-platform-sdk`): adds `RegistryClient`, `Application` registration hooks, models, testing fixtures. Additive only — `mcp_servers` dict still works with `DeprecationWarning`. Tag → release workflow → SDK + base image `3.11-sdk0.5.0`.
2. **`narisun/ai-registry` v0.5.0** (NEW repo): server + UI, consumes SDK 0.5.0. Tag → image at `ghcr.io/narisun/ai-registry:0.5.0`.
3. **`ai-dev-stack`**: add `ai-registry` service to compose; inject `REGISTRY_URL` into every service's environment; bind-mount `config/registry.yaml`. Tag v0.5.0; E2E verifies registry comes up. Services don't have to USE the registry yet (they're still on SDK 0.4.0).
4. **Per-service SDK bumps** (8 repos: `ai-agent-analytics`, 4 `ai-mcp-*`, `ai-registry` itself): pin SDK to 0.5.0, bump base image to `3.11-sdk0.5.0`. Services now self-register on startup. `mcp_servers` dict still in use — registry is observability-only at this stage. Tag v0.5.0 in each.
5. **`ai-agent-analytics`**: replace `mcp_servers` dict with `mcp_dependencies` list. The first agent to actually depend on the registry for URL resolution. Tag v0.5.1.
6. **SDK 0.6.0** (later, opportunistic): drop `mcp_servers` deprecation shim. Wait for at least one minor cycle of grace.

### What can break, recovery plan

| Failure | Detection | Recovery |
|---|---|---|
| Registry won't start (config bug) | E2E in dev-stack fails | Don't merge Step 3. Fix yaml. |
| Services can't register | `registry_register_failed` warnings | Services start anyway (registration is non-blocking). Investigate. |
| Reaper falsely evicts | `registry_services_by_state{state=stale}` spikes | Bump `heartbeat_grace_seconds` env on registry; redeploy registry only. |
| Step 5 ships and analytics-agent can't find data-mcp | Agent startup fails at `_connect_bridges` | Roll back analytics-agent to v0.5.0. SDK is unaffected. |
| Registry restart breaks running agents | `registry_unreachable_using_stale` logs | Soft-fail behavior already covers this. |

## Scope boundary: services vs. MCP tools

The registry tracks **services** (agents, MCP servers, the registry itself, future runtime processes) — not the MCP **tools** that live inside MCP servers. Tools are discovered via the MCP protocol's standard `list_tools()` call, made by the agent against each MCP server *after* the agent has resolved the server's URL via the registry.

This is a deliberate split:

- **Registry's job:** "Where is `ai-mcp-data` running, and is it healthy?" → returns URL + state.
- **MCP protocol's job:** "What tools does `ai-mcp-data` expose?" → returns tool definitions, schemas, descriptions.

Duplicating tool metadata in the registry would create a second source of truth that drifts from each MCP server's own declaration. `MCPToolBridge` already calls `list_tools()` on connect; that data is fresh by definition. The registry stays focused on the bootstrap problem (URL resolution + health), and the existing MCP plumbing handles capability discovery.

If a future need surfaces — e.g., a "platform tool catalog" UI that browses all tools across all MCP servers without contacting them — that's a separate component that *consumes* the registry to enumerate MCP servers, then aggregates `list_tools()` results from each. Not a registry feature.

## Out of scope (v1, deliberate)

- Multi-instance registration (running 2 copies of `data-mcp` for HA). Today's registry is one-name-one-URL.
- Mutual TLS between services and registry.
- A Vercel-hosted UI repo (`ai-frontend-registry`).
- Postgres backend (SQLite is fine for foreseeable scale).
- Rate limiting and audit log.
- Webhooks (notify Slack when a service goes stale).
- Mutating UI (manual register / edit / delete) — add later if operational pain forces it.
- Tags / filters / search in UI.

## References

- Public MCP registry: https://registry.modelcontextprotocol.io (inspiration for catalog UX)
- Existing SDK base classes: `platform_sdk.base.application.Application`, `platform_sdk.base.agent.Agent`, `platform_sdk.base.mcp_service.McpService`
- Existing health-tracking: `platform_sdk.bridge_health.BridgeHealthMatrix` (per-agent, not cross-service — superseded by registry for cross-service discovery)
- Existing helper: `platform_sdk.mcp_server_base.make_health_router` (each service still exposes `/health`; registry polls these via heartbeat-from-services, not registry-polls-services)
- Multi-repo restructure plan: this is the first major design after that work; extends the multi-repo pattern, doesn't break it

---

**Next step:** turn this design into a concrete implementation plan via `superpowers:writing-plans`.
