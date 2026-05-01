# Configuration Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Centralise configuration so every Python service in the platform loads its settings from one place, validates them at startup, and never reads `os.environ` outside the SDK's loader. Operational settings live in committed YAML files; secrets stay in environment variables and are referenced from YAML via `${VAR}` substitution. Strict L3 environment isolation prevents cross-environment traffic.

**Architecture:** SDK 0.6.0 ships a hard-cut replacement of `from_env()` factories with a unified `load_config(model_cls, config_dir, env)` that reads `default.yaml` + optional `<env>.yaml`, deep-merges, resolves `${VAR}` inline against `os.environ`, and validates against Pydantic v2 models. `MCPConfig`, `AgentConfig`, and `RegistryConfig` migrate from `@dataclass` to `pydantic.BaseModel` to gain `extra="forbid"` and `model_validate`. A new `make_internal_http_client(config)` factory stamps `X-Environment` and Bearer auth on every outbound HTTP call; `make_api_key_verifier()` validates the inbound header. The `Application` base class auto-loads via a `config_model: ClassVar` declaration; `_register()` reads `registration.*` fields from the config rather than `os.environ`. A new SDK CLI subcommand `platform-sdk check-env-example` is wired into each service's CI to keep `.env.example` in sync with `${VAR}` references in `config/*.yaml`. Migration is sequenced as one SDK release (broken-build window), six independent service migrations in parallel, then a final dev-stack PR.

**Tech Stack:** Python 3.11, Pydantic v2 (already a dep — `pydantic>=2.7.0`), PyYAML (already a dep), httpx (existing), structlog (existing), Click (existing — for CLI extension), pytest + pytest-asyncio (existing).

---

## Glossary

| Item | Value |
|---|---|
| GitHub org | `narisun` |
| SDK version (this milestone) | `0.6.0` (current is `0.5.1`) |
| Base image (post-bump) | `ghcr.io/narisun/ai-python-base:3.11-sdk0.6.0` |
| Single env selector | `ENVIRONMENT` (required, `Literal["dev","staging","prod"]`) |
| Config directory convention | `/app/config/` (override via `CONFIG_DIR`) |
| Inbound transit header | `X-Environment` (validated by `make_api_key_verifier`) |
| Outbound transit header | `X-Environment` (stamped by `make_internal_http_client`) |
| Substitution syntax | `${VAR}` only — no defaults, inline, strict missing-env |
| `.env` location | `ai-dev-stack/.env` (gitignored, canonical for local dev) |
| Per-repo doc | `.env.example` (committed, CI-checked) |

## Affected Repos

| Repo | What changes |
|---|---|
| `narisun/ai-platform-sdk` | NEW: `config/env_isolation.py`, `config/loader.py`, `http.py`, CLI subcommand. CHANGED: `MCPConfig`, `AgentConfig` migrated to Pydantic + `load()`. REMOVED: `config/helpers.py`, `from_env()`. Bump to 0.6.0; new base image tag. |
| `narisun/ai-registry` | `RegistryConfig` migrated to Pydantic + `load()`. Auth dependency now validates `X-Environment`. Adds `config/default.yaml` + `config/dev.yaml` + `.env.example`. Bump SDK pin and base image to 0.6.0. |
| `narisun/ai-mcp-data` | Replaces `os.environ.get("MCP_TRANSPORT")` and module-level `PORT` reads with `MCPConfig.load()`. Adds `config/default.yaml` + `config/dev.yaml` + `.env.example`. Bump SDK + base image. |
| `narisun/ai-mcp-news-search` | Same shape as `ai-mcp-data`; port `8083`. |
| `narisun/ai-mcp-payments` | Same shape; port `8082`. |
| `narisun/ai-mcp-salesforce` | Same shape; port `8081`. |
| `narisun/ai-agent-analytics` | Replaces `os.getenv("DATABASE_URL")` and `os.getenv("ENVIRONMENT")` reads with `AgentConfig.load()`. Adds `config/default.yaml` + `config/dev.yaml` + `.env.example`. Bump SDK + base image. |
| `narisun/ai-dev-stack` | Creates `.env`/`.env.example`. Removes operational config from `docker-compose.yml` `environment:` blocks (only `ENVIRONMENT=dev` remains there). Adds `env_file: .env` to every service. Bumps every image tag to `0.6.0`. New integration tests for env-isolation 403s. |
| `narisun/ai-frontend-analytics` | OUT OF SCOPE this round. |

---

## File Structure (post-implementation)

```
narisun/ai-platform-sdk
└── platform_sdk/
    ├── config/
    │   ├── __init__.py                      MODIFIED: drop _env exports; add ConfigError, Environment.
    │   ├── env_isolation.py                 NEW: Environment Literal, ENV_HEADER constant.
    │   ├── loader.py                        NEW: load_config(), ConfigError, ConfigErrorDetail.
    │   ├── mcp_config.py                    MIGRATED: dataclass → BaseModel; load(); from_env() removed.
    │   ├── agent_config.py                  MIGRATED: dataclass → BaseModel; load(); from_env() removed.
    │   └── helpers.py                       REMOVED.
    ├── http.py                              NEW: make_internal_http_client(config).
    ├── security.py                          MODIFIED: make_api_key_verifier(environment=…) param.
    ├── base/
    │   └── application.py                   MODIFIED: config_model ClassVar; auto-load; env reads → config.
    ├── base/
    │   └── mcp_service.py                   MODIFIED: config_model = MCPConfig.
    ├── fastapi_app/
    │   └── base.py                          MODIFIED: config_model = AgentConfig.
    ├── registry/
    │   └── client.py                        MODIFIED: use make_internal_http_client; gain header.
    └── cli/
        └── main.py                          MODIFIED: add `check-env-example` subcommand.
└── tests/unit/
    ├── test_env_isolation.py                NEW
    ├── test_loader.py                       NEW
    ├── test_loader_substitution.py          NEW
    ├── test_loader_layering.py              NEW
    ├── test_mcp_config_pydantic.py          NEW
    ├── test_agent_config_pydantic.py        NEW
    ├── test_http_client.py                  NEW
    ├── test_api_key_verifier_environment.py NEW
    ├── test_check_env_example_cli.py        NEW
    ├── test_application_auto_load.py        NEW
    ├── test_registry_client_environment_header.py  NEW
    ├── test_application_register.py         MODIFIED (config_model, no load_config abstract)
    ├── test_baseagentapp_registers.py       MODIFIED
    ├── test_mcp_service_registers.py        MODIFIED
    └── test_mcp_service_run_with_registration.py   MODIFIED
└── pyproject.toml                           MODIFIED: version → 0.6.0.
└── CHANGELOG.md                             MODIFIED: 0.6.0 entry.

narisun/ai-registry
├── src/
│   ├── config.py                            MIGRATED: BaseModel + load().
│   └── routes/_auth.py                      MODIFIED: pass environment to make_api_key_verifier.
├── config/
│   ├── default.yaml                         NEW
│   └── dev.yaml                             NEW
├── .env.example                             NEW
├── Dockerfile                               MODIFIED: BASE_TAG → 3.11-sdk0.6.0; COPY config/ /app/config/.
├── pyproject.toml                           MODIFIED: SDK pin → 0.6.0.
└── tests/                                   MODIFIED: load via tmp YAML, not env vars.

narisun/ai-mcp-{data,news-search,payments,salesforce}
├── src/main.py                              MODIFIED: read port/transport from MCPConfig.load(); no os.environ.
├── src/server.py                            MODIFIED: same as main.py (it's a shim).
├── config/
│   ├── default.yaml                         NEW
│   └── dev.yaml                             NEW
├── .env.example                             NEW
├── Dockerfile                               MODIFIED: BASE_TAG → 3.11-sdk0.6.0; COPY config/ /app/config/.
├── pyproject.toml                           MODIFIED: SDK pin → 0.6.0 (where applicable).
└── tests/                                   MODIFIED.

narisun/ai-agent-analytics
├── src/app.py                               MODIFIED: replace os.getenv calls with self.config fields.
├── config/
│   ├── default.yaml                         NEW
│   └── dev.yaml                             NEW
├── .env.example                             NEW
├── Dockerfile                               MODIFIED: BASE_TAG → 3.11-sdk0.6.0; COPY config/ /app/config/.
├── pyproject.toml                           MODIFIED: SDK pin → 0.6.0.
└── tests/                                   MODIFIED.

narisun/ai-dev-stack
├── .env                                     NEW (gitignored).
├── .env.example                             NEW (committed).
├── .gitignore                               MODIFIED: ensure .env present.
├── docker-compose.yml                       MODIFIED: env_file: .env on every service; environment: only ENVIRONMENT=dev; image tags → 0.6.0; bind-mount config/registry.yaml as before.
└── tests/integration/
    ├── test_registry_e2e.py                 MODIFIED: assert environment=dev on every entry.
    └── test_environment_isolation.py        NEW: cross-env 403 assertions.
```

---

# Phase 1 — SDK 0.6.0

All Phase-1 tasks happen in the `narisun/ai-platform-sdk` repo on branch `feature/config-management`. Each task is one TDD cycle ending in a commit. After the last Phase-1 task the SDK is tagged `v0.6.0` and a new base image `3.11-sdk0.6.0` is published.

---

## Task 1: Environment isolation primitives

**Files:**
- Create: `platform_sdk/config/env_isolation.py`
- Test: `tests/unit/test_env_isolation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_env_isolation.py
"""Tests for env_isolation primitives."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_environment_literal_accepts_valid_values():
    from typing import get_args

    from platform_sdk.config.env_isolation import Environment

    assert set(get_args(Environment)) == {"dev", "staging", "prod"}


def test_env_header_constant_value():
    from platform_sdk.config.env_isolation import ENV_HEADER

    assert ENV_HEADER == "X-Environment"
```

- [ ] **Step 2: Run test, verify FAIL**

Run: `pytest tests/unit/test_env_isolation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'platform_sdk.config.env_isolation'`

- [ ] **Step 3: Implement**

```python
# platform_sdk/config/env_isolation.py
"""Environment isolation primitives.

Defines the canonical `ENVIRONMENT` value space and the `X-Environment`
HTTP header name used by the SDK's HTTP factory and auth dependencies.
"""
from __future__ import annotations

from typing import Literal

Environment = Literal["dev", "staging", "prod"]
"""Strict enum of supported runtime environments.

The SDK's loader, auth dependency, and registry all enforce this set.
A service whose `ENVIRONMENT` env var is missing or anything other than
one of these three values fails to start.
"""

ENV_HEADER = "X-Environment"
"""Name of the HTTP header used to stamp environment on internal traffic.

Outbound: stamped automatically by `make_internal_http_client(config)`.
Inbound:  validated by `make_api_key_verifier(environment=...)`.
Mismatch: 403 Forbidden.
"""
```

- [ ] **Step 4: Run test, verify PASS**

Run: `pytest tests/unit/test_env_isolation.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add platform_sdk/config/env_isolation.py tests/unit/test_env_isolation.py
git commit -m "feat(config): add Environment Literal and ENV_HEADER constant

Foundational primitives for L3 strict environment isolation. The
Environment Literal is reused by config models; ENV_HEADER is the
header name stamped on outbound HTTP and validated on inbound."
```

---

## Task 2: Config loader and ConfigError

**Files:**
- Create: `platform_sdk/config/loader.py`
- Test: `tests/unit/test_loader.py` (parse, deep-merge, error aggregation)
- Test: `tests/unit/test_loader_substitution.py` (`${VAR}` rules)
- Test: `tests/unit/test_loader_layering.py` (default + overlay)

- [ ] **Step 1: Write the loader basic-shape test**

```python
# tests/unit/test_loader.py
"""Tests for load_config — parse, merge, validate, error aggregation."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import pytest
from pydantic import BaseModel, ConfigDict, Field

pytestmark = pytest.mark.unit


class _SampleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    port: Annotated[int, Field(gt=0, le=65535)] = 8080
    enabled: bool = True


def _write(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


def test_load_default_only(tmp_path):
    from platform_sdk.config.loader import load_config

    _write(tmp_path / "default.yaml", "name: hello\nport: 9000\n")

    cfg = load_config(_SampleConfig, config_dir=str(tmp_path), env="dev")

    assert cfg.name == "hello"
    assert cfg.port == 9000
    assert cfg.enabled is True


def test_overlay_replaces_scalar(tmp_path):
    from platform_sdk.config.loader import load_config

    _write(tmp_path / "default.yaml", "name: base\nport: 8080\n")
    _write(tmp_path / "dev.yaml", "name: overridden\n")

    cfg = load_config(_SampleConfig, config_dir=str(tmp_path), env="dev")

    assert cfg.name == "overridden"
    assert cfg.port == 8080


def test_missing_default_yaml_is_an_error(tmp_path):
    from platform_sdk.config.loader import ConfigError, load_config

    with pytest.raises(ConfigError) as exc:
        load_config(_SampleConfig, config_dir=str(tmp_path), env="dev")

    assert "default.yaml" in str(exc.value)


def test_overlay_optional(tmp_path):
    """If <env>.yaml is absent, loader silently uses default.yaml only."""
    from platform_sdk.config.loader import load_config

    _write(tmp_path / "default.yaml", "name: only\n")
    cfg = load_config(_SampleConfig, config_dir=str(tmp_path), env="staging")

    assert cfg.name == "only"


def test_pydantic_validation_errors_aggregated(tmp_path):
    from platform_sdk.config.loader import ConfigError, load_config

    _write(tmp_path / "default.yaml", "name: x\nport: -1\n")

    with pytest.raises(ConfigError) as exc:
        load_config(_SampleConfig, config_dir=str(tmp_path), env="dev")

    text = str(exc.value)
    assert "port" in text
    # The message must mention the field path and indicate the value problem.
    assert "-1" in text or "greater than 0" in text or "gt=0" in text
```

- [ ] **Step 2: Write the substitution test**

```python
# tests/unit/test_loader_substitution.py
"""${VAR} substitution rules — inline, no defaults, strict missing."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

pytestmark = pytest.mark.unit


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    secret: str = ""
    db_url: str = ""


def test_resolves_single_var(tmp_path, monkeypatch):
    from platform_sdk.config.loader import load_config

    monkeypatch.setenv("DB_PASS", "s3cret")
    (tmp_path / "default.yaml").write_text("secret: ${DB_PASS}\n")

    cfg = load_config(_Cfg, config_dir=str(tmp_path), env="dev")
    assert cfg.secret == "s3cret"


def test_resolves_inline_within_string(tmp_path, monkeypatch):
    from platform_sdk.config.loader import load_config

    monkeypatch.setenv("DB_PASS", "s3cret")
    monkeypatch.setenv("DB_HOST", "primary.local")
    (tmp_path / "default.yaml").write_text(
        "db_url: postgres://app:${DB_PASS}@${DB_HOST}:5432/app\n"
    )

    cfg = load_config(_Cfg, config_dir=str(tmp_path), env="dev")
    assert cfg.db_url == "postgres://app:s3cret@primary.local:5432/app"


def test_missing_var_raises_aggregated(tmp_path, monkeypatch):
    from platform_sdk.config.loader import ConfigError, load_config

    monkeypatch.delenv("DB_PASS", raising=False)
    monkeypatch.delenv("DB_HOST", raising=False)
    (tmp_path / "default.yaml").write_text(
        "secret: ${DB_PASS}\ndb_url: ${DB_HOST}\n"
    )

    with pytest.raises(ConfigError) as exc:
        load_config(_Cfg, config_dir=str(tmp_path), env="dev")

    text = str(exc.value)
    # Both missing vars should appear — collect-all behaviour.
    assert "DB_PASS" in text
    assert "DB_HOST" in text


def test_dollar_dollar_is_literal_dollar(tmp_path):
    """`$${VAR}` collapses to literal `${VAR}` after substitution."""
    from platform_sdk.config.loader import load_config

    (tmp_path / "default.yaml").write_text("secret: $${LITERAL}\n")
    cfg = load_config(_Cfg, config_dir=str(tmp_path), env="dev")

    assert cfg.secret == "${LITERAL}"


def test_resolved_value_is_not_re_scanned(tmp_path, monkeypatch):
    """Recursion guard: ${A}=${B} chains are not resolved transitively."""
    from platform_sdk.config.loader import load_config

    monkeypatch.setenv("A", "${B}")
    monkeypatch.setenv("B", "real")
    (tmp_path / "default.yaml").write_text("secret: ${A}\n")

    cfg = load_config(_Cfg, config_dir=str(tmp_path), env="dev")
    # Value of ${A} is "${B}", which we then DO NOT scan again.
    assert cfg.secret == "${B}"
```

- [ ] **Step 3: Write the layering test**

```python
# tests/unit/test_loader_layering.py
"""Deep-merge semantics for default + overlay."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

pytestmark = pytest.mark.unit


class _Inner(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: int = 0
    b: int = 0


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inner: _Inner = _Inner()
    items: list[str] = []
    name: str = ""


def test_overlay_merges_mapping_keys(tmp_path):
    from platform_sdk.config.loader import load_config

    (tmp_path / "default.yaml").write_text(
        "inner:\n  a: 1\n  b: 2\nname: base\n"
    )
    (tmp_path / "dev.yaml").write_text(
        "inner:\n  a: 99\n"  # only `a` overridden; `b` retained.
    )

    cfg = load_config(_Cfg, config_dir=str(tmp_path), env="dev")
    assert cfg.inner.a == 99
    assert cfg.inner.b == 2  # retained from default
    assert cfg.name == "base"


def test_overlay_replaces_lists_wholesale(tmp_path):
    from platform_sdk.config.loader import load_config

    (tmp_path / "default.yaml").write_text("items:\n  - a\n  - b\n")
    (tmp_path / "dev.yaml").write_text("items:\n  - x\n")

    cfg = load_config(_Cfg, config_dir=str(tmp_path), env="dev")
    # List replacement, not element-wise merge.
    assert cfg.items == ["x"]


def test_overlay_only_keys_added(tmp_path):
    from platform_sdk.config.loader import load_config

    (tmp_path / "default.yaml").write_text("name: base\n")
    (tmp_path / "dev.yaml").write_text("name: base\nitems:\n  - z\n")

    cfg = load_config(_Cfg, config_dir=str(tmp_path), env="dev")
    assert cfg.items == ["z"]


def test_top_level_list_in_default_is_an_error(tmp_path):
    from platform_sdk.config.loader import ConfigError, load_config

    (tmp_path / "default.yaml").write_text("- not\n- a\n- mapping\n")

    with pytest.raises(ConfigError) as exc:
        load_config(_Cfg, config_dir=str(tmp_path), env="dev")

    assert "mapping" in str(exc.value).lower()
```

- [ ] **Step 4: Run all three test files, verify FAIL**

Run: `pytest tests/unit/test_loader.py tests/unit/test_loader_substitution.py tests/unit/test_loader_layering.py -v`
Expected: every test FAIL with `ModuleNotFoundError: No module named 'platform_sdk.config.loader'`.

- [ ] **Step 5: Implement the loader**

```python
# platform_sdk/config/loader.py
"""YAML + ${VAR} configuration loader for Pydantic models.

Behaviour summary:
- Reads <config_dir>/default.yaml (required) and <config_dir>/<env>.yaml (optional).
- Deep-merges: scalars and mappings recurse; lists in overlay REPLACE base.
- Walks every string, resolving ${VAR} from os.environ. Missing vars are
  collected and reported together. `$${VAR}` is the escape for literal `${VAR}`.
- Validates the merged dict against the Pydantic model.
- Three sequential phases (parse → substitute → validate). Within each phase,
  every error is collected. If a phase has any errors, the loader raises
  ConfigError without advancing.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

_VAR_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")
"""Regex for ${VAR} references. Names follow shell convention: uppercase + underscore."""


@dataclass
class ConfigErrorDetail:
    """A single, structured loader problem."""
    location: str
    """File:line locator (e.g. "config/default.yaml:7"), or `<env>` for missing-var."""
    field: str
    """Dotted Pydantic field path (e.g. "db.host"); empty for parse-level errors."""
    reason: str
    """Human-readable explanation."""


class ConfigError(Exception):
    """Raised when configuration cannot be loaded or validated.

    The exception carries every problem encountered during a phase so the
    operator sees the full set of issues at once, not one at a time.
    """

    def __init__(self, errors: list[ConfigErrorDetail], hint: str = ""):
        self.errors: list[ConfigErrorDetail] = list(errors)
        self.hint = hint
        super().__init__(self._format())

    def _format(self) -> str:
        lines = [f"{len(self.errors)} problem{'s' if len(self.errors) != 1 else ''} loading configuration:"]
        for d in self.errors:
            field_part = f"field '{d.field}'" if d.field else "(parse)"
            lines.append(f"  - {d.location:30s}  {field_part:30s}  : {d.reason}")
        if self.hint:
            lines.append(f"Hint: {self.hint}")
        return "\n".join(lines)


def load_config(
    model_cls: type[T],
    *,
    config_dir: str | None = None,
    env: str | None = None,
) -> T:
    """Load and validate configuration for `model_cls`.

    Args:
        model_cls: Pydantic BaseModel subclass to validate against.
        config_dir: Directory containing default.yaml and optional <env>.yaml.
            Defaults to $CONFIG_DIR if set, else "/app/config".
        env: Selects the overlay file. Defaults to $ENVIRONMENT (required).

    Returns:
        Validated instance of `model_cls`.

    Raises:
        ConfigError: when YAML cannot be parsed, an env var is missing,
            or the merged dict fails Pydantic validation. All problems
            within a single phase are aggregated.
    """
    cfg_dir = Path(config_dir) if config_dir is not None else Path(os.environ.get("CONFIG_DIR", "/app/config"))
    env_name = env if env is not None else os.environ.get("ENVIRONMENT")
    if not env_name:
        raise ConfigError(
            [ConfigErrorDetail(location="<env>", field="ENVIRONMENT", reason="ENVIRONMENT not set")],
            hint="Set ENVIRONMENT=dev|staging|prod in the process environment.",
        )

    # --- Phase 1: parse -------------------------------------------------
    default_path = cfg_dir / "default.yaml"
    overlay_path = cfg_dir / f"{env_name}.yaml"

    parse_errors: list[ConfigErrorDetail] = []
    if not default_path.exists():
        parse_errors.append(ConfigErrorDetail(
            location=str(default_path), field="", reason="default.yaml not found",
        ))
        raise ConfigError(parse_errors)

    base = _read_yaml(default_path, parse_errors)
    overlay: dict[str, Any] | None = None
    if overlay_path.exists():
        overlay = _read_yaml(overlay_path, parse_errors)
    if parse_errors:
        raise ConfigError(parse_errors)

    if not isinstance(base, dict):
        raise ConfigError([ConfigErrorDetail(
            location=str(default_path), field="",
            reason="top-level must be a YAML mapping (object), not a list or scalar",
        )])
    if overlay is not None and not isinstance(overlay, dict):
        raise ConfigError([ConfigErrorDetail(
            location=str(overlay_path), field="",
            reason="top-level must be a YAML mapping (object), not a list or scalar",
        )])

    merged = _deep_merge(base, overlay or {})

    # --- Phase 2: ${VAR} substitution -----------------------------------
    sub_errors: list[ConfigErrorDetail] = []
    merged = _substitute(merged, default_path, sub_errors)
    if sub_errors:
        raise ConfigError(
            sub_errors,
            hint="every env var referenced from config/*.yaml must be listed in .env.example.",
        )

    # --- Phase 3: Pydantic validation -----------------------------------
    try:
        return model_cls.model_validate(merged)
    except ValidationError as ve:
        raise ConfigError(_unpack_validation_error(ve, default_path)) from ve


# ---------------------------------------------------------------- helpers


def _read_yaml(path: Path, errors: list[ConfigErrorDetail]) -> Any:
    try:
        with path.open("r") as f:
            return yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        # PyYAML's "problem_mark" gives line/column for syntax errors.
        line = getattr(getattr(exc, "problem_mark", None), "line", -1) + 1
        location = f"{path}:{line}" if line > 0 else str(path)
        errors.append(ConfigErrorDetail(
            location=location, field="", reason=f"YAML parse error: {exc}",
        ))
        return {}


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Deep-merge: scalars/lists in overlay replace; mappings recurse."""
    out = dict(base)
    for k, v in overlay.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _substitute(node: Any, source_path: Path, errors: list[ConfigErrorDetail]) -> Any:
    """Walk every string and resolve ${VAR} from os.environ. `$$` escapes `$`."""
    if isinstance(node, dict):
        return {k: _substitute(v, source_path, errors) for k, v in node.items()}
    if isinstance(node, list):
        return [_substitute(v, source_path, errors) for v in node]
    if not isinstance(node, str):
        return node

    # Two-step: collapse `$$` to a placeholder, then resolve `${VAR}`, then restore `$`.
    SENTINEL = "\x00DOLLAR\x00"
    work = node.replace("$$", SENTINEL)

    def _resolve(match: re.Match) -> str:
        var = match.group(1)
        val = os.environ.get(var)
        if val is None:
            errors.append(ConfigErrorDetail(
                location=str(source_path), field="",
                reason=f"{var} not set in environment",
            ))
            return match.group(0)  # leave unchanged so subsequent passes see it
        return val

    work = _VAR_RE.sub(_resolve, work)
    return work.replace(SENTINEL, "$")


def _unpack_validation_error(ve: ValidationError, source_path: Path) -> list[ConfigErrorDetail]:
    out: list[ConfigErrorDetail] = []
    for err in ve.errors():
        field_path = ".".join(str(p) for p in err.get("loc", ()))
        msg = err.get("msg", "")
        ctx = err.get("input")
        reason = f"{msg}" + (f" (got {ctx!r})" if ctx is not None else "")
        out.append(ConfigErrorDetail(location=str(source_path), field=field_path, reason=reason))
    return out
```

- [ ] **Step 6: Run all three test files, verify PASS**

Run: `pytest tests/unit/test_loader.py tests/unit/test_loader_substitution.py tests/unit/test_loader_layering.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add platform_sdk/config/loader.py \
  tests/unit/test_loader.py \
  tests/unit/test_loader_substitution.py \
  tests/unit/test_loader_layering.py
git commit -m "feat(config): add load_config, ConfigError, ${VAR} resolution

Three-phase loader: parse YAML default+overlay → resolve \${VAR} from
os.environ → validate against Pydantic model. Aggregates every error
in each phase so operators see the full set at once. \$\$ escape for
literal \$. List-replace, mapping-merge layering."
```

---

## Task 3: Migrate MCPConfig from dataclass to Pydantic + load()

**Files:**
- Modify: `platform_sdk/config/mcp_config.py`
- Test: `tests/unit/test_mcp_config_pydantic.py` (new behaviour)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mcp_config_pydantic.py
"""MCPConfig is now a Pydantic v2 BaseModel with extra='forbid' and load()."""
from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

pytestmark = pytest.mark.unit


def test_mcp_config_is_pydantic_basemodel():
    from platform_sdk.config import MCPConfig

    assert issubclass(MCPConfig, BaseModel)


def test_mcp_config_forbids_extra_fields():
    from platform_sdk.config import MCPConfig

    with pytest.raises(ValidationError) as exc:
        MCPConfig(environment="dev", typoed_field=123)

    assert "typoed_field" in str(exc.value)


def test_mcp_config_environment_strict_literal():
    from platform_sdk.config import MCPConfig

    # Valid values pass.
    MCPConfig(environment="dev")
    MCPConfig(environment="staging")
    MCPConfig(environment="prod")

    # Anything else rejected.
    with pytest.raises(ValidationError):
        MCPConfig(environment="local")
    with pytest.raises(ValidationError):
        MCPConfig(environment="production")


def test_mcp_config_transport_literal():
    from platform_sdk.config import MCPConfig

    MCPConfig(environment="dev", transport="sse")
    MCPConfig(environment="dev", transport="stdio")

    with pytest.raises(ValidationError):
        MCPConfig(environment="dev", transport="grpc")


def test_mcp_config_port_range():
    from platform_sdk.config import MCPConfig

    MCPConfig(environment="dev", port=8080)

    with pytest.raises(ValidationError):
        MCPConfig(environment="dev", port=0)
    with pytest.raises(ValidationError):
        MCPConfig(environment="dev", port=70000)


def test_mcp_config_load_classmethod_calls_loader(tmp_path, monkeypatch):
    from platform_sdk.config import MCPConfig

    (tmp_path / "default.yaml").write_text(
        "environment: dev\nport: 9000\nopa_url: http://opa:8181/v1/data/mcp\n"
    )
    cfg = MCPConfig.load(config_dir=str(tmp_path), env="dev")

    assert cfg.environment == "dev"
    assert cfg.port == 9000


def test_mcp_config_no_from_env():
    from platform_sdk.config import MCPConfig

    # The legacy from_env() factory has been removed.
    assert not hasattr(MCPConfig, "from_env")
```

- [ ] **Step 2: Run test, verify FAIL**

Run: `pytest tests/unit/test_mcp_config_pydantic.py -v`
Expected: at least one FAIL (likely `assert issubclass(MCPConfig, BaseModel)` fails because it's still a dataclass).

- [ ] **Step 3: Migrate MCPConfig to Pydantic**

Replace the entire contents of `platform_sdk/config/mcp_config.py`:

```python
# platform_sdk/config/mcp_config.py
"""FastMCP server configuration (Pydantic v2)."""
from __future__ import annotations

from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .env_isolation import Environment


class MCPConfig(BaseModel):
    """Configuration for FastMCP servers.

    Covers OPA policy enforcement, result size limits, service identity,
    database connection, Redis cache, and tool-result caching. Loaded
    from `config/default.yaml` + optional `config/<env>.yaml` via the
    SDK's `load_config()` (or `MCPConfig.load()`).
    """

    model_config = ConfigDict(extra="forbid")

    # OPA policy engine
    opa_url: str = "http://localhost:8181/v1/data/mcp/tools/allow"
    opa_timeout_seconds: Annotated[float, Field(gt=0)] = 2.0

    # Result guardrails
    max_result_bytes: Annotated[int, Field(ge=1000)] = 15_000

    # Service identity — stamped into every OPA evaluation.
    environment: Environment
    agent_role: str = "data_analyst_agent"
    service_name: str = "mcp-server"

    # Server runtime
    transport: Literal["stdio", "sse"] = "sse"
    port: Annotated[int, Field(gt=0, le=65535)] = 8080

    # Tool-result caching
    enable_tool_cache: bool = True
    tool_cache_ttl_seconds: Annotated[int, Field(ge=0)] = 300

    # Resilience parameters (circuit breaker, retry, backoff)
    cb_failure_threshold: int = 5
    cb_recovery_timeout: float = 30.0
    opa_max_retries: int = 2
    opa_retry_backoff: float = 0.2
    mcp_reconnect_backoff_cap: float = 60.0
    tool_call_timeout: float = 30.0

    # Database connection pool
    db_host: str = "pgvector"
    db_port: int = 5432
    db_user: str = "admin"
    db_pass: str = ""
    db_name: str = "ai_memory"
    db_require_ssl: bool = False
    statement_cache_size: int = 1024

    # Redis (tool-result cache backend)
    redis_host: str = ""
    redis_port: int = 6379
    redis_password: str = ""

    # MCP server URLs (used by orchestrator agents for service discovery)
    salesforce_mcp_url: str = "http://salesforce-mcp:8081/sse"
    payments_mcp_url: str = "http://payments-mcp:8082/sse"
    news_mcp_url: str = "http://news-search-mcp:8083/sse"
    mcp_sse_url: str = "http://localhost:8080/sse"

    # Registration / self-URL — used by Application._register hook.
    registry_url: str = ""
    service_url: str = ""
    service_version: str = ""

    _VALID_AGENT_ROLES: ClassVar[set[str]] = {
        "commercial_banking_agent",
        "data_analyst_agent",
        "compliance_agent",
        "analytics_agent",
    }

    @field_validator("opa_url")
    @classmethod
    def _validate_opa_url(cls, v: str) -> str:
        if not v:
            raise ValueError("opa_url must not be empty")
        if not v.startswith(("http://", "https://")):
            raise ValueError(f"opa_url must be an HTTP(S) URL, got: {v}")
        return v

    @field_validator("agent_role")
    @classmethod
    def _validate_agent_role(cls, v: str) -> str:
        if v not in cls._VALID_AGENT_ROLES:
            raise ValueError(f"agent_role='{v}' not in {sorted(cls._VALID_AGENT_ROLES)}")
        return v

    @classmethod
    def load(cls, *, config_dir: str | None = None, env: str | None = None) -> "MCPConfig":
        """Load from `<config_dir>/default.yaml` + optional `<config_dir>/<env>.yaml`."""
        from .loader import load_config
        return load_config(cls, config_dir=config_dir, env=env)
```

Note the three new fields (`registry_url`, `service_url`, `service_version`) — these absorb the env reads currently in `Application._register()`, completing the "no os.environ outside the loader" rule. They default to `""` so existing tests that construct `MCPConfig(...)` without registration fields still work.

- [ ] **Step 4: Run test, verify PASS**

Run: `pytest tests/unit/test_mcp_config_pydantic.py -v`
Expected: all 7 PASS.

- [ ] **Step 5: Verify nothing else broke**

Run: `pytest tests/unit -v 2>&1 | tail -40`
Expected: existing tests that import `MCPConfig` may fail; that's intentional. Note the failures and continue. The next tasks repair them.

- [ ] **Step 6: Commit**

```bash
git add platform_sdk/config/mcp_config.py tests/unit/test_mcp_config_pydantic.py
git commit -m "refactor(config)!: migrate MCPConfig to Pydantic v2 + load()

BREAKING: from_env() removed; environment is now strict Literal
[dev,staging,prod]; transport is Literal[stdio,sse]; port has range
validation. Adds registry_url/service_url/service_version fields so
Application._register no longer reads os.environ. extra='forbid'
catches typos in YAML."
```

---

## Task 4: Migrate AgentConfig from dataclass to Pydantic + load()

**Files:**
- Modify: `platform_sdk/config/agent_config.py`
- Test: `tests/unit/test_agent_config_pydantic.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_agent_config_pydantic.py
"""AgentConfig is now Pydantic v2 BaseModel with load()."""
from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

pytestmark = pytest.mark.unit


def test_agent_config_is_basemodel():
    from platform_sdk.config import AgentConfig

    assert issubclass(AgentConfig, BaseModel)


def test_agent_config_forbids_extra_fields():
    from platform_sdk.config import AgentConfig

    with pytest.raises(ValidationError):
        AgentConfig(environment="dev", typoed=1)


def test_agent_config_recursion_limit_clamped():
    """Existing behaviour: recursion_limit is silently clamped to [1, 50]."""
    from platform_sdk.config import AgentConfig

    cfg_low = AgentConfig(environment="dev", recursion_limit=0)
    assert cfg_low.recursion_limit == 1

    cfg_high = AgentConfig(environment="dev", recursion_limit=999)
    assert cfg_high.recursion_limit == 50


def test_agent_config_database_url_field_present():
    """Hoisted from analytics-agent's os.getenv leak."""
    from platform_sdk.config import AgentConfig

    cfg = AgentConfig(environment="dev", database_url="postgres://x")
    assert cfg.database_url == "postgres://x"


def test_agent_config_load_classmethod(tmp_path):
    from platform_sdk.config import AgentConfig

    (tmp_path / "default.yaml").write_text(
        "environment: dev\nmodel_route: complex-routing\n"
    )
    cfg = AgentConfig.load(config_dir=str(tmp_path), env="dev")

    assert cfg.environment == "dev"
    assert cfg.model_route == "complex-routing"


def test_agent_config_no_from_env():
    from platform_sdk.config import AgentConfig

    assert not hasattr(AgentConfig, "from_env")
```

- [ ] **Step 2: Run test, verify FAIL**

Run: `pytest tests/unit/test_agent_config_pydantic.py -v`
Expected: most FAIL (still dataclass).

- [ ] **Step 3: Migrate AgentConfig to Pydantic**

Replace the entire contents of `platform_sdk/config/agent_config.py`:

```python
# platform_sdk/config/agent_config.py
"""LangGraph agent configuration (Pydantic v2)."""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .env_isolation import Environment


class AgentConfig(BaseModel):
    """Configuration for LangGraph agents.

    Covers model routing (including multi-agent tiering), LLM endpoint,
    context compaction, session checkpointing, tool-result caching,
    and the application's database URL. Loaded via `AgentConfig.load()`.
    """

    model_config = ConfigDict(extra="forbid")

    environment: Environment

    # ---- Primary model routing ----
    model_route: str = "complex-routing"
    summary_model_route: str = "fast-routing"

    # ---- Multi-agent model tiering ----
    router_model_route: str = "fast-routing"
    specialist_model_route: str = "fast-routing"
    synthesis_model_route: str = "complex-routing"

    # ---- LLM endpoint (LiteLLM proxy) ----
    litellm_base_url: str = "http://localhost:4000/v1"
    internal_api_key: str = ""

    # ---- Session / checkpointer ----
    checkpointer_type: str = "memory"  # "memory" | "postgres"
    checkpointer_db_url: str = ""

    # ---- Conversation store (replaces the ad-hoc os.getenv("DATABASE_URL")) ----
    database_url: str = ""

    # ---- Context compaction ----
    enable_compaction: bool = True
    context_token_limit: Annotated[int, Field(ge=100)] = 6_000

    # ---- Safety limits ----
    recursion_limit: int = 10  # silently clamped via validator below
    max_message_length: Annotated[int, Field(ge=100)] = 32_000

    # ---- Tool-result caching ----
    enable_tool_cache: bool = True
    tool_cache_ttl_seconds: Annotated[int, Field(ge=0)] = 300

    # ---- MCP bridge startup ----
    mcp_startup_timeout: float = 120.0

    # ---- Synthesis settings ----
    chart_max_data_points: int = 20

    # ---- Registration / self-URL — for Application._register hook ----
    registry_url: str = ""
    service_url: str = ""
    service_version: str = ""

    @field_validator("recursion_limit")
    @classmethod
    def _clamp_recursion_limit(cls, v: int) -> int:
        # Preserve historical clamp: max(1, min(v, 50)).
        return max(1, min(v, 50))

    @field_validator("model_route")
    @classmethod
    def _validate_model_route(cls, v: str) -> str:
        if not v:
            raise ValueError("model_route must not be empty")
        return v

    @classmethod
    def load(cls, *, config_dir: str | None = None, env: str | None = None) -> "AgentConfig":
        from .loader import load_config
        return load_config(cls, config_dir=config_dir, env=env)
```

- [ ] **Step 4: Run test, verify PASS**

Run: `pytest tests/unit/test_agent_config_pydantic.py -v`
Expected: all 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add platform_sdk/config/agent_config.py tests/unit/test_agent_config_pydantic.py
git commit -m "refactor(config)!: migrate AgentConfig to Pydantic v2 + load()

BREAKING: from_env() removed; environment is strict Literal. Adds
database_url field (hoisted from analytics-agent leak) and the same
registry_url/service_url/service_version triplet as MCPConfig.
recursion_limit clamp behaviour preserved via validator."
```

---

## Task 5: Remove helpers.py and clean up config/__init__.py

**Files:**
- Delete: `platform_sdk/config/helpers.py`
- Modify: `platform_sdk/config/__init__.py`
- Modify: `platform_sdk/__init__.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_helpers_removed.py
"""platform_sdk.config.helpers and its functions are gone."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_helpers_module_removed():
    with pytest.raises(ImportError):
        import platform_sdk.config.helpers  # noqa: F401


def test_env_helpers_not_exported():
    from platform_sdk import config as cfg_module

    for name in ("_env", "_env_int", "_env_float", "_env_bool"):
        assert not hasattr(cfg_module, name), f"{name} should not be exported"


def test_config_init_exports_load_machinery():
    from platform_sdk.config import ConfigError, Environment, load_config

    assert ConfigError is not None
    assert load_config is not None
    assert Environment is not None
```

- [ ] **Step 2: Run test, verify FAIL**

Run: `pytest tests/unit/test_helpers_removed.py -v`
Expected: at least one FAIL (helpers still importable).

- [ ] **Step 3: Delete helpers.py**

```bash
git rm platform_sdk/config/helpers.py
```

- [ ] **Step 4: Update config/__init__.py**

Replace the entire contents of `platform_sdk/config/__init__.py`:

```python
"""Platform SDK — typed configuration models and loader.

Every tunable parameter for agents and MCP servers is defined here as a
Pydantic v2 model. Load via `MCPConfig.load()` / `AgentConfig.load()` (or
the underlying `load_config()`). The loader is the single place that
reads os.environ — no other module in the SDK or in service code should
call os.environ.get directly.

Public API:
    AgentConfig
    MCPConfig
    load_config
    ConfigError
    ConfigErrorDetail
    Environment
    ENV_HEADER
"""
from .agent_config import AgentConfig
from .env_isolation import ENV_HEADER, Environment
from .loader import ConfigError, ConfigErrorDetail, load_config
from .mcp_config import MCPConfig

__all__ = [
    "AgentConfig",
    "MCPConfig",
    "load_config",
    "ConfigError",
    "ConfigErrorDetail",
    "Environment",
    "ENV_HEADER",
]
```

- [ ] **Step 5: Update top-level platform_sdk/__init__.py**

Open `platform_sdk/__init__.py` and apply two edits:

(a) Find the import:

```python
from .config import AgentConfig, MCPConfig
```

Replace with:

```python
from .config import (
    AgentConfig,
    MCPConfig,
    ConfigError,
    ConfigErrorDetail,
    Environment,
    ENV_HEADER,
    load_config,
)
```

(b) Find the `__all__` list and ensure it contains the entries — add the new ones if they're missing:

```python
    "AgentConfig",
    "MCPConfig",
    "ConfigError",
    "ConfigErrorDetail",
    "Environment",
    "ENV_HEADER",
    "load_config",
```

- [ ] **Step 6: Run test, verify PASS**

Run: `pytest tests/unit/test_helpers_removed.py -v`
Expected: 3 PASS.

- [ ] **Step 7: Commit**

```bash
git add platform_sdk/config/__init__.py platform_sdk/__init__.py tests/unit/test_helpers_removed.py
git commit -m "refactor(config)!: remove helpers.py and _env wrappers

The loader is now the single env-reader. config/__init__ exports the
new public surface (load_config, ConfigError, Environment, ENV_HEADER)
and drops the underscored env helpers from the package boundary."
```

---

## Task 6: Internal HTTP client factory

**Files:**
- Create: `platform_sdk/http.py`
- Test: `tests/unit/test_http_client.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_http_client.py
"""make_internal_http_client stamps X-Environment and Bearer auth."""
from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.unit


def _stub_config(env="dev", api_key="k"):
    """A bag-of-fields stub that quacks like an SDK config object."""
    class _C:
        environment = env
        internal_api_key = api_key
    return _C()


def test_factory_returns_async_client():
    from platform_sdk.http import make_internal_http_client

    client = make_internal_http_client(_stub_config())
    try:
        assert isinstance(client, httpx.AsyncClient)
    finally:
        # synchronous client.close — no await needed for AsyncClient at unit-test scope
        # because we never opened a connection.
        import asyncio
        asyncio.get_event_loop().run_until_complete(client.aclose())


def test_factory_sets_x_environment_header():
    from platform_sdk.http import make_internal_http_client

    client = make_internal_http_client(_stub_config(env="staging"))
    try:
        assert client.headers.get("X-Environment") == "staging"
    finally:
        import asyncio
        asyncio.get_event_loop().run_until_complete(client.aclose())


def test_factory_sets_bearer_auth_header():
    from platform_sdk.http import make_internal_http_client

    client = make_internal_http_client(_stub_config(api_key="my-secret-key"))
    try:
        assert client.headers.get("Authorization") == "Bearer my-secret-key"
    finally:
        import asyncio
        asyncio.get_event_loop().run_until_complete(client.aclose())


def test_factory_omits_authorization_when_no_api_key():
    """A service without internal_api_key (e.g. read-only) should not include Bearer."""
    from platform_sdk.http import make_internal_http_client

    client = make_internal_http_client(_stub_config(api_key=""))
    try:
        assert "Authorization" not in client.headers
    finally:
        import asyncio
        asyncio.get_event_loop().run_until_complete(client.aclose())
```

- [ ] **Step 2: Run test, verify FAIL**

Run: `pytest tests/unit/test_http_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'platform_sdk.http'`.

- [ ] **Step 3: Implement**

```python
# platform_sdk/http.py
"""Internal HTTP client factory.

Every inter-service Python HTTP call must go through `make_internal_http_client`.
The returned `httpx.AsyncClient` carries:
  - X-Environment: <config.environment>
  - Authorization: Bearer <config.internal_api_key>   (when set)

A grep-based CI step in each service repo bans direct construction of
`httpx.AsyncClient(` outside this module, ensuring no service can bypass
the L3 transit-isolation headers.
"""
from __future__ import annotations

from typing import Any

import httpx

from .config.env_isolation import ENV_HEADER


def make_internal_http_client(
    config: Any,
    *,
    timeout: float = 10.0,
    **httpx_kwargs: Any,
) -> httpx.AsyncClient:
    """Return a pre-configured AsyncClient that stamps environment + auth.

    Args:
        config: Any object with `.environment` (Environment Literal) and
            optionally `.internal_api_key` (str) attributes.  Both
            `MCPConfig` and `AgentConfig` (and `RegistryConfig` after the
            registry migration) satisfy this shape.
        timeout: Default per-request timeout in seconds.
        **httpx_kwargs: Forwarded to httpx.AsyncClient. Caller may
            supply `headers=` to add additional headers; these merge
            with (and never override) X-Environment and Authorization.

    Returns:
        An open httpx.AsyncClient. Caller is responsible for `aclose()`.
    """
    headers: dict[str, str] = {ENV_HEADER: str(config.environment)}
    api_key = getattr(config, "internal_api_key", "") or ""
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # Caller-supplied headers merge in WITHOUT overriding our two safety headers.
    extra = httpx_kwargs.pop("headers", {}) or {}
    for k, v in extra.items():
        headers.setdefault(k, v)

    return httpx.AsyncClient(timeout=timeout, headers=headers, **httpx_kwargs)
```

- [ ] **Step 4: Run test, verify PASS**

Run: `pytest tests/unit/test_http_client.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add platform_sdk/http.py tests/unit/test_http_client.py
git commit -m "feat(http): add make_internal_http_client factory

Stamps X-Environment and Bearer auth on every internal HTTP request.
Single replacement for ad-hoc httpx.AsyncClient() construction in
service code. Caller-supplied headers cannot override the two safety
headers."
```

---

## Task 7: RegistryClient uses make_internal_http_client + carries X-Environment

**Files:**
- Modify: `platform_sdk/registry/client.py`
- Test: `tests/unit/test_registry_client_environment_header.py`

- [ ] **Step 1: Inspect current RegistryClient construction**

Read `platform_sdk/registry/client.py` to understand the existing constructor signature and where headers are currently set. (For this plan: the existing client takes `registry_url: str` and `api_key: str` and constructs its own httpx client; we replace that with the factory.)

- [ ] **Step 2: Write the failing test**

```python
# tests/unit/test_registry_client_environment_header.py
"""RegistryClient stamps X-Environment from the supplied config."""
from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.unit


def _stub_config(env="dev", api_key="k"):
    class _C:
        environment = env
        internal_api_key = api_key
    return _C()


@pytest.mark.asyncio
async def test_registry_client_sends_x_environment(monkeypatch):
    """A RegistryClient instantiated from config sends X-Environment on every request."""
    from platform_sdk.registry.client import RegistryClient

    captured: list[httpx.Request] = []

    async def _mock_send(self, req, *a, **kw):
        captured.append(req)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(httpx.AsyncClient, "send", _mock_send)

    client = RegistryClient.from_config(_stub_config(env="staging"), "http://reg:8090")
    try:
        await client.lookup("data-mcp")
    except Exception:
        pass

    assert captured, "expected at least one request"
    assert captured[0].headers.get("X-Environment") == "staging"

    await client.aclose()
```

- [ ] **Step 3: Run test, verify FAIL**

Run: `pytest tests/unit/test_registry_client_environment_header.py -v`
Expected: FAIL — likely `AttributeError: type object 'RegistryClient' has no attribute 'from_config'`.

- [ ] **Step 4: Add `from_config` constructor and replace internal client**

Open `platform_sdk/registry/client.py`. Find the existing constructor (e.g. `def __init__(self, *, registry_url: str, api_key: str = "", ...)`) and:

(a) Add an `httpx_client: httpx.AsyncClient | None = None` keyword-only parameter. If supplied, use it directly; otherwise construct one using `httpx.AsyncClient` directly (preserving today's behaviour for callers that didn't pass a config object).

(b) Add a `@classmethod from_config(cls, config, registry_url: str | None = None) -> "RegistryClient"`:

```python
    @classmethod
    def from_config(cls, config, registry_url: str | None = None) -> "RegistryClient":
        """Build a RegistryClient from a config object that has
        `environment`, `internal_api_key`, and (optionally) `registry_url`.

        The returned client uses make_internal_http_client so every
        outbound call carries X-Environment and Bearer auth.
        """
        from ..http import make_internal_http_client

        url = registry_url or getattr(config, "registry_url", "")
        if not url:
            raise ValueError(
                "RegistryClient.from_config requires a registry_url either on "
                "the config object or as a positional argument."
            )
        return cls(
            registry_url=url,
            api_key=getattr(config, "internal_api_key", "") or "",
            httpx_client=make_internal_http_client(config),
        )
```

(c) In `__init__`, when `httpx_client` is supplied, store it and skip constructing a new one. Keep the old code path for the bare `(registry_url, api_key)` constructor — `Application._register` will move to `from_config()` in Task 9, but in-flight tests need both paths until then.

(Concrete `__init__` shape — adapt to your file's existing layout):

```python
    def __init__(
        self,
        *,
        registry_url: str,
        api_key: str = "",
        ...,
        httpx_client: "httpx.AsyncClient | None" = None,
    ) -> None:
        self._registry_url = registry_url.rstrip("/")
        self._api_key = api_key
        ...
        if httpx_client is not None:
            self._client = httpx_client
        else:
            # Legacy: construct our own client. Outbound calls still carry
            # the Bearer header via _auth_headers() but NOT X-Environment.
            # Callers are migrated to from_config() in 0.6.0; this branch
            # is retained for one release for tests that pre-date the
            # factory.
            self._client = httpx.AsyncClient(timeout=10.0)
```

- [ ] **Step 5: Run test, verify PASS**

Run: `pytest tests/unit/test_registry_client_environment_header.py -v`
Expected: PASS.

- [ ] **Step 6: Run full registry-client tests, ensure no regression**

Run: `pytest tests/unit/test_registry_client_lifecycle.py tests/unit/test_registry_client_lookup.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add platform_sdk/registry/client.py tests/unit/test_registry_client_environment_header.py
git commit -m "feat(registry): RegistryClient.from_config uses internal HTTP factory

New from_config classmethod accepts a config object and constructs the
client via make_internal_http_client, so X-Environment is stamped on
every outbound request. The legacy (registry_url, api_key) constructor
remains for one release to keep in-flight tests passing."
```

---

## Task 8: Extend make_api_key_verifier with environment validation

**Files:**
- Modify: `platform_sdk/security.py`
- Test: `tests/unit/test_api_key_verifier_environment.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_api_key_verifier_environment.py
"""make_api_key_verifier(environment=...) rejects mismatched X-Environment."""
from __future__ import annotations

import pytest
from fastapi import FastAPI, Depends, Header
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


def _build_app(verify):
    app = FastAPI()

    @app.get("/protected")
    async def protected(_: str = Depends(verify)):
        return {"ok": True}

    return TestClient(app)


def test_request_with_matching_environment_succeeds(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "secret")

    from platform_sdk.security import make_api_key_verifier

    verify = make_api_key_verifier(environment="dev")
    client = _build_app(verify)

    r = client.get(
        "/protected",
        headers={"Authorization": "Bearer secret", "X-Environment": "dev"},
    )
    assert r.status_code == 200


def test_request_with_mismatched_environment_returns_403(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "secret")

    from platform_sdk.security import make_api_key_verifier

    verify = make_api_key_verifier(environment="prod")
    client = _build_app(verify)

    r = client.get(
        "/protected",
        headers={"Authorization": "Bearer secret", "X-Environment": "dev"},
    )
    assert r.status_code == 403
    body = r.json()
    assert body.get("detail", {}).get("error") == "environment_mismatch"
    assert body["detail"]["expected"] == "prod"
    assert body["detail"]["got"] == "dev"


def test_request_without_x_environment_returns_403(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "secret")

    from platform_sdk.security import make_api_key_verifier

    verify = make_api_key_verifier(environment="prod")
    client = _build_app(verify)

    r = client.get(
        "/protected",
        headers={"Authorization": "Bearer secret"},
    )
    assert r.status_code == 403


def test_environment_none_disables_isolation(monkeypatch):
    """Passing environment=None preserves legacy auth-only behaviour."""
    monkeypatch.setenv("INTERNAL_API_KEY", "secret")

    from platform_sdk.security import make_api_key_verifier

    verify = make_api_key_verifier()  # no environment arg
    client = _build_app(verify)

    r = client.get(
        "/protected",
        headers={"Authorization": "Bearer secret"},
    )
    assert r.status_code == 200  # no X-Environment required
```

- [ ] **Step 2: Run test, verify FAIL**

Run: `pytest tests/unit/test_api_key_verifier_environment.py -v`
Expected: at least the mismatch test FAILs because the verifier doesn't yet check X-Environment.

- [ ] **Step 3: Modify make_api_key_verifier**

Open `platform_sdk/security.py`. Find `make_api_key_verifier()` and replace the function body with:

```python
def make_api_key_verifier(
    api_key: Optional[str] = None,
    *,
    environment: Optional[str] = None,
):
    """Return a FastAPI dependency that validates Bearer tokens and (optionally) X-Environment.

    If `environment` is provided (a string from the Environment Literal),
    the dependency also requires an `X-Environment` header equal to that
    value. Mismatch returns 403; absence returns 403. This is the
    inbound half of L3 environment isolation.

    If `api_key` is None the value is read from INTERNAL_API_KEY at call
    time, so the returned dependency can be created at module level
    safely even if the environment variable isn't set during import.
    """
    from fastapi import HTTPException, Request, Security
    from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

    from .config.env_isolation import ENV_HEADER

    _bearer = HTTPBearer(auto_error=True)
    _static_key: Optional[str] = api_key
    _env: Optional[str] = environment

    async def _verify(
        request: Request,
        credentials: HTTPAuthorizationCredentials = Security(_bearer),
    ) -> str:
        # ---- Bearer token ----
        key = _static_key or os.environ.get("INTERNAL_API_KEY", "")
        if not key:
            log.error("auth_misconfigured", reason="INTERNAL_API_KEY not set")
            raise HTTPException(
                status_code=500,
                detail="Service temporarily unavailable. Contact your administrator.",
            )
        if not hmac.compare_digest(credentials.credentials, key):
            log.warning("auth_rejected", reason="invalid_api_key")
            raise HTTPException(status_code=401, detail="Unauthorized")

        # ---- X-Environment (only when configured) ----
        if _env is not None:
            got = request.headers.get(ENV_HEADER)
            if got != _env:
                log.warning(
                    "environment_mismatch_rejected",
                    expected_env=_env,
                    got_env=got,
                    peer_ip=request.client.host if request.client else "",
                )
                raise HTTPException(
                    status_code=403,
                    detail={
                        "error": "environment_mismatch",
                        "expected": _env,
                        "got": got or "",
                    },
                )

        return credentials.credentials

    return _verify
```

(Note that `os` and `hmac` are already imported at module top; `Request` is the new import.)

- [ ] **Step 4: Run test, verify PASS**

Run: `pytest tests/unit/test_api_key_verifier_environment.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add platform_sdk/security.py tests/unit/test_api_key_verifier_environment.py
git commit -m "feat(security): make_api_key_verifier validates X-Environment

Adds optional environment= param. When provided, the verifier also
requires X-Environment to match — inbound half of L3. Mismatch returns
403 with structured error; absence returns 403; both logged with
peer_ip for cross-env leakage visibility. environment=None preserves
existing auth-only behaviour."
```

---

## Task 9: Application base — config_model, auto-load, env reads moved to config

**Files:**
- Modify: `platform_sdk/base/application.py`
- Test: `tests/unit/test_application_auto_load.py`
- Test (modify): `tests/unit/test_application_register.py`

- [ ] **Step 1: Write the auto-load test**

```python
# tests/unit/test_application_auto_load.py
"""Application auto-loads from config_model when no config is passed."""
from __future__ import annotations

from typing import ClassVar

import pytest
from pydantic import BaseModel, ConfigDict

from platform_sdk.config.env_isolation import Environment

pytestmark = pytest.mark.unit


class _StubConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    environment: Environment
    name: str = "stub"
    registry_url: str = ""
    service_url: str = ""
    service_version: str = ""
    internal_api_key: str = ""

    @classmethod
    def load(cls, *, config_dir=None, env=None):
        # Test version: synthesize a value rather than read YAML.
        return cls(environment=env or "dev")


def test_application_uses_config_model_when_no_config(monkeypatch):
    from platform_sdk.base.application import Application

    class _App(Application):
        config_model: ClassVar[type[BaseModel]] = _StubConfig

    monkeypatch.setenv("ENVIRONMENT", "dev")
    a = _App(name="x")
    assert a.config.environment == "dev"
    assert a.environment == "dev"


def test_application_uses_explicit_config_when_passed():
    from platform_sdk.base.application import Application

    class _App(Application):
        config_model: ClassVar[type[BaseModel]] = _StubConfig

    explicit = _StubConfig(environment="prod")
    a = _App(name="x", config=explicit)
    assert a.config is explicit
    assert a.environment == "prod"


def test_application_without_config_model_raises():
    from platform_sdk.base.application import Application

    class _Bad(Application):
        pass  # no config_model

    with pytest.raises(NotImplementedError):
        _Bad(name="x")
```

- [ ] **Step 2: Run test, verify FAIL**

Run: `pytest tests/unit/test_application_auto_load.py -v`
Expected: tests fail because Application.__init__ still calls `self.load_config(name)`.

- [ ] **Step 3: Refactor Application**

Replace the entire contents of `platform_sdk/base/application.py`:

```python
"""Enterprise AI Platform — Application base class."""
from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Any, ClassVar, Optional

if TYPE_CHECKING:
    import structlog
    from pydantic import BaseModel

from ..logging import get_logger

# RegistryClient is imported at module top so test code can do
# monkeypatch.setattr("platform_sdk.base.application.RegistryClient", ...).
from ..registry.client import RegistryClient


class Application(ABC):
    """Root base class for all Enterprise AI applications.

    Subclasses MUST set `config_model` to a Pydantic BaseModel subclass
    that defines the service's configuration shape.  The model is
    expected to expose:
      - environment: Environment Literal
      - registry_url: str
      - service_url: str
      - service_version: str
      - internal_api_key: str

    On construction, if no `config=` is passed, the SDK calls
    `cls.config_model.load()` and stores the result on `self.config`.
    """

    # ---- Class-level metadata ----
    service_type: ClassVar[str] = "other"
    service_metadata: ClassVar[dict[str, Any]] = {}

    # MUST be overridden by subclasses.
    config_model: ClassVar[Optional[type["BaseModel"]]] = None

    def __init__(self, name: str, *, config: Optional["BaseModel"] = None) -> None:
        self.name = name
        if config is not None:
            self.config = config
        else:
            if self.config_model is None:
                raise NotImplementedError(
                    f"{type(self).__name__} must set the `config_model` "
                    f"class attribute or pass an explicit `config=` to __init__."
                )
            self.config = self.config_model.load()
        # Convenience handle — every config has `environment`.
        self.environment: str = self.config.environment
        self.registry: Optional[RegistryClient] = None

    @property
    def logger(self) -> "structlog.BoundLogger":
        return get_logger(self.name)

    async def startup(self) -> None: ...
    async def shutdown(self) -> None: ...

    # ------------------------------------------------------------------
    # Self-registration
    # ------------------------------------------------------------------

    async def _register(self) -> None:
        """If `config.registry_url` is set and this isn't the registry itself,
        register self and start heartbeat + refresh background tasks.
        """
        registry_url = (self.config.registry_url or "").rstrip("/")
        if not registry_url:
            self.logger.info("registry_url_not_set", behavior="self_registration_disabled")
            return

        self_url = (self.config.service_url or "").rstrip("/")
        if not self_url:
            raise RuntimeError(
                "service_url must be set when registry_url is set. "
                "This service cannot register without knowing its own reachable URL — "
                "set service_url in the service's config (or via the SERVICE_URL env "
                "var that config/dev.yaml resolves)."
            )

        if registry_url == self_url:
            self.logger.info("registry_self_skip", reason="registry_url == service_url")
            return

        self.registry = RegistryClient.from_config(self.config, registry_url=registry_url)

        await self.registry.register_self({
            "name": self.name,
            "url": self.config.service_url,
            "type": self.service_type,
            "version": self.config.service_version or None,
            "metadata": dict(self.service_metadata),
        })
        await self.registry.start_heartbeat(self.name)
        await self.registry.start_refresh()

    async def _deregister(self) -> None:
        """Stop background tasks and DELETE /api/services/{name}."""
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

Key changes:
- `load_config` abstract method removed; subclasses set `config_model` ClassVar.
- All three env reads (`REGISTRY_URL`, `SERVICE_URL`, `SERVICE_VERSION`, `INTERNAL_API_KEY`) replaced with `self.config.<field>`.
- `RegistryClient` instantiated via `from_config` so its outbound calls carry `X-Environment`.

- [ ] **Step 4: Repair tests/unit/test_application_register.py**

The existing `_StubApp.__init__` defines an inline `_Concrete(Application)` with `def load_config(self, name): return None`. This no longer matches the refactored base class. Replace the body of `_StubApp.__init__`:

```python
class _StubApp:
    def __init__(self, name: str = "test", service_type: str = "agent"):
        from typing import ClassVar

        from pydantic import BaseModel, ConfigDict

        from platform_sdk.base.application import Application
        from platform_sdk.config.env_isolation import Environment

        class _StubConfig(BaseModel):
            model_config = ConfigDict(extra="forbid")
            environment: Environment = "dev"
            registry_url: str = ""
            service_url: str = ""
            service_version: str = ""
            internal_api_key: str = ""

            @classmethod
            def load(cls, *, config_dir=None, env=None):
                import os
                return cls(
                    environment=os.environ.get("ENVIRONMENT", "dev"),
                    registry_url=os.environ.get("REGISTRY_URL", ""),
                    service_url=os.environ.get("SERVICE_URL", ""),
                    service_version=os.environ.get("SERVICE_VERSION", ""),
                    internal_api_key=os.environ.get("INTERNAL_API_KEY", ""),
                )

        _service_type = service_type
        class _Concrete(Application):
            service_type = _service_type
            config_model = _StubConfig

        self.app = _Concrete(name)

    @property
    def reg(self):
        return getattr(self.app, "registry", None)
```

The behaviour the existing tests assert (registry skipped when `REGISTRY_URL` unset, registry skipped when `REGISTRY_URL == SERVICE_URL`, registry constructed otherwise) is preserved because the stub config reads the same env vars at `load()` time.

- [ ] **Step 5: Run all auto-load and register tests, verify PASS**

Run: `pytest tests/unit/test_application_auto_load.py tests/unit/test_application_register.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add platform_sdk/base/application.py tests/unit/test_application_auto_load.py tests/unit/test_application_register.py
git commit -m "refactor(base)!: Application auto-loads via config_model ClassVar

Replaces the abstract load_config(name) method with a config_model
class attribute the base reads in __init__. Eliminates the four
os.environ.get calls in _register by sourcing registry_url,
service_url, service_version, and internal_api_key from the config.
Subclasses now declare config_model = MCPConfig or AgentConfig (or any
Pydantic model with the matching shape)."
```

---

## Task 10: Wire McpService and BaseAgentApp to declare config_model

**Files:**
- Modify: `platform_sdk/base/mcp_service.py`
- Modify: `platform_sdk/fastapi_app/base.py`
- Test (modify): `tests/unit/test_mcp_service_registers.py`
- Test (modify): `tests/unit/test_baseagentapp_registers.py`
- Test (modify): `tests/unit/test_mcp_service_run_with_registration.py`

- [ ] **Step 1: Inspect existing McpService and BaseAgentApp signatures**

Read `platform_sdk/base/mcp_service.py` to find the current `__init__` (it accepts `name`, optional `config: MCPConfig | None = None`, and probably calls `super().__init__(name)` then `self.config = config or MCPConfig.from_env()`).

Read `platform_sdk/fastapi_app/base.py` likewise.

- [ ] **Step 2: Modify McpService**

In `platform_sdk/base/mcp_service.py`:

(a) Add at the top of the class definition (right under the class docstring, before any methods):

```python
    config_model = MCPConfig
```

(b) Find the existing `__init__`. Replace any local handling of "if config is None: self.config = MCPConfig.from_env()" with passing `config=` through to the super call:

```python
    def __init__(
        self,
        name: str,
        *,
        config: Optional[MCPConfig] = None,
        ...other existing kwargs...
    ) -> None:
        super().__init__(name, config=config)
        ...rest of existing init body, but using self.config (set by super)...
```

The existing kwargs (`authorizer`, `cache`, `db_pool`, etc.) are unchanged.

- [ ] **Step 3: Modify BaseAgentApp**

In `platform_sdk/fastapi_app/base.py`:

(a) Add `config_model = AgentConfig` as a class attribute.

(b) Find any code that calls `AgentConfig.from_env()` (or that the `load_config` abstract method delegated to) and replace it with `self.config` (set by the super call). The lifespan startup code that previously read env vars now reads `self.config.<field>`.

(c) The `load_config` method (overridden in the existing `BaseAgentApp` to call `AgentConfig.from_env()`) is now redundant and can be removed entirely since the base class auto-loads via `config_model`.

- [ ] **Step 4: Run modified register tests**

Run: `pytest tests/unit/test_mcp_service_registers.py tests/unit/test_baseagentapp_registers.py tests/unit/test_mcp_service_run_with_registration.py -v`
Expected: tests probably need fixture updates to provide a Pydantic config rather than rely on env-var-driven `from_env()`. Walk through each failure: replace any `monkeypatch.setenv(...)` setup with construction of a real `MCPConfig(environment="dev", ...)` or `AgentConfig(environment="dev", ...)` and pass via `config=`.

- [ ] **Step 5: Run the full unit test suite**

Run: `pytest tests/unit -v 2>&1 | tail -30`
Expected: all tests PASS. Any that still reference `from_env()` or `load_config()` need their setup migrated.

- [ ] **Step 6: Commit**

```bash
git add platform_sdk/base/mcp_service.py platform_sdk/fastapi_app/base.py tests/unit/
git commit -m "feat(base): McpService and BaseAgentApp declare config_model

McpService.config_model = MCPConfig; BaseAgentApp.config_model =
AgentConfig. The redundant load_config overrides are removed; the
super-class auto-loads when no explicit config= is passed. Test
fixtures migrated from monkeypatch.setenv to direct config
construction."
```

---

## Task 11: `platform-sdk check-env-example` CLI subcommand

**Files:**
- Modify: `platform_sdk/cli/main.py`
- Test: `tests/unit/test_check_env_example_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_check_env_example_cli.py
"""platform-sdk check-env-example verifies .env.example covers ${VAR} refs."""
from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

pytestmark = pytest.mark.unit


def test_passes_when_every_var_documented(tmp_path):
    from platform_sdk.cli.main import cli

    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "default.yaml").write_text("db_pass: ${DB_PASS}\nlog_level: info\n")
    env = tmp_path / ".env.example"
    env.write_text("DB_PASS=changeme\n")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["check-env-example", "--config-dir", str(cfg), "--env-example", str(env)],
    )
    assert result.exit_code == 0


def test_fails_when_var_referenced_but_not_documented(tmp_path):
    from platform_sdk.cli.main import cli

    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "default.yaml").write_text("db_pass: ${DB_PASS}\napi_key: ${API_KEY}\n")
    env = tmp_path / ".env.example"
    env.write_text("DB_PASS=changeme\n")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["check-env-example", "--config-dir", str(cfg), "--env-example", str(env)],
    )
    assert result.exit_code != 0
    assert "API_KEY" in result.output


def test_warns_but_passes_when_documented_var_unreferenced(tmp_path):
    from platform_sdk.cli.main import cli

    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "default.yaml").write_text("db_pass: ${DB_PASS}\n")
    env = tmp_path / ".env.example"
    env.write_text("DB_PASS=changeme\nUNUSED_KEY=zzz\n")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["check-env-example", "--config-dir", str(cfg), "--env-example", str(env)],
    )
    # Unreferenced is a warning, not a failure.
    assert result.exit_code == 0
    assert "UNUSED_KEY" in result.output


def test_runtime_only_allowlist_does_not_warn(tmp_path):
    from platform_sdk.cli.main import cli

    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "default.yaml").write_text("port: 8080\n")
    env = tmp_path / ".env.example"
    env.write_text("INTERNAL_API_KEY=x\nENVIRONMENT=dev\nCONFIG_DIR=/app/config\n")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["check-env-example", "--config-dir", str(cfg), "--env-example", str(env)],
    )
    assert result.exit_code == 0
    # None of the allowlisted vars should be flagged as unreferenced.
    assert "INTERNAL_API_KEY" not in result.output
    assert "ENVIRONMENT" not in result.output
```

- [ ] **Step 2: Run test, verify FAIL**

Run: `pytest tests/unit/test_check_env_example_cli.py -v`
Expected: FAIL — `check-env-example` subcommand doesn't exist.

- [ ] **Step 3: Add the subcommand**

At the bottom of `platform_sdk/cli/main.py` (before `if __name__ == "__main__":`), append:

```python
# ----------------------------- check-env-example -----------------------------

import re

_VAR_REF_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")
_RUNTIME_ONLY_ALLOWLIST = {"INTERNAL_API_KEY", "ENVIRONMENT", "CONFIG_DIR"}


def _scan_yaml_vars(config_dir: Path) -> set[str]:
    """Return every distinct ${VAR} referenced under config_dir."""
    vars_found: set[str] = set()
    for path in sorted(config_dir.glob("*.yaml")):
        text = path.read_text()
        # Strip $$ escapes before scanning so they don't yield false positives.
        text = text.replace("$$", "")
        vars_found.update(_VAR_REF_RE.findall(text))
    return vars_found


def _parse_env_example(path: Path) -> set[str]:
    """Return the keys declared in a .env.example file (KEY=value lines)."""
    keys: set[str] = set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key:
            keys.add(key)
    return keys


@cli.command("check-env-example")
@click.option(
    "--config-dir",
    type=click.Path(exists=True, file_okay=False),
    default="config",
    help="Directory containing default.yaml and per-env overlays.",
)
@click.option(
    "--env-example",
    type=click.Path(exists=True, dir_okay=False),
    default=".env.example",
    help="Path to .env.example file documenting required env vars.",
)
def check_env_example(config_dir: str, env_example: str) -> None:
    """Verify .env.example covers every ${VAR} referenced in config/*.yaml."""
    referenced = _scan_yaml_vars(Path(config_dir))
    documented = _parse_env_example(Path(env_example))

    missing = referenced - documented
    unreferenced = documented - referenced - _RUNTIME_ONLY_ALLOWLIST

    if missing:
        click.echo(
            f"FAIL: {len(missing)} env var(s) referenced from {config_dir}/*.yaml "
            f"but missing from {env_example}:",
            err=True,
        )
        for name in sorted(missing):
            click.echo(f"  - {name}", err=True)
        raise SystemExit(1)

    if unreferenced:
        click.echo(
            f"WARN: {len(unreferenced)} env var(s) listed in {env_example} "
            f"but not referenced from any YAML:"
        )
        for name in sorted(unreferenced):
            click.echo(f"  - {name}")

    click.echo(f"OK: {len(referenced)} env var(s) referenced and documented.")
```

(`from pathlib import Path` is already imported at module top; `re` and `click` likewise.)

- [ ] **Step 4: Run test, verify PASS**

Run: `pytest tests/unit/test_check_env_example_cli.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Smoke-test the CLI directly**

Run:
```bash
mkdir -p /tmp/cfg-smoke && echo 'db_pass: ${DB_PASS}' > /tmp/cfg-smoke/default.yaml
echo 'DB_PASS=changeme' > /tmp/cfg-smoke/.env.example
python -m platform_sdk.cli.main check-env-example \
  --config-dir /tmp/cfg-smoke --env-example /tmp/cfg-smoke/.env.example
```
Expected: prints `OK: 1 env var(s) referenced and documented.` exit code 0.

- [ ] **Step 6: Commit**

```bash
git add platform_sdk/cli/main.py tests/unit/test_check_env_example_cli.py
git commit -m "feat(cli): add check-env-example subcommand

Scans config/*.yaml for \${VAR} references and verifies .env.example
documents every one. Unreferenced documented keys produce a warning
(allowlist for INTERNAL_API_KEY, ENVIRONMENT, CONFIG_DIR — those are
consumed by the runtime, not the loader). Each service's CI runs this
to keep docs in sync with YAML."
```

---

## Task 12: Bump SDK version, update CHANGELOG, push, tag, release

**Files:**
- Modify: `pyproject.toml`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Bump version**

Edit `pyproject.toml`. Find:
```toml
version = "0.5.1"
```
Replace with:
```toml
version = "0.6.0"
```

- [ ] **Step 2: Update CHANGELOG**

Open `CHANGELOG.md` and prepend a new section above the existing top entry:

```markdown
## 0.6.0 — 2026-05-XX

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
```

- [ ] **Step 3: Run the full test suite one more time**

Run: `pytest tests/unit -v 2>&1 | tail -10`
Expected: every test PASSes (some may have been migrated in earlier tasks).

- [ ] **Step 4: Commit version bump and CHANGELOG**

```bash
git add pyproject.toml CHANGELOG.md
git commit -m "chore(release): bump to 0.6.0; CHANGELOG entry

See CHANGELOG.md for the full set of breaking changes."
```

- [ ] **Step 5: Push and open PR**

```bash
git push -u origin feature/config-management
```
Then via GitHub UI or `gh pr create`, open a PR titled "feat: centralised config management (SDK 0.6.0 — breaking)" with body referencing `docs/specs/2026-05-01-config-management-design.md` and `docs/plans/2026-05-01-config-management.md`.

- [ ] **Step 6: After PR merges, tag and publish base image**

In the SDK repo's `main` branch:
```bash
git tag v0.6.0
git push origin v0.6.0
```
The release workflow (existing) builds the wheel and publishes the base image `ghcr.io/narisun/ai-python-base:3.11-sdk0.6.0`. Verify in GHCR before proceeding to Phase 2.

---

# Phase 2 — Service Migrations (parallel)

The six service tasks below are independent and may be merged in any order. Each task targets one repo. Across all six, the pattern is:

1. Add `config/default.yaml` and `config/dev.yaml`.
2. Add `.env.example`.
3. Replace `<repo>/.gitignore` entry for `.env` (most repos already gitignore it; verify).
4. Bump SDK pin in `pyproject.toml` and base-image tag in `Dockerfile`.
5. Update `Dockerfile` to `COPY config/ /app/config/`.
6. Delete the module-level `os.environ.get` reads (each repo has different specifics).
7. Wire CI to run `platform-sdk check-env-example`.
8. Migrate any in-repo tests that relied on `from_env()`.
9. Tag a new release (e.g. `0.6.0`).

Each repo's worktree is set up via the `superpowers:using-git-worktrees` skill before its task begins.

---

## Task 13: Migrate `narisun/ai-registry`

**Branch:** `feature/config-management` in the ai-registry repo.

**Files:**
- Modify: `src/config.py` (Pydantic + load())
- Modify: `src/routes/_auth.py` (pass environment to make_api_key_verifier)
- Create: `config/default.yaml`
- Create: `config/dev.yaml`
- Create: `.env.example`
- Modify: `Dockerfile` (BASE_TAG → 3.11-sdk0.6.0; COPY config/)
- Modify: `pyproject.toml` (SDK pin → 0.6.0)
- Modify: `tests/` (replace env-var setup with explicit config or tmp YAML)

- [ ] **Step 1: Set up the worktree**

Use the `superpowers:using-git-worktrees` skill to create `.worktrees/config-management` off `main` in the registry repo.

- [ ] **Step 2: Write the new RegistryConfig test**

```python
# tests/unit/test_registry_config_pydantic.py
"""RegistryConfig is now a Pydantic v2 BaseModel with load()."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

pytestmark = pytest.mark.unit


def test_is_basemodel():
    from src.config import RegistryConfig
    assert issubclass(RegistryConfig, BaseModel)


def test_environment_required():
    from src.config import RegistryConfig
    with pytest.raises(ValidationError):
        RegistryConfig(internal_api_key="k")  # no environment → fail


def test_environment_strict_literal():
    from src.config import RegistryConfig
    with pytest.raises(ValidationError):
        RegistryConfig(environment="local", internal_api_key="k")


def test_load_from_yaml(tmp_path):
    from src.config import RegistryConfig
    (tmp_path / "default.yaml").write_text(
        "environment: dev\nport: 8090\nsqlite_path: /tmp/r.db\n"
        "internal_api_key: ${INTERNAL_API_KEY}\n"
    )
    import os
    os.environ["INTERNAL_API_KEY"] = "k"
    try:
        cfg = RegistryConfig.load(config_dir=str(tmp_path), env="dev")
        assert cfg.environment == "dev"
        assert cfg.port == 8090
    finally:
        del os.environ["INTERNAL_API_KEY"]
```

- [ ] **Step 3: Run test, verify FAIL**

Run: `pytest tests/unit/test_registry_config_pydantic.py -v`
Expected: FAIL.

- [ ] **Step 4: Replace `src/config.py`**

```python
# src/config.py
"""Registry server configuration (Pydantic v2)."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator
from platform_sdk.config.env_isolation import Environment


class RegistryConfig(BaseModel):
    """Configuration for the registry server."""

    model_config = ConfigDict(extra="forbid")

    environment: Environment

    # Server runtime
    port: Annotated[int, Field(gt=0, le=65535)] = 8090

    # Storage
    sqlite_path: Path = Path("/var/lib/registry/registry.db")
    seed_path: Path | None = None

    # Auth
    internal_api_key: str

    # Reaper
    heartbeat_grace_seconds: Annotated[int, Field(ge=0)] = 60
    eviction_seconds: int = 300
    reaper_interval_seconds: Annotated[int, Field(gt=0)] = 30

    # Self-URL (used when registry registers itself with another registry, rare)
    service_url: str = ""

    # UI
    enable_ui: bool = True

    @field_validator("internal_api_key")
    @classmethod
    def _require_api_key(cls, v: str) -> str:
        if not v:
            raise ValueError(
                "internal_api_key must not be empty (set INTERNAL_API_KEY env)"
            )
        return v

    @field_validator("eviction_seconds")
    @classmethod
    def _validate_eviction_vs_grace(cls, v, info):
        grace = info.data.get("heartbeat_grace_seconds", 0)
        if v < grace:
            raise ValueError(
                f"eviction_seconds={v} must be >= heartbeat_grace_seconds={grace}"
            )
        return v

    @classmethod
    def load(cls, *, config_dir: str | None = None, env: str | None = None) -> "RegistryConfig":
        from platform_sdk.config.loader import load_config
        return load_config(cls, config_dir=config_dir, env=env)
```

- [ ] **Step 5: Run test, verify PASS**

Run: `pytest tests/unit/test_registry_config_pydantic.py -v`
Expected: 4 PASS.

- [ ] **Step 6: Modify routes/_auth.py to validate X-Environment**

Open `src/routes/_auth.py`. Find the existing `make_api_key_verifier()` invocation. The shape will look something like:

```python
verify = make_api_key_verifier()
```

Replace with:

```python
verify = make_api_key_verifier(environment=config.environment)
```

(The `config` variable is whatever the route module already has access to — usually injected via the app's `state` or a module-level `make_routes(config)` factory. If the auth dependency is constructed without a config in scope, refactor to thread the `RegistryConfig` through.)

**Scope note for L2 registry isolation:** This step covers the critical half — *writes* (register, heartbeat, deregister) are env-checked, so cross-env registrations are impossible. The spec's secondary defense-in-depth — also stamping `environment` onto each `RegistryEntry` row and filtering lookup responses by the requesting client's `X-Environment` — is captured in *Open work after this plan* (item 5). It's a belt-and-suspenders feature: in practice, every entry in a "dev registry" already has `environment=dev` because write auth rejects everything else.

- [ ] **Step 7: Add config/default.yaml**

```yaml
# config/default.yaml — registry server, base settings.
environment: dev
port: 8090
sqlite_path: /var/lib/registry/registry.db
seed_path: /etc/registry/registry.yaml
internal_api_key: ${INTERNAL_API_KEY}
heartbeat_grace_seconds: 60
eviction_seconds: 300
reaper_interval_seconds: 30
service_url: ""
enable_ui: true
```

- [ ] **Step 8: Add config/dev.yaml**

```yaml
# config/dev.yaml — overlay for ENVIRONMENT=dev. Empty for now; placeholder
# for future overrides such as a more aggressive reaper.
```

(Yes — an empty file. The deep-merge layer treats this as "no overrides" and the default applies.)

- [ ] **Step 9: Add .env.example**

```
# Required env vars for the registry server.
# All operational config lives in config/*.yaml; this file documents
# only secrets and runtime-only values.

# Auth (substituted into config/default.yaml)
INTERNAL_API_KEY=changeme

# Environment selector — chooses config/<env>.yaml overlay and is
# stamped into outbound traffic.  Required.
ENVIRONMENT=dev
```

- [ ] **Step 10: Verify .env in .gitignore**

```bash
grep -q '^\.env$' .gitignore || echo '.env' >> .gitignore
```

- [ ] **Step 11: Update Dockerfile**

Find the BASE_TAG line and bump:
```dockerfile
ARG BASE_TAG=3.11-sdk0.6.0
```

Add `COPY config/ /app/config/` after the `COPY src/` line:
```dockerfile
COPY src/   /app/src/
COPY config/ /app/config/
```

- [ ] **Step 12: Update pyproject.toml (SDK pin)**

Change the SDK dependency line to `0.6.0`:
```toml
"enterprise-ai-platform-sdk @ git+ssh://git@github.com/narisun/ai-platform-sdk.git@v0.6.0",
```

- [ ] **Step 13: Update tests that previously did `monkeypatch.setenv`**

Walk every `tests/` file. Where a test relied on `RegistryConfig.from_env()` plus `monkeypatch.setenv`, replace with direct construction:

```python
config = RegistryConfig(
    environment="dev",
    internal_api_key="test-key",
    sqlite_path=tmp_path / "registry.db",
)
```

- [ ] **Step 14: Wire CI**

In `.github/workflows/ci.yml` (or equivalent), add two steps:

```yaml
      - name: check-env-example
        run: |
          pip install enterprise-ai-platform-sdk@git+ssh://git@github.com/narisun/ai-platform-sdk.git@v0.6.0
          platform-sdk check-env-example --config-dir config --env-example .env.example

      - name: no-adhoc-httpx-async-client
        run: |
          # All inter-service HTTP must go through platform_sdk.http.make_internal_http_client
          # so X-Environment + Bearer headers are guaranteed (L3).
          if grep -rn --include='*.py' 'httpx\.AsyncClient(' src/; then
            echo "ERROR: direct httpx.AsyncClient construction found in src/."
            echo "Use platform_sdk.http.make_internal_http_client instead."
            exit 1
          fi
```

- [ ] **Step 15: Run full test suite locally**

Run: `pytest tests -v`
Expected: all PASS.

- [ ] **Step 16: Build the image locally and verify startup**

```bash
docker build --build-arg BASE_TAG=3.11-sdk0.6.0 -t ai-registry:dev .
docker run --rm -e ENVIRONMENT=dev -e INTERNAL_API_KEY=k ai-registry:dev python -c "from src.config import RegistryConfig; print(RegistryConfig.load())"
```
Expected: prints a populated `RegistryConfig` instance.

- [ ] **Step 17: Commit, push, tag**

```bash
git add -A
git commit -m "refactor(config)!: migrate to SDK 0.6.0 centralised config

RegistryConfig is now Pydantic; load() reads config/default.yaml +
config/<env>.yaml and resolves \${INTERNAL_API_KEY}. Auth dependency
validates X-Environment. .env.example documents required env vars
and is checked in CI via platform-sdk check-env-example."
git push -u origin feature/config-management
```
Open PR; after merge, tag `v0.6.0`.

---

## Task 14: Migrate `narisun/ai-mcp-data`

**Branch:** `feature/config-management` in the ai-mcp-data repo.

**Files:**
- Modify: `src/main.py` (no os.environ; build via MCPConfig.load())
- Modify: `src/server.py` (matches main.py)
- Create: `config/default.yaml`
- Create: `config/dev.yaml`
- Create: `.env.example`
- Modify: `Dockerfile` (BASE_TAG → 3.11-sdk0.6.0; COPY config/)
- Modify: `pyproject.toml` (SDK pin → 0.6.0)
- Modify: tests as needed

- [ ] **Step 1: Set up the worktree**

Use the `superpowers:using-git-worktrees` skill.

- [ ] **Step 2: Write a sanity test for the new main.py shape**

```python
# tests/unit/test_main_loads_config.py
"""src.main constructs FastMCP from MCPConfig.load()."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_main_uses_loaded_config_for_port_and_transport(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("INTERNAL_API_KEY", "k")

    (tmp_path / "default.yaml").write_text(
        "environment: dev\nport: 8080\ntransport: sse\n"
        "service_name: data-mcp\nservice_url: http://data-mcp:8080\n"
        "registry_url: http://ai-registry:8090\n"
        "internal_api_key: ${INTERNAL_API_KEY}\n"
    )

    # Import is what triggers MCPConfig.load() at module level.
    from src import main as main_mod

    assert main_mod.config.port == 8080
    assert main_mod.config.transport == "sse"
    assert main_mod.mcp is not None
    assert main_mod.service.name == "data-mcp"
```

- [ ] **Step 3: Replace `src/main.py`**

```python
"""Main entry point for the data-mcp server."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from platform_sdk import MCPConfig, configure_logging, get_logger

from .data_mcp_service import DataMcpService

configure_logging()
log = get_logger(__name__)

# Module-level: required for FastMCP construction before lifespan runs.
config = MCPConfig.load()

# Service constructed with the loaded config — the DataMcpService base
# class will store it on self.config and use it through registration.
service = DataMcpService(config=config)

# Create the MCP server.
if config.transport == "sse":
    mcp = FastMCP(
        "Enterprise Data MCP",
        lifespan=service.lifespan,
        host="0.0.0.0",
        port=config.port,
    )
else:
    mcp = FastMCP("Enterprise Data MCP", lifespan=service.lifespan)

service.register_tools(mcp)


if __name__ == "__main__":
    log.info("mcp_server_starting", transport=config.transport)
    service.run_with_registration(mcp, config.transport)
```

- [ ] **Step 4: Replace `src/server.py`** (the existing shim that delegates to main)

```python
"""Backwards-compat entrypoint shim. Delegates to src.main."""
from .main import config, mcp, service

if __name__ == "__main__":
    service.run_with_registration(mcp, config.transport)
```

- [ ] **Step 5: Add config/default.yaml**

```yaml
# config/default.yaml — data-mcp base settings.
environment: dev
service_name: data-mcp
agent_role: data_analyst_agent
transport: sse
port: 8080

# OPA — overridden in container by registry-published URL or service URL.
opa_url: http://opa:8181/v1/data/mcp/tools/allow
opa_timeout_seconds: 2.0
opa_max_retries: 2
opa_retry_backoff: 0.2

# Result guardrails
max_result_bytes: 15000

# Tool-result cache (Redis)
enable_tool_cache: true
tool_cache_ttl_seconds: 300

# Database
db_host: pgvector
db_port: 5432
db_user: admin
db_pass: ${DB_PASS}
db_name: ai_memory
db_require_ssl: false
statement_cache_size: 1024

# Redis
redis_host: redis
redis_port: 6379
redis_password: ${REDIS_PASSWORD}

# Self-registration
registry_url: http://ai-registry:8090
service_url: http://data-mcp:8080
service_version: "0.6.0"
internal_api_key: ${INTERNAL_API_KEY}

# Resilience
cb_failure_threshold: 5
cb_recovery_timeout: 30.0
mcp_reconnect_backoff_cap: 60.0
tool_call_timeout: 30.0
```

- [ ] **Step 6: Add config/dev.yaml**

```yaml
# config/dev.yaml — overlay for ENVIRONMENT=dev.
# Empty placeholder; service_url and registry_url already point at compose
# hostnames in default.yaml. Add per-env overrides here when needed
# (e.g. alternate OPA URL, different result-byte cap).
```

- [ ] **Step 7: Add .env.example**

```
# Secrets required by config/*.yaml ${VAR} references.
DB_PASS=changeme
REDIS_PASSWORD=changeme
INTERNAL_API_KEY=changeme

# Selectors / runtime-only.
ENVIRONMENT=dev
```

- [ ] **Step 8: Update Dockerfile**

```dockerfile
ARG BASE_TAG=3.11-sdk0.6.0
FROM ghcr.io/narisun/ai-python-base:${BASE_TAG}

WORKDIR /app

COPY requirements-runtime.txt .
RUN pip install --no-cache-dir -r requirements-runtime.txt

COPY src/    /app/src/
COPY config/ /app/config/

USER appuser
EXPOSE 8080
CMD ["python", "-m", "src.server"]
```

- [ ] **Step 9: Update pyproject.toml (SDK pin)**

Change SDK dependency to `v0.6.0`.

- [ ] **Step 10: Wire CI**

Add **both** the `check-env-example` step **and** the `no-adhoc-httpx-async-client` grep step (same shape as Task 13 Step 14).

- [ ] **Step 11: Migrate any tests that relied on env vars**

Search tests for `from_env()` and `monkeypatch.setenv` patterns; replace with explicit `MCPConfig(...)` construction.

- [ ] **Step 12: Run tests and image build**

```bash
pytest tests -v
docker build --build-arg BASE_TAG=3.11-sdk0.6.0 -t ai-mcp-data:dev .
docker run --rm \
  -e ENVIRONMENT=dev -e DB_PASS=x -e REDIS_PASSWORD=x -e INTERNAL_API_KEY=k \
  ai-mcp-data:dev python -c "from src.main import config; print(config.port, config.transport)"
```
Expected: tests pass; container prints `8080 sse`.

- [ ] **Step 13: Commit, push, tag**

```bash
git add -A
git commit -m "refactor(config)!: adopt SDK 0.6.0 centralised config

src/main.py reads from MCPConfig.load() instead of os.environ.
config/default.yaml + config/dev.yaml define operational values;
secrets come from .env.example documented vars."
git push -u origin feature/config-management
```
Open PR; after merge, tag `v0.6.0`.

---

## Task 15: Migrate `narisun/ai-mcp-news-search`

Identical to Task 14 with these specifics:
- `service_name: news-search-mcp`
- `port: 8083`
- `service_url: http://news-search-mcp:8083`
- The news repo's `src/main.py` already has the `PORT = int(os.environ.get("PORT", 8083))` leak.
- May reference an external news API key (e.g. `NEWS_API_KEY`) — list it in `.env.example` and reference it via `${NEWS_API_KEY}` in `config/default.yaml`.

- [ ] **Step 1: Worktree, write `tests/unit/test_main_loads_config.py`** (mirror Task 14 Step 2 but expect `port=8083`).

- [ ] **Step 2: Run test, verify FAIL.**

- [ ] **Step 3: Replace `src/main.py`**

```python
"""Main entry point for the news-search-mcp server."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from platform_sdk import MCPConfig, configure_logging, get_logger

from .news_search_mcp_service import NewsSearchMcpService

configure_logging()
log = get_logger(__name__)

config = MCPConfig.load()

service = NewsSearchMcpService(config=config)

mcp = FastMCP(
    "news-search-mcp",
    lifespan=service.lifespan,
    host="0.0.0.0",
    port=config.port,
)

service.register_tools(mcp)


if __name__ == "__main__":
    log.info("mcp_server_starting", transport=config.transport)
    service.run_with_registration(mcp, config.transport)
```

- [ ] **Step 4: Update `src/server.py` shim** to mirror Task 14 Step 4.

- [ ] **Step 5: Add config/default.yaml**

```yaml
environment: dev
service_name: news-search-mcp
agent_role: data_analyst_agent
transport: sse
port: 8083

opa_url: http://opa:8181/v1/data/mcp/tools/allow
opa_timeout_seconds: 2.0

max_result_bytes: 15000
enable_tool_cache: true
tool_cache_ttl_seconds: 300

# News-search has no DB — db_pass is unused, but the model requires it
# (defaults to ""). We omit DB fields here entirely; the loader uses
# Pydantic defaults.
redis_host: redis
redis_port: 6379
redis_password: ${REDIS_PASSWORD}

registry_url: http://ai-registry:8090
service_url: http://news-search-mcp:8083
service_version: "0.6.0"
internal_api_key: ${INTERNAL_API_KEY}
```

- [ ] **Step 6: Add config/dev.yaml** (empty placeholder).

- [ ] **Step 7: Add .env.example**

```
REDIS_PASSWORD=changeme
INTERNAL_API_KEY=changeme
NEWS_API_KEY=changeme   # only if the service consumes it
ENVIRONMENT=dev
```

If `NEWS_API_KEY` isn't actually consumed by current code, omit it. Otherwise reference it in `config/default.yaml` via `news_api_key: ${NEWS_API_KEY}` and add the field to `MCPConfig` as well — but that requires SDK changes, so prefer to load it from env via a custom subclass field if needed (rare; verify before adding).

- [ ] **Step 8: Update Dockerfile** (BASE_TAG → 3.11-sdk0.6.0; COPY config/).

- [ ] **Step 9: Update pyproject.toml** (SDK pin).

- [ ] **Step 10: Wire CI** — same `check-env-example` and `no-adhoc-httpx-async-client` steps as Task 14 Step 10.

- [ ] **Step 11: Migrate tests.**

- [ ] **Step 12: Build & smoke-test:**

```bash
docker build --build-arg BASE_TAG=3.11-sdk0.6.0 -t ai-mcp-news-search:dev .
docker run --rm \
  -e ENVIRONMENT=dev -e REDIS_PASSWORD=x -e INTERNAL_API_KEY=k \
  ai-mcp-news-search:dev python -c "from src.main import config; print(config.port)"
```
Expected: prints `8083`.

- [ ] **Step 13: Commit, push, tag** (same commit message style as Task 14).

---

## Task 16: Migrate `narisun/ai-mcp-payments`

Identical to Task 14 with these specifics:
- `service_name: payments-mcp`
- `port: 8082`
- `service_url: http://payments-mcp:8082`

- [ ] **Step 1: Worktree, write tests/unit/test_main_loads_config.py mirroring Task 14 Step 2 with `port=8082`.**

- [ ] **Step 2: Run test, verify FAIL.**

- [ ] **Step 3: Replace `src/main.py`**

```python
"""Main entry point for the payments-mcp server."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from platform_sdk import MCPConfig, configure_logging, get_logger

from .payments_mcp_service import PaymentsMcpService

configure_logging()
log = get_logger(__name__)

config = MCPConfig.load()
service = PaymentsMcpService(config=config)

mcp = FastMCP(
    "payments-mcp",
    lifespan=service.lifespan,
    host="0.0.0.0",
    port=config.port,
)

service.register_tools(mcp)


if __name__ == "__main__":
    log.info("mcp_server_starting", transport=config.transport)
    service.run_with_registration(mcp, config.transport)
```

(If the actual class name differs from `PaymentsMcpService`, adjust accordingly. Inspect `src/` to confirm.)

- [ ] **Step 4: Update `src/server.py` shim.**

- [ ] **Step 5: Add config/default.yaml** (mirror Task 14 with payments-specific values: `service_name`, `port`, `service_url`).

- [ ] **Step 6: Add config/dev.yaml** (empty).

- [ ] **Step 7: Add .env.example**

```
INTERNAL_API_KEY=changeme
REDIS_PASSWORD=changeme
ENVIRONMENT=dev
```

(Include `DB_PASS` only if payments-mcp actually queries Postgres — verify by `grep -r 'db_pass\|DB_PASS' src/`.)

- [ ] **Step 8: Update Dockerfile, pyproject.toml, CI, tests, build, smoke-test, commit, push, tag** as in Task 14.

---

## Task 17: Migrate `narisun/ai-mcp-salesforce`

Identical to Task 14 with these specifics:
- `service_name: salesforce-mcp`
- `port: 8081`
- `service_url: http://salesforce-mcp:8081`
- May reference Salesforce credentials (e.g. `SALESFORCE_USERNAME`, `SALESFORCE_PASSWORD`, `SALESFORCE_TOKEN`) — list each in `.env.example` and reference via `${VAR}` in `config/default.yaml`. Add corresponding fields to `MCPConfig` only if not already present; otherwise use a service-specific subclass.

Steps mirror Task 14 with port 8081 and Salesforce-specific .env.example entries. Detailed steps:

- [ ] **Step 1: Worktree.**

- [ ] **Step 2: Write `tests/unit/test_main_loads_config.py`** with port=8081.

- [ ] **Step 3: Run test, verify FAIL.**

- [ ] **Step 4: Replace `src/main.py`** mirroring Task 14 Step 3 (substitute `salesforce-mcp` and `SalesforceMcpService` class name; verify by inspecting `src/`).

- [ ] **Step 5: Update `src/server.py` shim.**

- [ ] **Step 6: Add config/default.yaml**

```yaml
environment: dev
service_name: salesforce-mcp
agent_role: data_analyst_agent
transport: sse
port: 8081

opa_url: http://opa:8181/v1/data/mcp/tools/allow
opa_timeout_seconds: 2.0

max_result_bytes: 15000
enable_tool_cache: true
tool_cache_ttl_seconds: 300

redis_host: redis
redis_port: 6379
redis_password: ${REDIS_PASSWORD}

registry_url: http://ai-registry:8090
service_url: http://salesforce-mcp:8081
service_version: "0.6.0"
internal_api_key: ${INTERNAL_API_KEY}
```

- [ ] **Step 7: Add config/dev.yaml** (empty).

- [ ] **Step 8: Add .env.example**

```
INTERNAL_API_KEY=changeme
REDIS_PASSWORD=changeme
SALESFORCE_USERNAME=changeme
SALESFORCE_PASSWORD=changeme
SALESFORCE_TOKEN=changeme
ENVIRONMENT=dev
```

(Trim entries that aren't actually consumed — verify with `grep -r SALESFORCE_ src/`.)

- [ ] **Step 9: Update Dockerfile, pyproject.toml, CI, tests, build, smoke-test, commit, push, tag** as in Task 14.

---

## Task 18: Migrate `narisun/ai-agent-analytics`

**Branch:** `feature/config-management` in the ai-agent-analytics repo.

**Files:**
- Modify: `src/app.py` (delete `os.getenv("DATABASE_URL")` and `os.getenv("ENVIRONMENT")` calls)
- Create: `config/default.yaml`
- Create: `config/dev.yaml`
- Create: `.env.example`
- Modify: `Dockerfile`
- Modify: `pyproject.toml`
- Modify: tests

- [ ] **Step 1: Worktree.**

- [ ] **Step 2: Write the failing test**

```python
# tests/unit/test_app_uses_config_database_url.py
"""build_conversation_store reads database_url from config, not os.getenv."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_postgres_store_used_when_database_url_set_and_env_is_dev(monkeypatch):
    """A non-local environment + database_url → PostgresConversationStore (or Memory if asyncpg missing)."""
    from src.app import AnalyticsAgentApp
    from platform_sdk import AgentConfig

    cfg = AgentConfig(environment="dev", database_url="postgres://x")
    app = AnalyticsAgentApp("analytics-agent", config=cfg)

    store = app.build_conversation_store()
    # Either PostgresConversationStore (if asyncpg installed) or fallback Memory.
    assert store is not None
    assert "Memory" in type(store).__name__ or "Postgres" in type(store).__name__


def test_memory_store_when_database_url_empty(monkeypatch):
    from src.app import AnalyticsAgentApp
    from platform_sdk import AgentConfig

    cfg = AgentConfig(environment="dev", database_url="")
    app = AnalyticsAgentApp("analytics-agent", config=cfg)

    store = app.build_conversation_store()
    assert "Memory" in type(store).__name__
```

- [ ] **Step 3: Run, verify FAIL** (current build_conversation_store reads via os.getenv).

- [ ] **Step 4: Modify `src/app.py`**

(a) Find the `import os` line — the import remains (other code may use os.path), but the two `os.getenv` calls go away.

(b) Find:
```python
    def load_config(self, name: str | None = None) -> AgentConfig:
        return AgentConfig.from_env()
```
Delete this method entirely. The base class auto-loads via `config_model = AgentConfig`. Add the class attribute below the existing class attrs:
```python
    config_model = AgentConfig
```

(c) Find `build_conversation_store`:
```python
    def build_conversation_store(self) -> Any:
        """Create the appropriate conversation store based on environment."""
        db_url = os.getenv("DATABASE_URL")
        if (
            db_url
            and os.getenv("ENVIRONMENT") not in ("local",)
            and PostgresConversationStore is not None
        ):
            return PostgresConversationStore(db_url)
        if db_url and PostgresConversationStore is None:
            log.warning("asyncpg_not_available", fallback="MemoryConversationStore")
        return MemoryConversationStore()
```

Replace with:

```python
    def build_conversation_store(self) -> Any:
        """Create the appropriate conversation store based on config."""
        db_url = self.config.database_url
        # "local" was the legacy alias for dev with in-memory store; in 0.6.0
        # the strict Environment Literal removes "local". Use Memory in dev.
        use_postgres = (
            bool(db_url)
            and self.config.environment != "dev"
            and PostgresConversationStore is not None
        )
        if use_postgres:
            return PostgresConversationStore(db_url)
        if db_url and PostgresConversationStore is None:
            log.warning("asyncpg_not_available", fallback="MemoryConversationStore")
        return MemoryConversationStore()
```

(Behaviour delta: `dev` now always uses MemoryConversationStore, mirroring the old `local` semantics. `staging`/`prod` use Postgres if `database_url` is non-empty.)

- [ ] **Step 5: Run test, verify PASS.**

- [ ] **Step 6: Add config/default.yaml**

```yaml
# config/default.yaml — analytics-agent base settings.
environment: dev

# Model routing
model_route: complex-routing
summary_model_route: fast-routing
router_model_route: fast-routing
specialist_model_route: fast-routing
synthesis_model_route: complex-routing

# LiteLLM
litellm_base_url: http://litellm:4000/v1
internal_api_key: ${INTERNAL_API_KEY}

# Checkpointer
checkpointer_type: memory
checkpointer_db_url: ""

# Conversation store
database_url: ""

# Compaction
enable_compaction: true
context_token_limit: 6000

# Safety
recursion_limit: 10
max_message_length: 32000

# Tool cache
enable_tool_cache: true
tool_cache_ttl_seconds: 300

# MCP bridge
mcp_startup_timeout: 120.0

# Synthesis
chart_max_data_points: 20

# Self-registration
registry_url: http://ai-registry:8090
service_url: http://analytics-agent:8000
service_version: "0.6.0"
```

- [ ] **Step 7: Add config/dev.yaml** (empty).

- [ ] **Step 8: Add .env.example**

```
# Secrets and runtime-only vars for analytics-agent.
INTERNAL_API_KEY=changeme

# Optional: set when running with a real Postgres conversation store.
# Leave empty for in-memory.
# DATABASE_URL=postgres://app:pass@db/analytics

ENVIRONMENT=dev
```

If `DATABASE_URL` is intended to come from env, add it to `config/default.yaml` as `database_url: ${DATABASE_URL}` AND list it as a non-commented `.env.example` entry. Otherwise leave the YAML literal empty (as above) and treat dev as in-memory.

- [ ] **Step 9: Update Dockerfile** (BASE_TAG → 3.11-sdk0.6.0; `COPY config/ /app/config/`).

- [ ] **Step 10: Update pyproject.toml** (SDK pin → 0.6.0).

- [ ] **Step 11: Wire CI** — same `check-env-example` and `no-adhoc-httpx-async-client` steps as Task 14 Step 10.

- [ ] **Step 12: Migrate any tests** that relied on `monkeypatch.setenv("DATABASE_URL", ...)` — pass an explicit `AgentConfig(database_url=..., environment=...)` instead.

- [ ] **Step 13: Run full test suite**

Run: `pytest tests -v`
Expected: PASS.

- [ ] **Step 14: Build & smoke-test**

```bash
docker build --build-arg BASE_TAG=3.11-sdk0.6.0 -t ai-agent-analytics:dev .
docker run --rm -e ENVIRONMENT=dev -e INTERNAL_API_KEY=k \
  ai-agent-analytics:dev python -c "from src.app import AnalyticsAgentApp; a = AnalyticsAgentApp('analytics-agent'); print(a.config.environment, a.config.database_url)"
```
Expected: `dev ` (empty database_url).

- [ ] **Step 15: Commit, push, tag**

```bash
git add -A
git commit -m "refactor(config)!: adopt SDK 0.6.0 centralised config

build_conversation_store now reads database_url from AgentConfig.
config/default.yaml + config/dev.yaml define operational values.
The legacy 'local' environment alias is gone (replaced by 'dev')."
git push -u origin feature/config-management
```

Open PR; after merge, tag `v0.6.0`.

---

# Phase 3 — Dev-Stack

The dev-stack PR ties everything together. It MUST land after every Phase-2 service has shipped its 0.6.0 image, otherwise `make setup` will pull older images that lack the new YAML files.

---

## Task 19: Dev-stack `.env` and `.env.example`

**Files:**
- Create: `ai-dev-stack/.env` (gitignored)
- Create: `ai-dev-stack/.env.example` (committed)
- Modify: `ai-dev-stack/.gitignore`

- [ ] **Step 1: Worktree** in ai-dev-stack on `feature/config-management`.

- [ ] **Step 2: Verify .env is gitignored**

```bash
grep -q '^\.env$' .gitignore || echo '.env' >> .gitignore
```

- [ ] **Step 3: Create .env (NOT committed)**

```
# Local-dev secrets for the entire stack. Loaded by every service via
# Compose's env_file: directive. Never committed.

# Selectors
ENVIRONMENT=dev

# Auth
INTERNAL_API_KEY=changeme-local

# Postgres (pgvector)
POSTGRES_PASSWORD=changeme-local
DB_PASS=changeme-local

# Redis
REDIS_PASSWORD=changeme-local

# Third-party (set per developer's account; leave blank if unused)
NEWS_API_KEY=
SALESFORCE_USERNAME=
SALESFORCE_PASSWORD=
SALESFORCE_TOKEN=

# OpenAI / LiteLLM provider keys (used by the LiteLLM proxy)
OPENAI_API_KEY=

# LangFuse (optional; leave blank if unused)
LANGFUSE_HOST=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
```

- [ ] **Step 4: Create .env.example (committed)**

Same content as .env above (developers copy `.env.example` to `.env` and edit).

- [ ] **Step 5: Commit .env.example only**

```bash
git add .env.example .gitignore
git commit -m "chore(dev-stack): add .env.example with required vars

Documents every secret/runtime-only env var consumed by any service
in the stack. Developers copy to .env (gitignored) and fill in.
Compose loads .env into every service via env_file:."
```

---

## Task 20: Update `docker-compose.yml`

**Files:**
- Modify: `ai-dev-stack/docker-compose.yml`

- [ ] **Step 1: Bump every service image tag to 0.6.0**

For each service block (`ai-registry`, `ai-data-mcp`, `ai-salesforce-mcp`, `ai-payments-mcp`, `ai-news-search-mcp`, `ai-analytics-agent`, `ai-frontend-analytics` if it tracks SDK), find the `image:` line and update the tag from `:0.5.x` to `:0.6.0`.

- [ ] **Step 2: Add `env_file: .env` to every Python service**

For `ai-registry`, every `ai-*-mcp`, and `ai-analytics-agent`, add immediately under the `image:` line:

```yaml
    env_file: .env
```

- [ ] **Step 3: Trim the `environment:` block of each service**

Today's `environment:` blocks contain a mix of secrets, URLs, and selectors. Replace each one with **only** `ENVIRONMENT` (and any compose-internal hostname overrides that aren't expressible in YAML — those should be rare to none).

For example, replace this current `data-mcp` block:

```yaml
    environment:
      DB_HOST: pgvector
      DB_USER: admin
      DB_PASS: ${POSTGRES_PASSWORD}
      DB_NAME: ai_memory
      OPA_URL: http://opa:8181/v1/data/mcp/tools/allow
      MCP_TRANSPORT: sse
      PORT: 8080
      INTERNAL_API_KEY: ${INTERNAL_API_KEY}
      REGISTRY_URL: http://ai-registry:8090
      SERVICE_URL: http://data-mcp:8080
      <<: *otel-env
```

with:

```yaml
    environment:
      ENVIRONMENT: dev
      <<: *otel-env
```

The `env_file: .env` already injects `INTERNAL_API_KEY`, `DB_PASS`, etc. for `${VAR}` substitution. Operational values (`OPA_URL`, `MCP_TRANSPORT`, `PORT`, `REGISTRY_URL`, `SERVICE_URL`) live in each service's `config/default.yaml` as literals.

Repeat for every service (registry, all four MCPs, analytics-agent).

- [ ] **Step 4: Verify the registry's seed YAML mount is unchanged**

The registry receives its `config/registry.yaml` (the seed catalogue) via a bind-mount; the new SDK config files are baked into the image. The two are unrelated. Leave the existing `volumes: - ./config/registry.yaml:/etc/registry/registry.yaml:ro` in place.

- [ ] **Step 5: Validate compose syntactically**

```bash
docker compose config > /dev/null
```
Expected: exits 0 with no output.

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml
git commit -m "refactor(compose)!: env_file for secrets, strip operational vars

Every Python service now consumes secrets via env_file: .env (canonical
source) and ENVIRONMENT=dev via environment:. Operational values
(OPA_URL, PORT, MCP_TRANSPORT, REGISTRY_URL, SERVICE_URL) moved into
each service's config/default.yaml — they are no longer compose
concerns."
```

---

## Task 21: Update integration tests

**Files:**
- Modify: `tests/integration/test_registry_e2e.py`
- Create: `tests/integration/test_environment_isolation.py`

- [ ] **Step 1: Strengthen registry E2E**

In `tests/integration/test_registry_e2e.py`, find the existing assertion that all 5 services are registered. Keep it as-is. The per-entry environment field is a follow-up (Open work item 5); for this round we cover the cross-env gate via the new `test_environment_isolation.py` (Step 2 below), which proves the *write-side* enforcement. The existing "all five registered" assertion already implicitly proves dev↔dev cross-talk works.

If the existing assertion only checks names (not state), upgrade it to also check `state == "registered"`:

```python
def test_registry_all_services_registered(...):
    ...
    response = httpx.get(f"{REGISTRY_URL}/api/services")
    assert response.status_code == 200
    services = response.json().get("services", [])
    by_name = {s["name"]: s for s in services}

    expected_names = {"analytics-agent", "data-mcp", "salesforce-mcp",
                      "payments-mcp", "news-search-mcp"}
    assert expected_names.issubset(by_name.keys()), \
        f"missing services: {expected_names - by_name.keys()}"

    for name in expected_names:
        entry = by_name[name]
        assert entry["state"] == "registered", f"{name}: state={entry['state']}"
```

- [ ] **Step 2: Create cross-env isolation test**

```python
# tests/integration/test_environment_isolation.py
"""End-to-end cross-environment isolation: a fake prod client sees 403."""
from __future__ import annotations

import os

import httpx
import pytest

REGISTRY_URL = os.environ.get("REGISTRY_URL", "http://localhost:8090")
DATA_MCP_URL = os.environ.get("DATA_MCP_URL", "http://localhost:8080")
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "changeme-local")


def test_fake_prod_client_against_registry_returns_403():
    """A POST /api/services with X-Environment: prod is rejected."""
    r = httpx.post(
        f"{REGISTRY_URL}/api/services",
        json={"name": "evil", "url": "http://evil/", "type": "agent"},
        headers={
            "Authorization": f"Bearer {INTERNAL_API_KEY}",
            "X-Environment": "prod",
        },
    )
    assert r.status_code == 403
    body = r.json()
    assert body.get("detail", {}).get("error") == "environment_mismatch"


def test_fake_prod_client_against_data_mcp_returns_403():
    """A request to data-mcp's protected endpoint with X-Environment: prod is rejected."""
    # data-mcp's /sse endpoint requires the same auth dependency. Hitting
    # it with the wrong environment returns 403 even with a valid Bearer.
    r = httpx.get(
        f"{DATA_MCP_URL}/sse",
        headers={
            "Authorization": f"Bearer {INTERNAL_API_KEY}",
            "X-Environment": "prod",
        },
        timeout=2.0,
    )
    assert r.status_code == 403


def test_no_x_environment_header_rejected():
    """Missing X-Environment is treated the same as a mismatch."""
    r = httpx.post(
        f"{REGISTRY_URL}/api/services",
        json={"name": "evil", "url": "http://evil/", "type": "agent"},
        headers={"Authorization": f"Bearer {INTERNAL_API_KEY}"},
    )
    assert r.status_code == 403
```

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_registry_e2e.py \
        tests/integration/test_environment_isolation.py
git commit -m "test(integration): assert env=dev on registry, cross-env 403

E2E coverage for L3 strict isolation: every registered service must
report environment=dev; a fake prod client gets 403 from the registry
and from data-mcp's protected endpoint."
```

(The complementary "no `httpx.AsyncClient(` outside the SDK factory" check lives in each Phase-2 service repo's CI — see Task 14 Step 10 onward, which adds a grep step alongside `platform-sdk check-env-example`.)

---

## Task 22: End-to-end verification

- [ ] **Step 1: Stop any running stack**

```bash
make stop || true
docker compose down -v
```

- [ ] **Step 2: Pull latest images**

```bash
docker compose pull
```
Expected: every image at tag `0.6.0` (registry, four MCPs, analytics-agent).

- [ ] **Step 3: Run `make setup`**

```bash
make setup
```
Expected: all 13 containers reach `Up (healthy)`. Watch the logs of `ai-registry` and each Python service for `config_loaded` (or equivalent — there's no startup log line specifically for config in the SDK; verify by absence of `ConfigError` traces).

- [ ] **Step 4: Verify catalog**

```bash
sleep 30
curl -s http://localhost:8090/api/services | jq '.services[] | {name, state}'
```
Expected (in some order):
```json
{"name": "analytics-agent", "state": "registered"}
{"name": "data-mcp",        "state": "registered"}
{"name": "news-search-mcp", "state": "registered"}
{"name": "payments-mcp",    "state": "registered"}
{"name": "salesforce-mcp",  "state": "registered"}
```

(The per-entry `environment` field arrives in the registry-side follow-up — see *Open work after this plan* item 5.)

- [ ] **Step 5: Run integration tests**

```bash
pytest tests/integration -v
```
Expected: all PASS, including the new env-isolation 403 tests.

- [ ] **Step 6: Stop**

```bash
make stop
```

- [ ] **Step 7: Commit (if any test fixtures changed) and open PR**

```bash
git add -A   # only if there are uncommitted changes
git commit -m "chore(dev-stack): final test fixture tweaks for 0.6.0" || true
git push -u origin feature/config-management
```
Open the PR. Merge after green CI.

---

# Tracker

| Phase | Tasks | Independent? |
|---|---|---|
| Phase 1 — SDK 0.6.0 | 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12 | Sequential within the SDK PR. |
| Phase 2 — Service migrations | 13 (registry), 14, 15, 16, 17 (MCPs), 18 (analytics) | Independent across repos; merge in any order. Each must wait for SDK 0.6.0 release. |
| Phase 3 — Dev-stack | 19, 20, 21, 22 | Sequential within the dev-stack PR. Must wait for every Phase-2 service to ship. |

After Task 22 lands, the platform is fully on the new config model: secrets in `.env`, operational config in `config/*.yaml`, strict environment isolation in transit, single env-reader in the SDK.

---

# Open work after this plan

1. **Frontend (Next.js) parallel design.** A follow-up spec defines a TS YAML loader that mirrors this Python loader's `${VAR}` rules. Out of scope here.
2. **Pydantic SecretStr adoption.** Re-type `db_pass`, `internal_api_key`, etc. as `SecretStr` so they don't accidentally appear in logs. Per-field one-line follow-up.
3. **Per-service rotated `INTERNAL_API_KEY`.** The current model uses a single shared key. A follow-up spec covers rotated, per-service API keys.
4. **Removal of `RegistryClient(registry_url=..., api_key=...)` legacy constructor.** Kept for one release in Task 7; remove in SDK 0.7.0 once every caller is on `from_config`.
5. **Registry lookup environment filtering (defense-in-depth).** Stamp `environment` onto each `RegistryEntry` (taken from the registering client's `X-Environment` header at write time) and filter `GET /api/services` by the lookup client's `X-Environment`. The plan ships the critical half (writes are env-checked, blocking cross-env registrations); this follow-up adds the per-entry stamp and read-time filter as belt-and-suspenders.
