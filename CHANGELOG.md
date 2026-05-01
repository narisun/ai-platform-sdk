# Changelog

## 0.6.1 — 2026-05-01

### FIX

- `MCPConfig` now defines `internal_api_key: str = ""`.

  Previously this field only existed on `AgentConfig`, which meant MCP
  services could not authenticate when registering with `ai-registry`:
  `RegistryClient.from_config(config)` reads `config.internal_api_key`,
  and the missing field resolved to an empty string, producing a 401 at
  the registry's auth dependency. Surfaced consistently across all four
  Phase-2 MCP migrations (data, news-search, payments, salesforce) — each
  had to drop `internal_api_key: ${INTERNAL_API_KEY}` from their
  `config/default.yaml` because of `extra="forbid"`.

  After 0.6.1, MCP repos can restore the YAML reference and authenticate
  registration normally.

## 0.6.0 — 2026-05-01

### BREAKING

- `MCPConfig.from_env()` and `AgentConfig.from_env()` removed.
  Use `MCPConfig.load()` / `AgentConfig.load()` instead. The new
  loader reads `config/default.yaml` + optional `config/<env>.yaml`,
  resolves `${VAR}` from env, and validates against the Pydantic model.
- `MCPConfig` and `AgentConfig` are now Pydantic v2 BaseModel
  subclasses (previously dataclasses). Field defaults preserved.
  `extra="forbid"` rejects unknown YAML keys.
- `Application.load_config()` abstract method removed. Subclasses
  declare `config_model: ClassVar[type[BaseModel]]` instead.
- `ENVIRONMENT` is now a strict `Literal["dev", "staging", "prod"]`.
  Values like `"local"`, `"production"`, `"test"` are rejected.

### NEW

- `platform_sdk.config.loader.load_config()` — three-phase loader
  (parse → substitute → validate) with collect-all errors.
- `platform_sdk.config.env_isolation.Environment` Literal and
  `ENV_HEADER = "X-Environment"` constant.
- `platform_sdk.http.make_internal_http_client(config)` factory —
  stamps `X-Environment` and Bearer auth on every outbound request.
- `make_api_key_verifier(environment=...)` — inbound `X-Environment`
  validation. Mismatch → 403.
- `RegistryClient.from_config(config, registry_url=...)` constructor
  — uses the HTTP factory automatically.
- `platform-sdk check-env-example` CLI subcommand — scans
  `config/*.yaml` for `${VAR}` references and verifies `.env.example`
  covers them.

### REMOVED

- `platform_sdk.config.helpers` module and the `_env`, `_env_int`,
  `_env_float`, `_env_bool` helpers. The loader is the only env-reader.

## 0.5.1 — 2026-05-01

### Fixed
- `McpService.run_with_registration(mcp, transport)` — new helper that
  registers + heartbeats on a background asyncio thread, then calls
  `mcp.run(transport)`. Use this in MCP service `__main__` blocks
  instead of `mcp.run()` directly.

  Reason: FastMCP's SSE-mode lifespan attaches to a per-connection ASGI
  app, so registration tied to lifespan only fires while a client is
  mid-stream. Without this helper, MCP services never persist as
  `state=registered` in the registry catalog. The lifespan-based wiring
  in `Application._register` / `_deregister` (introduced in 0.5.0) is
  retained for FastAPI agents (where lifespan IS process-scoped).

### Migration notes
- MCP service authors: change your `__main__` block from
  `mcp.run(transport=TRANSPORT)` to
  `service.run_with_registration(mcp, TRANSPORT)`. The existing
  `lifespan=service.lifespan` argument to `FastMCP(...)` should be
  retained — it still drives OPA / cache / db_pool init for tools.
- FastAPI agents (`BaseAgentApp` subclasses) are unaffected.

## 0.5.0 — 2026-05-01

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
- `_register()` raises `RuntimeError` when `REGISTRY_URL` is set but
  `SERVICE_URL` is empty (a common deployment misconfiguration that
  silently registers the wrong URL otherwise).

### Migration notes
- Existing services on 0.4.0 keep working — both `mcp_servers` and the
  absence of `REGISTRY_URL` are fully backwards-compatible. When you bump
  to 0.5.0 and set `REGISTRY_URL` in your environment, your service
  self-registers automatically. Migrate `mcp_servers` → `mcp_dependencies`
  on your own schedule before 0.6.0.

## 0.4.0 — 2026-04-30

### Added
- `platform_sdk.mcp_auth` (promoted from `tools/shared/mcp_auth.py`):
  `AgentContextMiddleware`, `get_agent_context`, `verify_auth_context`.
- `platform_sdk.fastapi_app.BaseAgentApp` — FastAPI lifespan factory
  symmetric to `McpService.lifespan`. Subclasses declare `service_name`,
  `service_title`, `service_description`, `mcp_servers`, and implement
  `build_dependencies()` / `routes()`. Async `on_started(deps, *, bridges,
  config, checkpointer, store)` hook for post-init work.
- `platform_sdk.testing.plugin` — pytest plugin (auto-registered via
  pytest11 entry-point) shipping `jwt_secret`, `hmac_secret`,
  `internal_api_key`, `make_persona_jwt`, `persona_*` session fixtures.
- `AgentContext.is_anonymous` property (returns `True` when `rm_id == "anonymous"`).

### Changed
- `tools_shared.mcp_auth` retained as a deprecation re-export (will be
  removed at 0.5.0 alongside the multi-repo carve-out).
- `BaseAgentApp.service_agent_context()` defaults to `role="readonly"`
  (fail-closed minimum-privilege); subclasses override for elevated clearance.
- `flush_langfuse()` on shutdown is now gated by `enable_telemetry`
  (was unconditional) so telemetry-disabled services don't initialize
  a Langfuse client just to tear it down.

### Migration notes
- New agents: subclass `BaseAgentApp` instead of hand-writing FastAPI
  lifespan + `create_app` boilerplate.
- New MCP servers: continue to subclass `McpService` (unchanged).
- Per-service consumers should import middleware/auth helpers from
  `platform_sdk.mcp_auth` rather than `tools_shared.mcp_auth`.

## 0.3.0 — earlier
(see git history)
