"""Smoke tests for the platform-sdk scaffolding CLI."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _run_cli(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "platform_sdk.cli.main", *args],
        capture_output=True, text=True, cwd=cwd, check=False,
    )


def test_cli_help_runs():
    res = _run_cli("--help")
    assert res.returncode == 0
    assert "new" in res.stdout


def test_new_agent_help_runs():
    res = _run_cli("new", "agent", "--help")
    assert res.returncode == 0
    assert "--name" in res.stdout
    assert "--target" in res.stdout


def test_new_mcp_help_runs():
    res = _run_cli("new", "mcp", "--help")
    assert res.returncode == 0
    assert "--name" in res.stdout
    assert "--target" in res.stdout


def test_new_agent_scaffolds_expected_files(tmp_path: Path):
    target = tmp_path / "ai-agent-foo"
    res = _run_cli("new", "agent", "--name", "foo", "--target", str(target))
    assert res.returncode == 0, f"stderr: {res.stderr}"
    assert target.exists()
    assert (target / "Dockerfile").exists()
    assert (target / "pyproject.toml").exists()
    assert (target / "requirements.txt").exists()
    assert (target / "src" / "app.py").exists()
    assert (target / "tests" / "unit").exists()


def test_new_mcp_scaffolds_expected_files(tmp_path: Path):
    target = tmp_path / "ai-mcp-foo"
    res = _run_cli("new", "mcp", "--name", "foo", "--target", str(target))
    assert res.returncode == 0, f"stderr: {res.stderr}"
    assert target.exists()
    assert (target / "src" / "main.py").exists()
    assert (target / "src" / "foo_service.py").exists()


def test_new_agent_substitutes_capitalization(tmp_path: Path):
    """{{Name}} should produce CapWords from a hyphenated name."""
    target = tmp_path / "ai-agent-customer-support"
    res = _run_cli("new", "agent", "--name", "customer-support", "--target", str(target))
    assert res.returncode == 0, f"stderr: {res.stderr}"
    app_py = (target / "src" / "app.py").read_text()
    # CapWords form should produce CustomerSupportAgentApp
    assert "CustomerSupportAgentApp" in app_py
    assert "{{Name}}" not in app_py
    assert "{{name}}" not in app_py


def test_new_mcp_substitutes_capitalization(tmp_path: Path):
    """{{Name}} should produce CapWords from a hyphenated name."""
    target = tmp_path / "ai-mcp-customer-support"
    res = _run_cli("new", "mcp", "--name", "customer-support", "--target", str(target))
    assert res.returncode == 0, f"stderr: {res.stderr}"
    # Both file path and content should use CapWords
    svc_path = target / "src" / "customer-support_service.py"
    # The {{name}}_service.py file path uses {{name}} (lowercase), so:
    expected_path = target / "src" / "customer-support_service.py"
    assert expected_path.exists(), f"expected {expected_path} not found"
    content = expected_path.read_text()
    assert "CustomerSupportMcpService" in content
    assert "{{Name}}" not in content


def test_new_agent_refuses_existing_target(tmp_path: Path):
    target = tmp_path / "exists"
    target.mkdir()
    res = _run_cli("new", "agent", "--name", "foo", "--target", str(target))
    assert res.returncode != 0


def test_new_agent_includes_gitignore(tmp_path: Path):
    target = tmp_path / "ai-agent-bar"
    res = _run_cli("new", "agent", "--name", "bar", "--target", str(target))
    assert res.returncode == 0, f"stderr: {res.stderr}"
    assert (target / ".gitignore").exists(), ".gitignore must ship in scaffold"


def test_new_mcp_includes_gitignore(tmp_path: Path):
    target = tmp_path / "ai-mcp-bar"
    res = _run_cli("new", "mcp", "--name", "bar", "--target", str(target))
    assert res.returncode == 0, f"stderr: {res.stderr}"
    assert (target / ".gitignore").exists(), ".gitignore must ship in scaffold"
