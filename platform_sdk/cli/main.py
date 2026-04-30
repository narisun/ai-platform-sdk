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


if __name__ == "__main__":
    cli()
