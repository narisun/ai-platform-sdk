"""${VAR} substitution rules — inline, no defaults, strict missing."""
from __future__ import annotations

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
    assert cfg.secret == "${B}"
