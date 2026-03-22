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

log = get_logger(__name__)


class OpaClient:
    """
    Reusable async OPA decision client.

    Design principles:
    - Fail CLOSED: any error (timeout, HTTP error, exception) denies the call.
    - Configurable retry with back-off on transient network errors.
    - Circuit breaker: after N consecutive failures, fail fast for a recovery
      period before probing again (prevents latency amplification during outages).
    - Shared httpx.AsyncClient connection pool — no new TCP connection per call.
    - Environment and agent_role are SERVER-STAMPED, never read from the caller's
      payload, preventing the local-env bypass attack (code review finding H3).
    """

    def __init__(self, config: MCPConfig) -> None:
        self._url         = config.opa_url
        self._environment = config.environment   # stamped server-side
        self._agent_role  = config.agent_role    # stamped server-side
        self._max_retries = getattr(config, 'opa_max_retries', 2)
        self._retry_backoff = getattr(config, 'opa_retry_backoff', 0.2)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=1.0,
                read=config.opa_timeout_seconds,
                write=config.opa_timeout_seconds,
                pool=config.opa_timeout_seconds,
            ),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        # Circuit breaker state
        self._cb_threshold = getattr(config, 'cb_failure_threshold', 5)
        self._cb_recovery_timeout = getattr(config, 'cb_recovery_timeout', 30.0)
        self._consecutive_failures = 0
        self._circuit_open_until: float = 0.0
        log.info("opa_client_ready", url=self._url)

    # Methods to support 'async with OpaClient() as opa:'
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.aclose()

    def _is_circuit_open(self) -> bool:
        """Check if the circuit breaker is open (fail-fast mode)."""
        import time
        if self._consecutive_failures < self._cb_threshold:
            return False
        if time.monotonic() >= self._circuit_open_until:
            # Recovery timeout elapsed — allow a probe
            return False
        return True

    def _record_success(self) -> None:
        """Reset circuit breaker on successful OPA call."""
        if self._consecutive_failures > 0:
            log.info("opa_circuit_closed", after_failures=self._consecutive_failures)
        self._consecutive_failures = 0

    def _record_failure(self) -> None:
        """Track failure and potentially open the circuit breaker."""
        import time
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._cb_threshold:
            self._circuit_open_until = time.monotonic() + self._cb_recovery_timeout
            log.warning(
                "opa_circuit_opened",
                failures=self._consecutive_failures,
                recovery_seconds=self._cb_recovery_timeout,
            )

    async def authorize(self, tool_name: str, payload: dict) -> bool:
        """
        Ask OPA whether tool_name is allowed for the given payload.

        Environment and agent_role are always overwritten with server-side
        values so callers cannot escalate privileges by injecting them.

        Returns True if OPA grants access, False on denial or any error.
        Circuit breaker: after consecutive failures, fails fast without network calls.
        """
        # Circuit breaker: fail fast if OPA is known to be unavailable
        if self._is_circuit_open():
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
                self._record_success()
                log.info(
                    "opa_decision",
                    tool=tool_name, allowed=decision, attempt=attempt + 1,
                )
                return decision

            except httpx.TimeoutException:
                log.warning("opa_timeout", tool=tool_name, attempt=attempt + 1)
                self._record_failure()

            except httpx.HTTPStatusError as exc:
                log.error(
                    "opa_http_error",
                    tool=tool_name, status=exc.response.status_code,
                )
                self._record_failure()
                return False  # fail closed immediately — no retry on HTTP errors

            except Exception as exc:
                log.error(
                    "opa_error",
                    tool=tool_name, error=str(exc), attempt=attempt + 1,
                )
                self._record_failure()

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


def make_api_key_verifier(api_key: Optional[str] = None):
    """
    Return a FastAPI dependency that validates Bearer tokens.

    If api_key is None the value is read from INTERNAL_API_KEY at call time,
    so the returned dependency can be created at module level safely even if
    the environment variable isn't set during import.

    Usage:
        verify = make_api_key_verifier()

        @app.post("/endpoint")
        async def endpoint(_: str = Depends(verify)):
            ...
    """
    # Lazy FastAPI import — services without FastAPI (e.g. MCP servers) can
    # still import the rest of this module without pulling in FastAPI.
    from fastapi import HTTPException, Security
    from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

    _bearer = HTTPBearer(auto_error=True)

    # Capture the key at verifier-creation time if provided; otherwise read
    # from environment on every request (safer for late-binding test setups).
    _static_key: Optional[str] = api_key

    async def _verify(
        credentials: HTTPAuthorizationCredentials = Security(_bearer),
    ) -> str:
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
        return credentials.credentials

    return _verify
