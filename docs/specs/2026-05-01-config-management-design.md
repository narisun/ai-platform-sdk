# Configuration Management — Design Specification

**Date:** 2026-05-01
**Status:** Approved (post-brainstorm); ready for implementation planning.
**Owners:** Platform team.

## Goal

Centralise configuration so every Python service in the platform loads its settings from one place, validates them at startup, and never reads `os.environ` outside the SDK. Operational settings live in committed YAML files; secrets stay in environment variables and are referenced from YAML via `${VAR}` substitution. After this change, "where does this URL come from?" or "what happens when DB_PASS is missing?" both have a single, obvious answer.

## Why this exists

The current configuration story has three problems that compound each other:

1. **Three near-duplicate `from_env()` factories** in the SDK (`MCPConfig`, `AgentConfig`, `RegistryConfig`) and a fourth raw-`os.environ.get()` pattern in the registry — all doing the same shape of work, drifting independently.
2. **Module-level env reads bypass the config layer.** Every MCP `main.py` reads `MCP_TRANSPORT` and `PORT` at import time; `ai-agent-analytics/src/app.py` reads `DATABASE_URL` and `ENVIRONMENT` inside helpers; the frontend reads everything through `process.env`. These leaks make a future centralised config invisible to the leaked sites and impossible to audit.
3. **Secrets and operational config are intermingled.** `MCPConfig` puts `db_pass` next to `opa_url` and circuit-breaker thresholds. There is no rule for "where does this value live?" — only convention.

We are still pre-production, so a hard cut is cheap. Doing this once-and-done now is far cheaper than dragging dual paths through every future feature.

## Decisions made during brainstorming

| Question | Choice | Rationale |
|---|---|---|
| Approach | **Option 1 — YAML-per-service, secrets via env, SDK provides loader** | Each repo owns its config next to its code; SDK owns the one loading mechanism. No central config repo coupling. |
| Scope | **C — Python services only, schema designed to be TS-mirrorable later** | Frontend keeps `process.env` for now; YAML schema and `${VAR}` syntax stay portable. |
| Per-environment handling | **B — `default.yaml` + optional `<env>.yaml` overlay, deep-merged** | Non-secret values that legitimately differ across envs (timeouts, log levels, model routes) belong in committed config, not in `.env`. |
| Path discovery | **B — convention (`/app/config/`) with `CONFIG_DIR` env override** | Convention covers 95%; env override unblocks k8s configmaps and ad-hoc ops without rebuilds. |
| Environment variable naming | **Single strict `ENVIRONMENT` enum (no separate `APP_ENV`)** | One source of truth for "which env am I" — used for overlay selection, OPA stamping, and L3 isolation. |
| Strictness ceiling | **L3 — validation + registry isolation + transit `X-Environment` header** | Only level robust to operator mistakes downstream of config (hardcoded URLs, leaked secrets, stale `.env`). |
| Loader API integration | **C — base class auto-loads when no `config=` is passed, explicit override allowed** | Zero-boilerplate production path; tests/scripts keep an escape hatch. |
| Migration of `from_env()` | **A — hard cut in SDK 0.6.0; no shim** | Greenfield, six services, one path is cheaper than two. |
| `${VAR}` syntax | **No defaults in syntax + inline substitution + strict missing-env** | Defaults belong on Pydantic fields; inline matches Compose/envsubst conventions; strict aligns with L3. |
| `.env` convention | **A — dev-stack `.env` canonical; per-repo `.env.example` only; CI checks coverage** | One audit point for secrets; docs cannot drift from YAML. |
| Sequencing | **C — SDK first (hard cut), services in parallel, dev-stack last** | Brief broken-build window matches recent registry rollout; avoids shim code that exists only to be deleted. |

## Architecture

### File layout (post-implementation)

```
<each Python service repo>
├── config/
│   ├── default.yaml                Operational config. Committed. Source of truth.
│   ├── dev.yaml                    Optional overlay for ENVIRONMENT=dev.
│   ├── staging.yaml                Optional overlay for ENVIRONMENT=staging.
│   └── prod.yaml                   Optional overlay for ENVIRONMENT=prod.
├── .env.example                    Required env vars referenced by config/*.yaml. Committed.
├── .env                            Gitignored. Never present in this repo for the dev-stack flow.
└── Dockerfile                      COPY config/ /app/config/

ai-platform-sdk
└── platform_sdk/
    ├── config/
    │   ├── loader.py               NEW — load_config() free function + ConfigError.
    │   ├── env_isolation.py        NEW — Environment Literal, X-Environment header constants/helpers.
    │   ├── mcp_config.py           CHANGED — adds load() classmethod, port/transport fields; from_env() removed.
    │   ├── agent_config.py         CHANGED — adds load() classmethod, database_url field; from_env() removed.
    │   └── helpers.py              REMOVED — _env / _env_int / _env_float / _env_bool gone.
    ├── http.py                     NEW — make_internal_http_client(config) factory.
    └── tools/
        └── check_env_example.py    NEW — CLI: scans config/*.yaml for ${VAR} refs, validates against .env.example.
                                    Installed as `platform-sdk check-env-example`.

ai-registry
├── src/config.py                   CHANGED — RegistryConfig.load(); from_env() removed.
└── config/{default,dev,staging,prod}.yaml   NEW

ai-dev-stack
├── .env                            Gitignored — the canonical local-dev secrets file.
├── .env.example                    Committed — authoritative list of all secrets across the platform.
└── docker-compose.yml              CHANGED — env_file: .env; environment: {ENVIRONMENT: dev, ...} only.
                                    No operational config inlined in compose any more.
```

### High-level flow at startup

```
process start
   │
   ├─ ENVIRONMENT read from os.environ
   │     └─ if missing or not in {dev,staging,prod} → ConfigError, exit non-zero
   │
   ├─ Application.__init__(config=None)
   │     └─ MCPConfig.load() → load_config(MCPConfig)
   │           ├─ read /app/config/default.yaml             (required)
   │           ├─ read /app/config/<ENVIRONMENT>.yaml        (optional)
   │           ├─ deep-merge (overlay wins)
   │           ├─ walk all string values:
   │           │     for each ${VAR}, look up os.environ[VAR]
   │           │     collect every missing var into errors list
   │           ├─ MCPConfig.model_validate(merged_dict)
   │           │     collect every Pydantic ValidationError detail
   │           └─ if errors:  raise ConfigError(file:line, field, missing var)
   │
   ├─ self.environment = config.environment   (already validated as Literal)
   │
   ├─ on outbound HTTP via SDK clients:
   │     httpx headers default = {"X-Environment": self.environment, ...}
   │
   └─ on inbound HTTP (FastAPI/MCP auth dependency):
         require X-Environment header, must equal self.environment, else 403
```

## Loader specification

### Public API

```python
# platform_sdk/config/loader.py
from typing import TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

class ConfigError(Exception):
    """Raised when configuration cannot be loaded or validated.

    .errors is a list of structured error records, each containing:
      - location: "config/default.yaml:12" or "<env>" for missing-env-var
      - field:    dotted Pydantic field path (e.g. "db_pass")
      - reason:   human-readable explanation
    """
    errors: list["ConfigErrorDetail"]

def load_config(
    model_cls: type[T],
    *,
    config_dir: str | None = None,   # default: $CONFIG_DIR or "/app/config"
    env: str | None = None,          # default: $ENVIRONMENT (required)
) -> T:
    """Load <config_dir>/default.yaml + <config_dir>/<env>.yaml, resolve
    ${VAR}, validate against model_cls, return a populated instance.
    Collects every error before raising — never partial."""
```

Pydantic models gain a thin classmethod that delegates to the loader:

```python
class MCPConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @classmethod
    def load(cls, *, config_dir: str | None = None, env: str | None = None) -> "MCPConfig":
        return load_config(cls, config_dir=config_dir, env=env)
```

### File discovery

| Source | Default | Override |
|---|---|---|
| Config directory | `/app/config/` | `$CONFIG_DIR` |
| Environment selector | `$ENVIRONMENT` (required, no default) | `env=` kwarg in `load()` |
| Default file | `<config_dir>/default.yaml` | None — required |
| Overlay file | `<config_dir>/<env>.yaml` | None — optional, silently skipped if absent |

### Layering semantics (deep merge)

- `default.yaml` is the base. `<env>.yaml`, if present, is merged on top.
- Merge rules:
  - Scalars in overlay replace scalars in base.
  - Mappings are merged key-by-key, recursively.
  - Lists in overlay **replace** lists in base (no element-wise merge — keeps semantics simple and predictable).
- Both files must validate as YAML mappings at the top level (a list at the root is an error).

### `${VAR}` substitution

- **Syntax:** `${VAR_NAME}`. No `${VAR:-default}`, no `${VAR:?error}`, no nesting (the resolved value of `${A}` is *not* re-scanned for further substitution).
- **Scope:** every string value in the merged dict is walked. A single string may contain multiple `${VAR}` tokens at any position; each is replaced independently. Example: `db_url: postgres://app:${DB_PASS}@${DB_HOST}:5432/app`.
- **Escape:** literal `$${...}` collapses to `${...}` after substitution (so YAML can express the literal string `${FOO}` if ever needed).
- **Type coercion:** substitution happens in YAML *string* values; the result is fed to Pydantic, which performs its normal coercion (string → int, etc). To set a non-string field from an env var, write the YAML as a string and let Pydantic coerce: `port: "${PORT}"` → Pydantic int.
- **Missing env var:** collected into the `errors` list with `location = "config/default.yaml:<line>"`, `reason = "VAR not set in environment"`. **Never** silently substituted with empty string.
- **Recursion guard:** because resolved values are not re-scanned, accidental `${VAR}=${OTHER}` chains are impossible by construction.

### Validation order

The loader runs three sequential phases. Within each phase, errors are aggregated; if a phase produced any errors, the loader raises `ConfigError` containing all of them and does not advance to the next phase.

1. **Parse.** Read `default.yaml` (required) and `<env>.yaml` (optional). YAML syntax errors → `ConfigError` with `file:line`.
2. **Substitute.** Deep-merge, then walk every string value resolving `${VAR}` from `os.environ`. Every missing var collected into one `ConfigError`.
3. **Validate.** `model_cls.model_validate(merged_dict)`. Pydantic `ValidationError` details unpacked into `ConfigErrorDetail` records and raised as one `ConfigError`.

On success, return the validated instance.

Why phase-stop rather than collect-everything: Pydantic cannot meaningfully validate a dict with literal `${UNRESOLVED}` strings in fields typed as `int` or `Literal`. Reporting the missing env vars first gives the operator the actionable error; once those are fixed, the next run surfaces any genuine Pydantic-level mistakes (wrong type, value out of range).

Error messages aggregate every problem; example:

```
ConfigError: 3 problems loading MCPConfig:
  - config/default.yaml:7   field 'db_pass'        : DB_PASS not set in environment
  - config/default.yaml:14  field 'opa_url'        : DOES_NOT_EXIST not set in environment
  - config/dev.yaml:3       field 'opa_timeout_seconds' : input should be > 0 (got -5)
Hint: every env var referenced from config/*.yaml must be listed in .env.example.
```

## Strict environment isolation (L3)

`ENVIRONMENT` is the only env var that determines which environment a process belongs to. It is propagated through three layers, each enforced.

### Layer 1 — config validation

```python
# platform_sdk/config/env_isolation.py
from typing import Literal

Environment = Literal["dev", "staging", "prod"]
ENV_HEADER = "X-Environment"
```

Every config model that inherits from a shared `ApplicationConfig` base has:

```python
class ApplicationConfig(BaseModel):
    environment: Environment   # required, no default
    ...
```

Missing or invalid → `ConfigError` at startup. The loader does not synthesise a default.

### Layer 2 — registry isolation

The registry's own `ENVIRONMENT` is loaded the same way. The registry's auth dependency (the same one that validates `INTERNAL_API_KEY`) gains an `X-Environment` check:

- On every write endpoint (`/api/services`, `/api/services/{name}/heartbeat`, `DELETE /api/services/{name}`), the dependency requires the header to be present and equal to the registry's own `environment`. Mismatch → `403 Forbidden` with body `{"error": "environment_mismatch", "expected": "...", "got": "..."}`. No registration occurs.
- The registry persists the registering service's environment as a column on `RegistryEntry`. Lookup endpoints (`GET /api/services`, `GET /api/services/{name}`) filter by the requesting client's `X-Environment` header so a `dev` client cannot enumerate `prod` services.

### Layer 3 — transit isolation

Every SDK-provided HTTP client stamps `X-Environment` automatically; every SDK-provided server-side dependency validates it. This is the *general* enforcement; Layer 2 is the registry-specific application of the same primitive.

Outbound (clients):
- A new `make_internal_http_client(config)` factory in `platform_sdk.http` returns a pre-configured `httpx.AsyncClient` with default headers `X-Environment: <env>` and `Authorization: Bearer <internal_api_key>`. **All** inter-service Python HTTP calls go through this factory; ad-hoc `httpx.AsyncClient()` construction in service code is removed.
- `RegistryClient` is built on top of this factory and inherits the headers automatically.
- The MCP bridge layer (in `BaseAgentApp._connect_bridges`) attaches the same headers when opening SSE connections to MCP servers.

Inbound (servers):
- `make_api_key_verifier()` (in `platform_sdk.security`) gains an `environment: Environment` parameter; the dependency rejects requests whose `X-Environment` header is missing or doesn't match. Rejection is `403`, distinguishable from auth failure (`401`).
- The MCP server's auth wrapper (FastMCP is FastAPI-based) inserts the same dependency at startup.
- A reject is logged with structured fields `(expected_env, got_env, peer_ip)` so cross-env leakage is visible in the standard log stream.

### What L3 does and doesn't catch

| Mistake | Caught at |
|---|---|
| `ENVIRONMENT` missing or typo'd at startup | Config load — process refuses to start |
| Service has wrong `ENVIRONMENT` (e.g. operator pasted prod `.env` into dev) and tries to register against the dev registry | Registry auth — `403` on register; service fails to start |
| Service's config hardcodes a peer URL pointing to another environment (e.g. dev service hardcodes `data-mcp.prod` in its YAML) | Transit — receiving server's auth dependency returns `403` based on the X-Environment header |
| Service in env A talks to a peer in env B without going through SDK clients (raw `httpx.AsyncClient()`) | Not caught by L3 directly. Mitigated by removing all ad-hoc `httpx.AsyncClient()` construction in Phase 2 and adding a CI grep that fails if any returns. |

L3 closes the operator-mistake hole the user raised. The remaining hole — code that bypasses the SDK's HTTP factory — is closed by the Phase-2 cleanup combined with a grep-based CI check (see Migration plan).

## Pydantic model changes

### `MCPConfig`

- Add fields hoisted from `main.py` leaks: `port: int`, `mcp_transport: Literal["stdio","sse"]`.
- Add `environment: Environment` (replaces the existing free-form `environment: str`).
- Remove `from_env()` and `helpers.py` `_env*` functions.
- Add `MCPConfig.load()` classmethod.
- `model_config` keeps `extra="forbid"`.

### `AgentConfig`

- Add `environment: Environment`, `database_url: str`.
- Remove `from_env()`.
- Add `AgentConfig.load()` classmethod.

### `RegistryConfig` (in `ai-registry`, mirrors SDK pattern)

- Add `environment: Environment`.
- Remove `from_env()` (the raw `os.environ.get` pattern).
- Add `RegistryConfig.load()` (delegates to SDK's `load_config`).

### Splits and refactors deferred

We do **not** split each model into operational + secrets pairs. The user goal is "secrets are referenced via `${VAR}`" — that already separates concerns at the YAML layer without doubling the model surface area. A future refactor could introduce per-secret types if needed.

## SDK base-class integration

```python
# platform_sdk/base/application.py
class Application:
    config_model: ClassVar[type[BaseModel]]   # subclasses override

    def __init__(self, config: BaseModel | None = None):
        self.config = config if config is not None else self.config_model.load()
        self.environment = self.config.environment
        ...
```

`McpService(Application)` and `BaseAgentApp(Application)` set `config_model` to `MCPConfig` and `AgentConfig` respectively. Subclasses override only when they need a custom shape (rare).

Tests that previously did `monkeypatch.setenv(...)` + `MCPConfig.from_env()` switch to one of:

1. Construct directly: `MCPConfig(opa_url="...", environment="dev", ...)` — best for unit tests.
2. Use the `tmp_path` fixture: write a `default.yaml`, call `load_config(MCPConfig, config_dir=tmp_path, env="dev")` — best for integration tests of the loader itself.

## CI: `.env.example` ↔ YAML coverage

A new SDK CLI:

```
platform-sdk check-env-example [--config-dir config] [--env-example .env.example]
```

Behavior:

1. Walk every `*.yaml` under `--config-dir`.
2. Extract every distinct `${VAR}` reference (regex `\$\{([A-Z_][A-Z0-9_]*)\}` — no `$$` literals).
3. Read `--env-example` (`KEY=value` lines, comments allowed).
4. Pass conditions:
   - Every `${VAR}` from step 2 has a `VAR=` line in `.env.example`. Missing vars are listed and exit code is non-zero.
   - Every `KEY=` in `.env.example` is referenced from at least one YAML file. Unreferenced vars warn (exit 0) — they may be runtime-only (e.g., `INTERNAL_API_KEY` consumed by the auth dependency, not the loader).
   - The exempt list of "runtime-only" vars is defined in a small allowlist in the CLI itself: `INTERNAL_API_KEY`, `ENVIRONMENT`, `CONFIG_DIR`. New entries require an SDK PR.

Each service repo's CI runs `platform-sdk check-env-example` as a single step. CI fails if `.env.example` drifts from the YAML.

## Migration plan (sequencing C)

### Phase 1 — SDK 0.6.0 (single PR in `ai-platform-sdk`)

1. Add `platform_sdk/config/loader.py`, `env_isolation.py`, and the `check_env_example` CLI.
2. Refactor `MCPConfig`, `AgentConfig` to add `load()`, hoist leaked fields, change `environment` to `Environment` Literal.
3. Remove `from_env()` and `_env*` helpers.
4. Update `RegistryClient` to inject `X-Environment` header.
5. Add a new `make_internal_http_client(config)` factory in `platform_sdk.http` — returns an `httpx.AsyncClient` with default `X-Environment` and `Authorization: Bearer` headers. `RegistryClient` is rebuilt on top of it.
6. Extend `make_api_key_verifier()` to take and validate `environment`.
7. Update `Application.__init__` to call `cls.config_model.load()` when no config is provided.
8. Add unit tests for loader (substitution, layering, missing-var error aggregation, type coercion, escape sequence).
9. Bump SDK version to 0.6.0; tag and release. **Existing downstream service builds break here, intentionally.**

### Phase 2 — Six service repos in parallel

Each of `ai-mcp-data`, `ai-mcp-news-search`, `ai-mcp-payments`, `ai-mcp-salesforce`, `ai-agent-analytics`, `ai-registry`:

1. Add `config/default.yaml` and `config/dev.yaml` (any current env values → YAML literals or `${VAR}` references).
2. Add `.env.example`.
3. Bump SDK pin to 0.6.0 (and base-image tag to `3.11-sdk0.6.0` once published).
4. Delete every direct `os.environ` access in service code — the SDK's loader is the only place that reads the environment. Notable sites to remove: `main.py` PORT/TRANSPORT in every MCP repo; `app.py` DATABASE_URL/ENVIRONMENT in `ai-agent-analytics`. Replace with reads from `self.config.<field>`.
5. Wire CI to run `platform-sdk check-env-example`.
6. Tag a new minor for each service (e.g., `ai-mcp-data 0.6.0`).

These six PRs do not depend on each other. Whichever lands first lands first.

### Phase 3 — `ai-dev-stack`

1. Create `ai-dev-stack/.env` (gitignored) and `.env.example` (committed) listing every secret across the platform — `INTERNAL_API_KEY`, `DB_PASS`, third-party API keys, etc. **No operational config in `.env`.**
2. Edit `docker-compose.yml`:
   - `env_file: .env` on every service (delivers all secrets).
   - `environment:` blocks contain *only* `ENVIRONMENT=dev`. Operational values that vary by env (OPA URL, DB host, registry URL) live in each service's `config/dev.yaml` as literal values referencing Compose-internal hostnames (`http://opa:8181/...`, `db:5432`, etc.).
   - Bind-mount `config/registry.yaml` for the registry seed as before.
3. Bump every service's image tag to its 0.6.0 release.
4. Refresh integration tests:
   - Strict assertion that every service registered with `environment=dev`.
   - New assertion that a fake client sending `X-Environment: prod` to any internal endpoint receives `403`.
   - Grep-based assertion (run as a CI step in every Python service repo) that `httpx.AsyncClient(` does not appear outside `platform_sdk/http.py` — preventing future bypasses of the L3 transit headers.
5. `make setup` end-to-end.

### Backward compatibility

None. SDK 0.6.0 is breaking by design. Old service images on SDK 0.5.x continue to work against an old dev-stack but are not interoperable with anything 0.6.0+. We do not promise mixed-version operation.

## Out of scope

- **Frontend (`ai-frontend-analytics`).** Continues to use `process.env`. The YAML schema and `${VAR}` syntax are designed to be portable, but no TS loader is built this round. A follow-up spec covers the frontend pass.
- **External-service configs** (`platform/config/litellm-local.yaml`, `platform/otel/otel-local.yaml`). These are consumed by LiteLLM and the OTel collector respectively, not by our Python code. They stay where they are and use whatever variable expansion their owners support.
- **Schema-introspection YAML** (`platform/db/relationships.yaml`). Loaded by `schema_introspection.py` as semantic data, not configuration. Untouched.
- **Per-secret type splitting** (separate `MCPSecrets` model, etc.). Deferred. The `${VAR}` reference is a sufficient separation today.
- **Encrypted secrets at rest** (sops, sealed-secrets, etc.). Out of scope. `.env` is plain text; production deployments outside the dev-stack will use whatever secret manager is appropriate (k8s secrets, AWS SM, Azure Key Vault) — those substitute env vars before the process starts, which is exactly what the loader expects.

## Open questions / risks

### Risks accepted

1. **Phase-2 build-broken window.** Between SDK 0.6.0 release and the last service's 0.6.0 release, `make setup` against `main` of every repo is broken. Mitigated by sequencing all six service PRs to land within ~1 day.
2. **Wrong-`.env` poisoning the registry.** If the dev-stack `.env` contains `ENVIRONMENT=dev` but the registry was started with `ENVIRONMENT=prod` somehow, services will fail to register and the failure will be visible in logs immediately. This is a Layer-2 catch and acceptable.

### Open

1. **k8s ergonomics for `${VAR}` in configmaps.** When the config YAML is shipped via configmap (future), operators may want envsubst at the configmap-build step or at the loader. Spec defers — current loader does runtime substitution, which works for both compose and k8s.
2. **Pydantic v2 secret types.** Pydantic offers `SecretStr` / `SecretBytes` that mask values in repr/log output. Worth adopting for fields like `db_pass` and `internal_api_key` to harden against accidental log leakage. Out of scope for this round but a one-line follow-up per field.
3. **Where does `INTERNAL_API_KEY` get rotated?** The current model has the same key shared across every internal HTTP path. A separate spec for per-service rotated keys is a likely follow-up but does not block this round.
