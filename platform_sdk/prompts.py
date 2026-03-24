"""
Platform SDK — Sandboxed Jinja2 prompt loader.

Provides a thin, injectable wrapper around Jinja2's SandboxedEnvironment
so that:

1. Prompt templates cannot execute arbitrary Python via SSTI
   (e.g. {{ config.__class__.__mro__ }}).
2. The prompt directory is injectable — tests can use a temp directory
   with minimal test-only templates.
3. The loader is immutable (frozen dataclass) and safe to share across
   concurrent async requests.

Usage:
    from platform_sdk.prompts import PromptLoader

    prompts = PromptLoader.from_directory(Path("src/prompts"))
    text = prompts.render("router.j2", client_name="Acme", has_brief=True)

Testing:
    prompts = PromptLoader.from_directory(Path("tests/fixtures/prompts"))
    # or inject a mock that returns static strings
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class PromptLoader:
    """Sandboxed Jinja2 prompt renderer.  Inject into graph builders."""

    _env: Any  # jinja2.SandboxedEnvironment — typed as Any to allow lazy import

    @classmethod
    def from_directory(cls, prompt_dir: Path) -> "PromptLoader":
        """Create a PromptLoader that reads templates from *prompt_dir*.

        Uses SandboxedEnvironment to prevent server-side template injection.
        autoescape=False is correct for LLM prompt templates (not HTML).
        """
        try:
            from jinja2.sandbox import SandboxedEnvironment
            from jinja2 import FileSystemLoader
        except ImportError:
            raise RuntimeError(
                "jinja2 is required for PromptLoader — run: pip install jinja2"
            )

        env = SandboxedEnvironment(
            loader=FileSystemLoader(str(prompt_dir)),
            autoescape=False,
        )
        log.info("prompt_loader_ready", directory=str(prompt_dir))
        return cls(_env=env)

    def render(self, template_name: str, **context: Any) -> str:
        """Render a template with the given context variables."""
        return self._env.get_template(template_name).render(**context)
