"""
Platform SDK — Security primitives.

Provides two reusable building blocks:

OpaClient
    Async OPA decision client with retry, fail-closed semantics, and
    server-side environment/role stamping.  Extracted from data-mcp so
    every new MCP server inherits the same policy-enforcement behaviour.

make_api_key_verifier()
    Returns a FastAPI dependency that validates Bearer tokens against
    INTERNAL_API_KEY.  Extracted from the agent service so every new
    FastAPI service gets consistent authentication without copy-paste.

Example — MCP server:
    from platform_sdk import MCPConfig
    from platform_sdk.security import OpaClient

    config = MCPConfig.from_env()
    opa    = OpaClient(config)

    @mcp.tool()
    async def my_tool(query: str, session_id: str) -> str:
        if not await opa.authorize("my_tool", {"query": query, "session_id": session_id}):
            return "ERROR: Unauthorized."
        ...

Example — FastAPI service:
    from platform_sdk.security import make_api_key_verifier

    verify = make_api_key_verifier()

    @app.post("/chat")
    async def chat(body: ChatRequest, _: str = Depends(verify)):
        ...
"""
import asyncio
import hmac
import os
from typing import Optional

import httpx

from .config import MCPConfig
from .logging import get_logger
from .resilience import CircuitBreaker

log = get_logger(__name__)


class OpaClient:
    """
    Reusable async OPA decision client.

    Design principles:
    - Fail CLOSED: any error (timeout, HTTP error, exception) denies the call.
    - Configurable retry with back-off on transient network errors.
    - Circuit breaker (via reusable CircuitBreaker): after N consecutive failures,
      fail fast for a recovery period before probing again.
    - Shared httpx.AsyncClient connection pool — no new TCP connection per call.
    - Environment and agent_role are SERVER-STAMPED, never read from the caller's
      payload, preventing the local-env bypass attack (code review finding H3).
    """

    def __init__(self, config: MCPConfig) -> None:
        self._url         = config.opa_url
        self._environment = config.environment   # stamped server-side
        self._agent_role  = config.agent_role    # stamped server-side
        self._max_retries = config.opa_max_retries
        self._retry_backoff = config.opa_retry_backoff
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=1.0,
                read=config.opa_timeout_seconds,
                write=config.opa_timeout_seconds,
                pool=config.opa_timeout_seconds,
            ),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        self._cb = CircuitBreaker(
            name="opa",
            failure_threshold=config.cb_failure_threshold,
            recovery_timeout=config.cb_recovery_timeout,
        )
        log.info("opa_client_ready", url=self._url)

    # Methods to support 'async with OpaClient() as opa:'
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.aclose()

    async def authorize(self, tool_name: str, payload: dict) -> bool:
        """
        Ask OPA whether tool_name is allowed for the given payload.

        Environment and agent_role are always overwritten with server-side
        values so callers cannot escalate privileges by injecting them.

        Returns True if OPA grants access, False on denial or any error.
        Circuit breaker: after consecutive failures, fails fast without network calls.
        """
        # Circuit breaker: fail fast if OPA is known to be unavailable
        if self._cb.is_open:
            log.warning("opa_circuit_open_deny", tool=tool_name)
            return False

        input_data = {
            **payload,
            "tool": tool_name,
            "environment": self._environment,   # overrides any caller-supplied value
            "agent_role":  self._agent_role,    # overrides any caller-supplied value
        }

        for attempt in range(self._max_retries):
            try:
                response = await self._client.post(
                    self._url, json={"input": input_data}
                )
                response.raise_for_status()
                decision = bool(response.json().get("result", False))
                self._cb.record_success()
                log.info(
                    "opa_decision",
                    tool=tool_name, allowed=decision, attempt=attempt + 1,
                )
                return decision

            except httpx.TimeoutException:
                log.warning("opa_timeout", tool=tool_name, attempt=attempt + 1)
                self._cb.record_failure()

            except httpx.HTTPStatusError as exc:
                log.error(
                    "opa_http_error",
                    tool=tool_name, status=exc.response.status_code,
                )
                self._cb.record_failure()
                return False  # fail closed immediately — no retry on HTTP errors

            except Exception as exc:
                log.error(
                    "opa_error",
                    tool=tool_name, error=str(exc), attempt=attempt + 1,
                )
                self._cb.record_failure()

            if attempt < self._max_retries - 1:
                await asyncio.sleep(self._retry_backoff)  # backoff before retry

        log.error(
            "opa_unavailable",
            tool=tool_name, reason="all retries exhausted — denying",
        )
        return False  # fail closed

    async def aclose(self) -> None:
        """Release the underlying connection pool."""
        await self._client.aclose()
        log.info("opa_client_closed")

    @classmethod
    def from_env(cls) -> "OpaClient":
        """Convenience constructor that reads all settings from environment."""
        return cls(MCPConfig.from_env())


def make_api_key_verifier(
    api_key: Optional[str] = None,
    *,
    environment: Optional[str] = None,
):
    """Return a FastAPI dependency that validates Bearer tokens and (optionally) X-Environment.

    If `environment` is provided (a string from the Environment Literal),
    the dependency also requires an `X-Environment` header equal to that
    value. Mismatch returns 403; absence returns 403. This is the
    inbound half of L3 environment isolation.

    If `api_key` is None the value is read from INTERNAL_API_KEY at call
    time, so the returned dependency can be created at module level
    safely even if the environment variable isn't set during import.
    """
    from fastapi import HTTPException, Request, Security
    from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

    from .config.env_isolation import ENV_HEADER

    _bearer = HTTPBearer(auto_error=True)
    _static_key: Optional[str] = api_key
    _env: Optional[str] = environment

    async def _verify(
        request: Request,
        credentials: HTTPAuthorizationCredentials = Security(_bearer),
    ) -> str:
        # ---- Bearer token ----
        key = _static_key or os.environ.get("INTERNAL_API_KEY", "")
        if not key:
            log.error("auth_misconfigured", reason="INTERNAL_API_KEY not set")
            raise HTTPException(
                status_code=500,
                detail="Service temporarily unavailable. Contact your administrator.",
            )
        if not hmac.compare_digest(credentials.credentials, key):
            log.warning("auth_rejected", reason="invalid_api_key")
            raise HTTPException(status_code=401, detail="Unauthorized")

        # ---- X-Environment (only when configured) ----
        if _env is not None:
            got = request.headers.get(ENV_HEADER)
            if got != _env:
                log.warning(
                    "environment_mismatch_rejected",
                    expected_env=_env,
                    got_env=got,
                    peer_ip=request.client.host if request.client else "",
                )
                raise HTTPException(
                    status_code=403,
                    detail={
                        "error": "environment_mismatch",
                        "expected": _env,
                        "got": got or "",
                    },
                )

        return credentials.credentials

    return _verify
