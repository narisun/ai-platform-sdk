"""platform-sdk command-line entry point.

Subcommands:
    platform-sdk new agent --name <name> --target <path>
    platform-sdk new mcp   --name <name> --target <path>
"""
from __future__ import annotations

import shutil
from pathlib import Path

import click

TEMPLATES = Path(__file__).parent / "templates"


def _substitute(text: str, name: str) -> str:
    """Substitute {{name}}, {{Name}}, {{NAME}} placeholders in template text."""
    cap_words = "".join(part.capitalize() for part in name.split("-"))
    shout = name.upper().replace("-", "_")
    return (text
            .replace("{{NAME}}", shout)
            .replace("{{Name}}", cap_words)
            .replace("{{name}}", name))


def _render_tree(template_dir: Path, target: Path, name: str) -> None:
    if target.exists():
        raise click.UsageError(f"{target} already exists; refusing to overwrite.")
    shutil.copytree(template_dir, target)
    # Walk the tree and substitute placeholders in file contents AND in file/dir names.
    # First pass: file contents.
    for path in target.rglob("*"):
        if path.is_file():
            try:
                text = path.read_text()
            except UnicodeDecodeError:
                # Binary file — skip content substitution.
                continue
            new_text = _substitute(text, name)
            if new_text != text:
                path.write_text(new_text)
    # Second pass: file and directory names (depth-first so parents rename last).
    paths = sorted(target.rglob("*"), key=lambda p: -len(p.parts))
    for path in paths:
        if "{{name}}" in path.name or "{{Name}}" in path.name or "{{NAME}}" in path.name:
            new_name = _substitute(path.name, name)
            path.rename(path.with_name(new_name))


@click.group()
def cli() -> None:
    """Enterprise AI Platform SDK scaffolding tools."""


@cli.group()
def new() -> None:
    """Create a new agent or MCP server repo from the canonical template."""


@new.command("agent")
@click.option("--name", required=True, help="Short agent name (e.g., 'foo' for ai-agent-foo).")
@click.option("--target", type=click.Path(), required=True, help="Path where the new repo dir is created.")
def new_agent(name: str, target: str) -> None:
    """Scaffold a new agent repo."""
    _render_tree(TEMPLATES / "agent", Path(target), name)
    click.echo(f"Scaffolded ai-agent-{name} at {target}")


@new.command("mcp")
@click.option("--name", required=True, help="Short MCP name (e.g., 'foo' for ai-mcp-foo).")
@click.option("--target", type=click.Path(), required=True, help="Path where the new repo dir is created.")
def new_mcp(name: str, target: str) -> None:
    """Scaffold a new MCP server repo."""
    _render_tree(TEMPLATES / "mcp", Path(target), name)
    click.echo(f"Scaffolded ai-mcp-{name} at {target}")


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


if __name__ == "__main__":
    cli()
