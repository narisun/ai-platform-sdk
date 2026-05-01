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
    assert "-1" in text or "greater than 0" in text or "gt=0" in text


def test_empty_default_yaml_yields_pydantic_validation_error(tmp_path):
    """Empty default.yaml must surface as missing required fields, not a crash."""
    from platform_sdk.config.loader import ConfigError, load_config

    (tmp_path / "default.yaml").write_text("")  # empty file

    with pytest.raises(ConfigError) as exc:
        load_config(_SampleConfig, config_dir=str(tmp_path), env="dev")

    text = str(exc.value)
    # _SampleConfig has a required `name: str`; Pydantic should complain about it.
    assert "name" in text
