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
from dataclasses import dataclass
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
    field: str
    reason: str


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
    """Load and validate configuration for `model_cls`."""
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
            return match.group(0)
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
