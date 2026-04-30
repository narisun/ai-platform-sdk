# enterprise-ai-platform-sdk

Shared SDK for the Enterprise AI Platform. Provides the cross-cutting concerns that every agent and every MCP server needs — logging, telemetry, auth, OPA authorization, caching, MCP tool bridging, configuration, FastAPI/FastMCP lifespan wiring — so service developers can focus on business logic instead of re-implementing infrastructure.

```python
# A complete agent service in 12 lines:
from platform_sdk import BaseAgentApp, AgentContext

class MyAgentApp(BaseAgentApp):
    service_name = "ai-agent-my"
    mcp_servers = {"data-mcp": "http://data-mcp:8000/sse"}
    requires_checkpointer = True

    def build_dependencies(self, *, bridges, checkpointer, store):
        return {"graph": build_my_graph(bridges, checkpointer)}

    def routes(self):
        return [chat_router, health_router]

app = MyAgentApp().create_app()
```

The base class brings: structured logging, OpenTelemetry tracing, MCP bridge connection, schema fetching, conversation-store wiring, CORS, exception handling, graceful shutdown, and a verified service identity for outbound MCP calls. None of that is in your service.

---

## Why this SDK exists

In a multi-service AI platform, every agent and every MCP server has the same set of concerns:

- Read configuration from the environment, with sensible defaults and fail-fast validation.
- Set up structured logging that downstream collectors can parse.
- Initialize OpenTelemetry tracing and Langfuse callbacks.
- Verify a JWT, build an `AgentContext`, sign it with HMAC, and forward it to MCP servers.
- Decode the HMAC-signed `X-Agent-Context` header on the receiving end.
- Enforce per-tool authorization via OPA, fail-closed on any error.
- Wrap tool results in a Redis-backed cache.
- Trim long conversation histories before they exceed the model's context window.
- Retry transient failures with backoff, fail fast when a circuit breaker opens.
- Wire all of the above into a FastAPI lifespan or FastMCP lifespan in a specific order.

Without an SDK, every new service re-implements these. Subtle differences accumulate: one agent forgets to seal the OPA fail-closed path; one MCP server logs the JWT into a trace; one service uses `time.time()` for HMAC verification instead of `hmac.compare_digest()` and is now timing-attackable.

This SDK collects those primitives in one place and ships base classes (`BaseAgentApp` for FastAPI agents, `McpService` for FastMCP servers) that wire them up in the right order. **Service repos should import from this SDK; they should not copy patterns from each other.**

## What the SDK owns

| Concern | Module | Key API |
|---|---|---|
| Structured logging | `platform_sdk.logging` | `configure_logging()`, `get_logger(name)` |
| OpenTelemetry + Langfuse | `platform_sdk.telemetry` | `setup_telemetry(svc)`, `flush_langfuse()` |
| Typed configuration | `platform_sdk.config` | `AgentConfig.from_env()`, `MCPConfig.from_env()` |
| JWT-verified identity | `platform_sdk.auth` | `AgentContext`, `assert_secrets_configured()` |
| MCP-side auth middleware | `platform_sdk.mcp_auth` | `AgentContextMiddleware`, `verify_auth_context()` |
| Bearer token verifier | `platform_sdk.security` | `make_api_key_verifier()` |
| OPA authorization | `platform_sdk.security` | `OpaClient` (fail-closed, retry, circuit breaker) |
| Redis cache | `platform_sdk.cache` | `ToolResultCache.from_config()`, `cached_tool()` |
| Resilience primitives | `platform_sdk.resilience` | `CircuitBreaker` |
| LLM routing | `platform_sdk.llm_client` | `EnterpriseLLMClient` (LiteLLM proxy wrapper) |
| Context compaction | `platform_sdk.compaction` | `make_compaction_modifier(config)` |
| MCP tool bridge | `platform_sdk.mcp_bridge` | `MCPToolBridge` (auto-reconnect, header signing) |
| Schema introspection | `platform_sdk.schema_introspection` | `introspect_schema()`, `format_for_prompt()` |
| Prompt management | `platform_sdk.prompt_manager` | `PromptManager` (Langfuse-backed) |
| Tool error model | `platform_sdk.models` | `make_tool_error()`, `make_tool_success()` |
| FastAPI agent base | `platform_sdk.fastapi_app` | `BaseAgentApp` |
| FastMCP service base | `platform_sdk.base` | `McpService`, `Application`, `Agent` |
| Pytest plugin | `platform_sdk.testing` | `TEST_PERSONAS`, `make_persona_jwt`, `persona_*` fixtures |
| Scaffolding CLI | `platform_sdk.cli` | `platform-sdk new agent\|mcp <name>` |

Each module is independent — you can use `OpaClient` without touching `BaseAgentApp` if your service has its own framework. But the base classes wire everything in the canonical order, and that's what new services should reach for.

---

## Quick start

### Install the SDK

The SDK ships via Git URL pin (no PyPI publication). Public-repo installs over HTTPS need no auth; private repos need an SSH key.

```bash
pip install "enterprise-ai-platform-sdk[fastapi,postgres-checkpointer] \
  @ git+ssh://git@github.com/narisun/ai-platform-sdk.git@v0.4.0"
```

For local SDK development against a service repo:

```bash
pip install -e ../ai-platform-sdk
```

### Scaffold a new service

The SDK ships a `platform-sdk` CLI that generates a starter repo with the canonical layout (Dockerfile inheriting from `ai-python-base`, slim `requirements.txt`, `BaseAgentApp` / `McpService` skeleton, conftest with sys.path bootstrap, `.gitignore`).

```bash
platform-sdk new agent --name pricing --target /tmp/ai-agent-pricing
platform-sdk new mcp --name inventory --target /tmp/ai-mcp-inventory
```

The templates use three placeholder forms: `{{name}}` (lowercase, hyphens preserved), `{{Name}}` (CapWords from a hyphenated name — `customer-support` becomes `CustomerSupport`), and `{{NAME}}` (SHOUT with hyphens to underscores).

### Build the container

Service Dockerfiles inherit from the SDK-bundled base image at `ghcr.io/narisun/ai-python-base:3.11-sdk{VERSION}`. The base image has the SDK pre-installed with the `[fastapi,postgres-checkpointer]` extras, so each service's Dockerfile is a thin layer on top:

```dockerfile
ARG BASE_TAG=3.11-sdk0.4.0
FROM ghcr.io/narisun/ai-python-base:${BASE_TAG}

WORKDIR /app
COPY requirements-runtime.txt .
RUN pip install --no-cache-dir -r requirements-runtime.txt
COPY src/ /app/src/

USER appuser
EXPOSE 8000
CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

`requirements-runtime.txt` holds only **service-specific** extras (e.g., `uvicorn`, `tavily-python`). The SDK is in the base image already; do not re-install it inside the container build (the build context has no Git or SSH key).

---

## Building an agent — extend `BaseAgentApp`

`BaseAgentApp` is a FastAPI lifespan factory. Subclasses declare configuration as class attributes and implement two methods.

```python
from platform_sdk import BaseAgentApp, AgentContext


class PricingAgentApp(BaseAgentApp):
    # ---- Identity (used in logs, OTel resource attrs, FastAPI title) ----
    service_name        = "ai-agent-pricing"
    service_title       = "Pricing Agent"
    service_description = "Real-time pricing decisions over MCP-exposed catalog data."

    # ---- Cross-cutting toggles ----
    enable_telemetry            = True   # OpenTelemetry + Langfuse on startup
    requires_checkpointer       = True   # LangGraph PostgresSaver / MemorySaver
    requires_conversation_store = True   # ConversationStore for chat persistence

    # ---- MCP servers this agent talks to ----
    mcp_servers = {
        "catalog-mcp":  "http://catalog-mcp:8000/sse",
        "pricing-mcp":  "http://pricing-mcp:8000/sse",
    }

    # ---- Override service identity for outbound MCP calls ----
    def service_agent_context(self) -> AgentContext:
        # Default is role="readonly" (fail-closed minimum-privilege).
        # Elevate when the agent needs broader access.
        return AgentContext(
            rm_id="pricing-agent",
            rm_name="Pricing Agent",
            role="manager",
            team_id="pricing",
            assigned_account_ids=(),
            compliance_clearance=("standard",),
        )

    # ---- Wire dependencies (sync hook; runs after bridges connect) ----
    def build_dependencies(self, *, bridges, checkpointer, store):
        return AppDependencies(
            graph=build_pricing_graph(bridges, self.config, checkpointer),
            conversation_store=store,
            chat_service_factory=lambda user_ctx: ChatService(...),
        )

    # ---- Routes to mount ----
    def routes(self):
        return [health_router, chat_router, conversations_router]

    # ---- Async post-init hook (optional; runs after build_dependencies) ----
    async def on_started(self, deps, *, bridges, config, checkpointer, store):
        deps.schema_context = await fetch_schema(bridges["catalog-mcp"])

    # ---- Override exception handlers for domain errors (optional) ----
    def register_exception_handlers(self, app):
        @app.exception_handler(PricingError)
        async def _on_pricing_error(request, exc):
            return JSONResponse({"error": str(exc)}, status_code=500)


# Module-level entry point — uvicorn loads this `app` symbol
_agent = PricingAgentApp()
app = _agent.create_app()
```

What `BaseAgentApp.lifespan` does for you in order:

1. `configure_logging()` — structlog JSON output to stdout.
2. `setup_telemetry(service_name)` if `enable_telemetry=True` — registers an OTel SDK provider, exports OTLP traces, hooks Langfuse callbacks into LangChain.
3. Calls `load_config()` — by default reads `AgentConfig.from_env()` (subclass to customize).
4. Connects to each MCP server in `mcp_servers` concurrently with `asyncio.gather(...)`. Failures don't block startup; they're logged with `mcp_startup_status`. Per-server URLs can be overridden via `<NAME>_URL` env var (e.g., `CATALOG_MCP_URL`).
5. Sets up the LangGraph checkpointer if `requires_checkpointer=True`.
6. Calls `build_conversation_store()` if `requires_conversation_store=True`.
7. Calls your `build_dependencies(bridges=, checkpointer=, store=)` and assigns the result to `app.state.deps`.
8. Awaits your `on_started(deps, bridges=, config=, checkpointer=, store=)` async hook.
9. Logs `<service>_ready` with hyphens normalized to underscores.
10. Yields. FastAPI starts accepting requests.
11. On shutdown: `on_shutdown(deps)`, `flush_langfuse()` (gated on `enable_telemetry`), `await store.disconnect()`, `await bridge.disconnect()` per bridge.

Tests construct their own `AppDependencies` and call `_agent.create_app(deps=fake_deps)` directly — no lifespan, no env, no Docker. The `create_app()` factory is a pure function: no env reads, no I/O.

---

## Building an MCP server — extend `McpService`

`McpService` is the symmetric base class for FastMCP servers. Same pattern: declare configuration via class attributes, implement two methods.

```python
from platform_sdk import McpService, MCPConfig, get_logger, make_tool_error


log = get_logger(__name__)


class InventoryMcpService(McpService):
    # ---- Cross-cutting toggles ----
    cache_ttl_seconds = 300   # Redis tool-result cache TTL
    requires_database = True  # asyncpg pool created during lifespan
    enable_telemetry  = True
    assert_secrets    = True  # fail startup if JWT_SECRET is the default in non-dev env

    async def on_startup(self) -> None:
        """Service-specific startup. config, authorizer, cache, db_pool are all
        ready by the time this runs — the base lifespan creates them."""
        self.tracer = trace.get_tracer(__name__)
        self.inventory = InventoryQueryService(self.db_pool, self.tracer)
        log.info("inventory_mcp_ready")

    def register_tools(self, mcp) -> None:
        @mcp.tool()
        async def get_inventory(sku: str, auth_context: str = "") -> str:
            user = verify_auth_context(auth_context)  # HMAC-verified identity

            # OPA authorization — fail-closed on any error
            if not await self.authorizer.authorize(
                "get_inventory",
                {"sku": sku, "user_role": user.user_role},
            ):
                return make_tool_error("unauthorized", "Blocked by policy.")

            # Tool-result cache — keyed by tool name + args + user role
            key = make_cache_key("get_inventory", {"sku": sku, "role": user.user_role})
            if (cached := await self.cache.get(key)) is not None:
                return cached

            result = await self.inventory.lookup(sku)
            await self.cache.set(key, result)
            return result
```

Server entry point:

```python
# src/main.py
import os
from mcp.server.fastmcp import FastMCP
from platform_sdk import configure_logging, get_logger
from .inventory_service import InventoryMcpService

configure_logging()
log = get_logger(__name__)

TRANSPORT = os.environ.get("MCP_TRANSPORT", "stdio")
service = InventoryMcpService("ai-mcp-inventory")

if TRANSPORT == "sse":
    mcp = FastMCP(
        "ai-mcp-inventory",
        lifespan=service.lifespan,  # ← SDK-managed lifespan
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
    )
else:
    mcp = FastMCP("ai-mcp-inventory", lifespan=service.lifespan)

service.register_tools(mcp)

if __name__ == "__main__":
    mcp.run(transport=TRANSPORT)
```

What `McpService.lifespan` does:

1. `setup_telemetry(name)` if `enable_telemetry=True`.
2. `assert_secrets_configured()` if `assert_secrets=True` — raises `RuntimeError` with an actionable message if `JWT_SECRET` is still the default value in any non-dev environment.
3. Creates an `OpaClient` (fail-closed, with circuit breaker) and assigns it to `self.authorizer`.
4. Creates a `ToolResultCache` if `MCPConfig.enable_tool_cache=True` and assigns to `self.cache`.
5. Creates an `asyncpg.Pool` if `requires_database=True` and assigns to `self.db_pool` (uses `cfg.db_*` settings, applies SSL when `db_require_ssl=True`).
6. Calls your `on_startup()` hook.
7. Yields.
8. On teardown: `on_shutdown()`, then closes only the resources the base class created (it doesn't close injected resources, so tests can pass in fakes safely).

For dependency injection in tests:

```python
fake_authorizer = AlwaysAllowAuthorizer()
service = InventoryMcpService(
    "test",
    config=test_config,
    authorizer=fake_authorizer,
    cache=in_memory_cache,
    db_pool=fake_pool,
)
# The base lifespan respects injected resources and won't overwrite them.
```

---

## Configuration: typed dataclasses with fail-fast validation

`AgentConfig` and `MCPConfig` are frozen dataclasses with two ways in:

- `Config(field=value, ...)` — explicit construction (tests, dependency injection).
- `Config.from_env()` — read from environment with the documented defaults.

Both call `__post_init__` to validate **all fields at once** and raise a `ValueError` listing every problem found. This is deliberately not "first error wins" — when something's broken at startup, the operator wants to see every misconfiguration in one error, not iterate through them one at a time.

Example: malformed config triggers a single, complete error message.

```python
>>> MCPConfig(
...     opa_url="not-a-url",
...     environment="invalid-env",
...     agent_role="bogus_role",
...     opa_timeout_seconds=-1,
...     max_result_bytes=10,
... )
Traceback (most recent call last):
  ...
ValueError: MCPConfig validation failed:
  opa_url must be an HTTP(S) URL, got: not-a-url;
  environment='invalid-env' not in {'dev', 'local', 'staging', 'prod', 'production', 'test'};
  agent_role='bogus_role' not in {'commercial_banking_agent', 'data_analyst_agent',
  'compliance_agent', 'analytics_agent'};
  opa_timeout_seconds=-1 must be positive;
  max_result_bytes=10 is too low (min 1000)
```

Every config field has a default, so most services pass. The validation strictness is reserved for fields where a wrong value silently produces incorrect security or correctness behavior — agent role, environment, OPA URL, timeouts.

The same pattern applies to `AgentConfig`:

```python
>>> AgentConfig(context_token_limit=10, model_route="")
Traceback (most recent call last):
  ...
ValueError: AgentConfig validation failed:
  context_token_limit=10 is too low (min 100);
  model_route must not be empty
```

### Reading environment variables

Config helpers (`_env`, `_env_int`, `_env_bool`, `_env_float`) coerce types and fall back to defaults. `_env_int` raises `ValueError` if the env var is set but not numeric — better to fail at startup than to silently coerce a typo to zero.

The full list of env vars each config reads is documented in the dataclass field comments and in the `from_env()` body. There's no "magic" mapping — read the dataclass, see exactly which env var names map to which fields.

### Read-time vs. import-time

Module-level helpers (`_get_jwt_secret`, `_get_hmac_secret`) read `os.environ` **at call time**, not at import time. This matters because:

1. Tests can `monkeypatch.setenv("JWT_SECRET", ...)` and the change is picked up immediately.
2. Late-set Docker Compose env vars (e.g., from `env_file` after the container starts) are honored.

If you write your own SDK extension, follow this rule: do not capture `os.environ.get(...)` in module-level constants.

---

## Security & authorization: fail-closed by default

The SDK takes a hard line on security defaults. Every primitive defaults to the safer choice and requires explicit opt-in to relax it.

### `assert_secrets_configured()` — refuse to start with default secrets

```python
from platform_sdk import assert_secrets_configured
assert_secrets_configured()  # raises in any non-dev env if JWT_SECRET is default
```

Error message is actionable:

```
RuntimeError: JWT_SECRET has not been rotated from the default value in the
'staging' environment. Set JWT_SECRET to a strong random secret. If running
locally, set ENVIRONMENT=dev to suppress this check.
```

A common bug elsewhere is checking `if env == "prod"` — this misses staging and UAT, which mirror production data but use a different `ENVIRONMENT` value. The SDK checks for `env != "dev"` instead, so any non-dev value (staging, prod, uat, test) triggers the assertion.

### `OpaClient` — fail-closed authorization

`OpaClient.authorize(tool, payload)` returns `False` (deny) on:

- Network timeout
- HTTP error response from OPA
- Any exception during the request
- All retries exhausted
- Circuit breaker open (after N consecutive failures)

It returns `True` only if OPA explicitly returns `{"result": true}`. There is no path that "fails open" because OPA was unreachable.

```python
opa = OpaClient(MCPConfig.from_env())
allowed = await opa.authorize("get_inventory", {"sku": sku, "user_role": user.role})
if not allowed:
    return make_tool_error("unauthorized", "Blocked by policy.")
```

### Server-stamped `environment` and `agent_role`

A previous code review found that callers could inject `environment` and `agent_role` into the OPA payload to escalate privileges. The fix is in the SDK: `OpaClient.authorize` always overwrites those two fields with values from `MCPConfig`, ignoring whatever the caller passed.

```python
input_data = {
    **payload,
    "tool": tool_name,
    "environment": self._environment,   # server-stamped, not from caller
    "agent_role":  self._agent_role,    # server-stamped, not from caller
}
```

### HMAC-signed `X-Agent-Context` header

Inter-service calls (agent → MCP) carry the verified caller identity in an `X-Agent-Context` header:

```
<base64url(JSON payload)>.<hex(HMAC-SHA256(payload, CONTEXT_HMAC_SECRET))>
```

Both segments are required. `AgentContext.from_header()` raises `ValueError` if the signature is missing or doesn't match. The middleware then falls through to `AgentContext.anonymous()` — minimum-privilege, **not** fail-open. Constant-time HMAC comparison via `hmac.compare_digest()` prevents timing attacks.

`CONTEXT_HMAC_SECRET` defaults to `JWT_SECRET` for development simplicity but should be a separate value in production — defense-in-depth, so a JWT compromise alone can't forge MCP context headers.

### Dual-secret rotation windows

Both `JWT_SECRET_PREVIOUS` and `CONTEXT_HMAC_SECRET_PREVIOUS` are honored if set. During a rotation, services accept both the current and the previous secret — letting you redeploy services independently without coordinated downtime. After rotation completes, unset the `*_PREVIOUS` vars.

### `AgentContextMiddleware` — auth at the MCP boundary

Each MCP server's tool handler reads the per-request identity:

```python
from platform_sdk.mcp_auth import AgentContextMiddleware, get_agent_context

# Patch FastMCP's sse_app() at module level to inject middleware:
if TRANSPORT == "sse":
    _orig_sse_app = mcp.sse_app
    def _patched_sse_app(mount_path=None):
        starlette_app = _orig_sse_app(mount_path)
        starlette_app.add_middleware(AgentContextMiddleware)
        return starlette_app
    mcp.sse_app = _patched_sse_app

@mcp.tool()
async def get_inventory(sku: str) -> str:
    ctx = get_agent_context()  # AgentContext or None
    if ctx is None or not ctx.has_clearance("standard"):
        return make_tool_error("unauthorized", "Insufficient clearance.")
```

---

## Observability

### Structured logging via structlog

```python
from platform_sdk import configure_logging, get_logger
configure_logging()
log = get_logger(__name__)

log.info("query_executed", session_id=sid, rows=42, ms=duration_ms)
```

Output is JSON to stdout, ready for any aggregator. Field names should be `snake_case` and stable — these are queryable identifiers. Do not log secrets, JWTs, or full request bodies.

### OpenTelemetry tracing

`setup_telemetry(service_name)` registers the SDK's OTel provider, configures the OTLP exporter to whatever `OTEL_EXPORTER_OTLP_ENDPOINT` points at, and auto-instruments LangChain / OpenAI / FastAPI. You don't write `tracer.start_span(...)` boilerplate; the auto-instrumentation creates spans for every LLM call, every LangChain step, every HTTP request. You only manually trace business-domain operations.

### Langfuse callbacks

`get_langfuse_callback_handler()` returns a per-request `LangfuseCallbackHandler`. Pass it to LangChain's `RunnableConfig` and every LLM call in the chain shows up in the Langfuse UI with full prompt / completion / cost. The base lifespan calls `flush_langfuse()` on shutdown so traces aren't dropped on container exit.

### Metrics

Pre-registered counters and gauges for the things every service cares about:

```python
from platform_sdk import (
    record_cache_state, record_cache_transition,
    record_opa_decision, record_opa_circuit_state,
    record_mcp_tool_call,
)
```

These hit the OTel meter provider configured by `setup_telemetry()`.

---

## Resilience patterns

### `CircuitBreaker`

Reusable circuit breaker — used internally by `OpaClient`, available for your own integrations:

```python
from platform_sdk import CircuitBreaker

cb = CircuitBreaker(name="my-api", failure_threshold=5, recovery_timeout=30.0)

if cb.is_open:
    return cached_fallback()
try:
    result = await call_api()
    cb.record_success()
    return result
except Exception:
    cb.record_failure()
    raise
```

After 5 consecutive failures, `is_open` returns `True` for 30 seconds. After the recovery timeout, it half-opens for one probe call.

### Retry-with-backoff

`OpaClient` retries OPA calls 2 times by default with 0.2s backoff (configurable via `OPA_MAX_RETRIES` / `OPA_RETRY_BACKOFF`). Note the constraint: **retries on transient errors only** (timeout, connection error). HTTP 4xx responses fail immediately — no point retrying a 403.

### Graceful degradation in `BaseAgentApp.lifespan`

MCP bridge connections use `asyncio.gather(..., return_exceptions=True)`. If one bridge fails to connect at startup, the agent still starts; just that bridge's tools are unavailable. Each bridge logs its connection status (`mcp_startup_status` event with `connected: bool`).

### Auto-reconnection in `MCPToolBridge`

The MCP bridge maintains its SSE connection across transient network failures with capped exponential backoff (`mcp_reconnect_backoff_cap`, default 60s). Tool calls timeout per `tool_call_timeout` (default 30s).

---

## Testing

### Pytest plugin (auto-registered)

The SDK ships a pytest plugin via the `pytest11` entry-point. Any test run with the SDK installed gets these fixtures automatically — no per-repo conftest registration needed:

```python
def test_my_route(client, make_persona_jwt, persona_manager):
    token = make_persona_jwt(persona_manager)
    response = client.post("/chat", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
```

Available fixtures (all session-scoped):

- `jwt_secret`, `hmac_secret`, `internal_api_key` — read from env or fall back to test defaults
- `make_persona_jwt(persona_dict) -> str` — factory that signs a JWT with the right secret
- `persona_manager`, `persona_senior_rm`, `persona_rm`, `persona_readonly` — pre-built persona payloads from `TEST_PERSONAS`

### Test personas

`platform_sdk.testing.TEST_PERSONAS` is the single source of truth for test identities. Each persona has the fields a real `AgentContext` would carry: `rm_id`, `rm_name`, `role`, `team_id`, `assigned_account_ids`, `compliance_clearance`. Different personas have different data access — the readonly persona has no assigned accounts, the senior_rm has more, the manager has full team visibility — letting tests exercise OPA decisions and row-level filters without faking the auth layer.

```python
from platform_sdk.testing import TEST_PERSONAS

def test_readonly_blocked_from_writes():
    ctx = AgentContext(**TEST_PERSONAS["readonly"])
    assert not ctx.has_clearance("aml_view")
```

### Test layers

The recommended layered test approach (used by `ai-agent-analytics`):

- **`tests/unit/`** — pure logic, no I/O. Asyncio mode auto. Fast (sub-second).
- **`tests/component/`** — multiple classes wired together, external systems faked.
- **`tests/application/`** — `create_app(fake_deps)` + FastAPI `TestClient`. No Docker.
- **`tests/integration/`** — full Docker Compose stack. Marked `@pytest.mark.integration`.

The SDK's pyproject.toml advertises `asyncio_mode = "auto"` so `async def test_*` functions are collected without manual `@pytest.mark.asyncio`. Add the same line to your service's pyproject if it has async tests.

---

## Distribution

### Git URL pin (no PyPI)

The SDK is consumed via Git URL pin. Local dev and CI use SSH; non-Docker installs use HTTPS for public repos:

```
# requirements.txt
enterprise-ai-platform-sdk[fastapi,postgres-checkpointer] @ git+ssh://git@github.com/narisun/ai-platform-sdk.git@v0.4.0
```

**Tags are immutable.** Pin to a specific tag (`@v0.4.0`); never to `main` or a floating ref. Pip caches by URL — tag pins give you cache hits.

### Pre-baked base image

`ghcr.io/narisun/ai-python-base:3.11-sdk{VERSION}` ships Python 3.11-slim plus the SDK installed with `[fastapi,postgres-checkpointer]`. Tag scheme: `3.11-sdk0.4.0` (pinned), `3.11-sdk-latest` (floating — never use in production).

The `release.yml` workflow in this repo builds and pushes both tags whenever a `vX.Y.Z` tag is pushed.

### Two-track install

| Context | How the SDK is installed |
|---|---|
| Production runtime | Inherited from `ai-python-base` base image. No re-install in service Dockerfile. |
| Local dev / CI | `pip install -r requirements.txt` (resolves the git URL pin). |
| SDK development | `pip install -e ../ai-platform-sdk` (editable install overrides the pin). |

---

## Versioning & deprecations

This SDK follows SemVer. Service repos should pin to a specific tag (`@v0.4.0`) and bump intentionally — never `>=`, never `latest`, never `main`.

**MAJOR.MINOR.PATCH:**

- **MAJOR** — incompatible API change. Every consumer must update.
- **MINOR** — additive change. Old code keeps working. New features available.
- **PATCH** — bug fixes. No API change.

**Deprecation policy:**

- A deprecated symbol stays for at least one MINOR release with a `DeprecationWarning`.
- The CHANGELOG flags every deprecation under "Changed."
- Removal happens in the next MINOR release after the deprecation lands.

Example: `tools_shared.mcp_auth` was deprecated in `0.4.0` (re-export shim) and will be removed in `0.5.0`.

---

## Contributing

This SDK is small and high-leverage — every new symbol affects every service repo. The bar for adding things is high.

**Add a primitive to the SDK when:**

- It's needed by 2+ service repos (or definitively will be).
- It encodes a security or correctness concern that's easy to get wrong (HMAC verification, fail-closed authorization, secret rotation).
- It's a cross-cutting concern (logging, telemetry, config) that should be uniform across services.

**Don't add to the SDK when:**

- Only one service uses it. Keep it in that service.
- It's domain-specific (e.g., a CRM-specific data model, a payments-specific adapter). That belongs in the consuming MCP server.
- It's a thin wrapper that adds no value over the underlying library.

**Process:**

1. Fork, branch from `main`.
2. Add tests first (TDD) — `platform-sdk/tests/unit/` for pure logic, separate test files per module.
3. Update CHANGELOG.md under an `## Unreleased` heading.
4. Open a PR to `main`. CI runs unit tests on every push.
5. Maintainers cut a `release/X.Y` branch when MINOR features are ready, tag `vX.Y.Z`. The release workflow publishes the new base image to GHCR.

---

## Reference

- Source: https://github.com/narisun/ai-platform-sdk
- Base image: https://github.com/narisun/ai-platform-sdk/pkgs/container/ai-python-base
- Service repos that use this SDK:
  - https://github.com/narisun/ai-agent-analytics
  - https://github.com/narisun/ai-mcp-data
  - https://github.com/narisun/ai-mcp-salesforce
  - https://github.com/narisun/ai-mcp-payments
  - https://github.com/narisun/ai-mcp-news-search
  - https://github.com/narisun/ai-frontend-analytics (Next.js, no SDK)
  - https://github.com/narisun/ai-dev-stack (orchestration)
- Release notes: [CHANGELOG.md](./CHANGELOG.md)
- License: MIT
