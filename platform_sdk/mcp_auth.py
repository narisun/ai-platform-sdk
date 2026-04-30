"""MCP server authorization middleware — ASGI middleware + ContextVar binding.

Decodes the X-Agent-Context request header and binds the resulting AgentContext
to a ContextVar so MCP tool handlers can read the per-request caller identity.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Optional

from .auth import AgentContext
from .logging import get_logger

log = get_logger(__name__)

_agent_context_var: ContextVar[Optional[AgentContext]] = ContextVar(
    "agent_context", default=None
)


def get_agent_context() -> Optional[AgentContext]:
    """Return the AgentContext for the current request, or None if unauthenticated."""
    return _agent_context_var.get()


class AgentContextMiddleware:
    """Starlette ASGI middleware that decodes X-Agent-Context and binds the
    resulting AgentContext into a ContextVar for the duration of the request."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] in ("http", "websocket"):
            headers = dict(scope.get("headers", []))
            raw = headers.get(b"x-agent-context", b"").decode()
            if raw:
                # Only catch exceptions from header parsing — NOT from self.app().
                # The original code wrapped both in one try/except, so any exception
                # raised by the app (e.g. an abrupt SSE disconnect after the response
                # had already started) was caught here, logged as
                # "invalid_agent_context_header" (a false alarm), and then self.app()
                # was called a second time.  That second call tried to send another
                # http.response.start into an already-started response, producing:
                #   RuntimeError: Expected ASGI message 'http.response.body',
                #                 but got 'http.response.start'.
                try:
                    ctx = AgentContext.from_header(raw)
                except Exception as exc:
                    log.warning("invalid_agent_context_header", error=str(exc))
                    # Fall through to the anonymous path below.
                else:
                    token = _agent_context_var.set(ctx)
                    try:
                        await self.app(scope, receive, send)
                    finally:
                        _agent_context_var.reset(token)
                    return
        if scope["type"] == "http":
            log.warning(
                "auth_context_fallback_anonymous",
                reason="missing_or_invalid_x_agent_context_header",
                path=scope.get("path", "unknown"),
            )
        await self.app(scope, receive, send)


def verify_auth_context(raw_token: str) -> AgentContext:
    """Verify an HMAC-signed `auth_context` token; fall back to anonymous on failure."""
    if not raw_token or not raw_token.strip():
        log.warning("verify_auth_context_empty", fallback="anonymous")
        return AgentContext.anonymous()
    try:
        return AgentContext.from_header(raw_token)
    except Exception as exc:
        log.warning("verify_auth_context_failed", error=str(exc), fallback="anonymous")
        return AgentContext.anonymous()
