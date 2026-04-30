# Changelog

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
