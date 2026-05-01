"""Deep-merge semantics for default + overlay."""
from __future__ import annotations

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

    (tmp_path / "default.yaml").write_text("inner:\n  a: 1\n  b: 2\nname: base\n")
    (tmp_path / "dev.yaml").write_text("inner:\n  a: 99\n")

    cfg = load_config(_Cfg, config_dir=str(tmp_path), env="dev")
    assert cfg.inner.a == 99
    assert cfg.inner.b == 2
    assert cfg.name == "base"


def test_overlay_replaces_lists_wholesale(tmp_path):
    from platform_sdk.config.loader import load_config

    (tmp_path / "default.yaml").write_text("items:\n  - a\n  - b\n")
    (tmp_path / "dev.yaml").write_text("items:\n  - x\n")

    cfg = load_config(_Cfg, config_dir=str(tmp_path), env="dev")
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
