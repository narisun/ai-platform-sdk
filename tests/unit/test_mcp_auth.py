"""Unit tests for platform_sdk.mcp_auth."""
import pytest

pytestmark = pytest.mark.unit


def test_module_exports_middleware_and_helpers():
    from platform_sdk.mcp_auth import (
        AgentContextMiddleware,
        get_agent_context,
        verify_auth_context,
    )
    assert AgentContextMiddleware is not None
    assert callable(get_agent_context)
    assert callable(verify_auth_context)


def test_get_agent_context_returns_none_outside_request():
    from platform_sdk.mcp_auth import get_agent_context
    assert get_agent_context() is None


def test_verify_auth_context_falls_back_anonymous_on_empty():
    from platform_sdk.mcp_auth import verify_auth_context
    ctx = verify_auth_context("")
    assert ctx is not None
    assert ctx.is_anonymous is True


def test_top_level_sdk_reexports_mcp_auth():
    """The SDK's __init__ should re-export mcp_auth symbols for one-line imports."""
    from platform_sdk import AgentContextMiddleware, get_agent_context, verify_auth_context
    assert AgentContextMiddleware is not None
    assert callable(get_agent_context)
    assert callable(verify_auth_context)
