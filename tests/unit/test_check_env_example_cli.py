"""platform-sdk check-env-example verifies .env.example covers ${VAR} refs."""
from __future__ import annotations

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
    assert "INTERNAL_API_KEY" not in result.output
    assert "ENVIRONMENT" not in result.output
