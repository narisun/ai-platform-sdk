"""
Platform SDK — Authorized tool decorator for MCP servers.

Extracts the cross-cutting OPA + AgentContext + error-format logic
from individual MCP tool functions into a reusable decorator.

Usage:
    from platform_sdk.authorized_tool import authorized_tool, ToolError

    @mcp.tool()
    @authorized_tool(opa_ref=lambda: _opa, tool_name="get_payment_summary")
    async def get_payment_summary(client_name: str) -> str:
        ...  # pure business logic — OPA already checked

Error convention:
    All errors are returned as JSON: {"error": "<code>", "message": "<human-readable>"}
    The cached_tool decorator recognises this format and skips caching.
"""
import json
from functools import wraps
from typing import Any, Callable, Optional

from .logging import get_logger

log = get_logger(__name__)


# Standard error codes
ERROR_NOT_INITIALISED = "service_not_initialised"
ERROR_UNAUTHORIZED = "unauthorized"
ERROR_INVALID_INPUT = "invalid_input"
ERROR_DATABASE = "database_error"
ERROR_INTERNAL = "internal_error"


def make_error(code: str, message: str) -> str:
    """Return a JSON error string in the standardised format.

    All MCP tool errors should use this function so the format is consistent
    and the cached_tool decorator can recognise errors reliably.
    """
    return json.dumps({"error": code, "message": message})


def is_error_response(response: str) -> bool:
    """Check if a response is an error in either the new JSON format or legacy ERROR: prefix."""
    if response.startswith("ERROR:"):
        return True
    try:
        data = json.loads(response)
        return isinstance(data, dict) and "error" in data
    except (json.JSONDecodeError, TypeError):
        return False


def authorized_tool(
    opa_ref: Callable[[], Any],
    tool_name: str,
    require_input: Optional[str] = None,
    max_input_length: int = 256,
) -> Callable:
    """
    Decorator factory that wraps an MCP tool with OPA authorization and
    standardised error handling.

    Args:
        opa_ref:          Callable that returns the OpaClient instance (lambda for lazy binding).
        tool_name:        Tool name for OPA policy evaluation.
        require_input:    If set, the name of the first argument that must be non-empty.
        max_input_length: Maximum length for the required input (truncated, not rejected).

    The decorated function receives the validated, truncated arguments.
    """
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        async def wrapper(**kwargs) -> str:
            opa = opa_ref()
            if opa is None:
                return make_error(ERROR_NOT_INITIALISED, "OPA client not ready.")

            # Validate required input
            if require_input:
                value = kwargs.get(require_input, "")
                if not value or not str(value).strip():
                    return make_error(ERROR_INVALID_INPUT, f"{require_input} must not be empty.")
                # Truncate excessively long inputs
                kwargs[require_input] = str(value).strip()[:max_input_length]

            # OPA authorization
            is_authorized = await opa.authorize(tool_name, kwargs)
            if not is_authorized:
                log.warning("opa_denied", tool=tool_name)
                return make_error(ERROR_UNAUTHORIZED, "Execution blocked by policy engine.")

            try:
                return await fn(**kwargs)
            except Exception as exc:
                log.error(
                    "tool_error",
                    tool=tool_name,
                    exc_type=type(exc).__name__,
                    error=str(exc),
                )
                return make_error(ERROR_DATABASE, "A database error occurred. Please try again.")

        return wrapper
    return decorator
