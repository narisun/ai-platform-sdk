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
