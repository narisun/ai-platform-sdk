"""
Platform SDK — Shared test utilities, personas, and fake implementations.

Provides:
- TEST_PERSONAS: Centralized test persona definitions for RM Prep access control testing.
- AlwaysAllowAuthorizer / AlwaysDenyAuthorizer: Fake Authorizer implementations.
- InMemoryCache: Fake CacheStore backed by a Python dict.
- MockLLMClient: Fake LLMClient that returns canned responses.
- FakeToolBridge: Fake ToolBridge for testing graph nodes without MCP servers.

All fakes implement the Protocol interfaces from platform_sdk.protocols.
"""
from __future__ import annotations

from typing import Any, Optional


# ---------------------------------------------------------------------------
# Test Personas
# ---------------------------------------------------------------------------
# Account IDs are from the test seed data (platform/db/21_test_sfcrm_seed.sql):
#   001000000000001AAA = Microsoft Corp.
#   001000000000002AAA = Ford Motor Company

TEST_PERSONAS: dict[str, dict] = {
    "manager": {
        "rm_id": "test-manager-001",
        "rm_name": "Alice Manager (test)",
        "role": "manager",
        "team_id": "test-team",
        "assigned_account_ids": [],
        "compliance_clearance": ["standard", "aml_view", "compliance_full"],
        "description": "Full access — all accounts, all compliance columns",
    },
    "senior_rm": {
        "rm_id": "test-senior-rm-001",
        "rm_name": "Bob Senior RM (test)",
        "role": "senior_rm",
        "team_id": "test-team",
        "assigned_account_ids": [],
        "compliance_clearance": ["standard", "aml_view"],
        "description": "All accounts, AML columns visible, compliance columns masked",
    },
    "rm": {
        "rm_id": "test-rm-001",
        "rm_name": "Carol RM (test)",
        "role": "rm",
        "team_id": "test-team",
        "assigned_account_ids": [
            "001000000000001AAA",  # Microsoft Corp.
            "001000000000002AAA",  # Ford Motor Company
        ],
        "compliance_clearance": ["standard"],
        "description": "Row-restricted to 2 accounts (Microsoft, Ford); PII and AML columns masked",
    },
    "readonly": {
        "rm_id": "test-readonly-001",
        "rm_name": "Dave Readonly (test)",
        "role": "readonly",
        "team_id": "test-team",
        "assigned_account_ids": [],
        "compliance_clearance": ["standard"],
        "description": "No data access — all tool calls return access_denied",
    },
}


# ---------------------------------------------------------------------------
# Fake Authorizer implementations
# ---------------------------------------------------------------------------

class AlwaysAllowAuthorizer:
    """Authorizer that permits every tool call. Use in unit tests."""

    async def authorize(self, tool_name: str, payload: dict) -> bool:
        return True

    async def aclose(self) -> None:
        pass


class AlwaysDenyAuthorizer:
    """Authorizer that blocks every tool call. Use for denial-path tests."""

    async def authorize(self, tool_name: str, payload: dict) -> bool:
        return False

    async def aclose(self) -> None:
        pass


class RecordingAuthorizer:
    """Authorizer that records calls for assertion and delegates to a flag."""

    def __init__(self, allow: bool = True) -> None:
        self._allow = allow
        self.calls: list[tuple[str, dict]] = []

    async def authorize(self, tool_name: str, payload: dict) -> bool:
        self.calls.append((tool_name, payload))
        return self._allow

    async def aclose(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Fake CacheStore implementation
# ---------------------------------------------------------------------------

class InMemoryCache:
    """Dict-backed cache for testing. Supports get/set/aclose from CacheStore protocol."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> Optional[str]:
        return self._store.get(key)

    async def set(self, key: str, value: str) -> None:
        self._store[key] = value

    async def aclose(self) -> None:
        self._store.clear()


# ---------------------------------------------------------------------------
# Fake LLM Client implementation
# ---------------------------------------------------------------------------

class MockLLMResponse:
    """Minimal mock of an OpenAI ChatCompletion response."""

    def __init__(self, content: str, model: str = "mock-model") -> None:
        self.choices = [_MockChoice(content)]
        self.model = model
        self.usage = _MockUsage()


class _MockChoice:
    def __init__(self, content: str) -> None:
        self.message = _MockMessage(content)
        self.finish_reason = "stop"


class _MockMessage:
    def __init__(self, content: str) -> None:
        self.content = content
        self.role = "assistant"


class _MockUsage:
    prompt_tokens = 10
    completion_tokens = 20
    total_tokens = 30


class MockLLMClient:
    """LLMClient that returns canned responses. Configurable per model_route."""

    def __init__(
        self,
        default_response: str = "Mock LLM response.",
        route_responses: Optional[dict[str, str]] = None,
    ) -> None:
        self._default = default_response
        self._routes: dict[str, str] = route_responses or {}
        self.calls: list[dict[str, Any]] = []

    async def generate(
        self, model_route: str, messages: list[dict], **kwargs: Any
    ) -> MockLLMResponse:
        self.calls.append({"model_route": model_route, "messages": messages, **kwargs})
        content = self._routes.get(model_route, self._default)
        return MockLLMResponse(content=content, model=model_route)


# ---------------------------------------------------------------------------
# Fake ToolBridge implementation
# ---------------------------------------------------------------------------

class FakeToolBridge:
    """ToolBridge that returns pre-configured tool results without MCP servers."""

    def __init__(
        self,
        tool_results: Optional[dict[str, str]] = None,
        connected: bool = True,
    ) -> None:
        self._tool_results: dict[str, str] = tool_results or {}
        self._connected = connected

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self, startup_timeout: float = 60.0) -> "FakeToolBridge":
        self._connected = True
        return self

    async def disconnect(self) -> None:
        self._connected = False

    async def get_langchain_tools(self) -> list:
        from langchain_core.tools import StructuredTool

        tools = []
        for name, result in self._tool_results.items():
            async def _invoke(tool_name=name, tool_result=result, **kwargs) -> str:
                return tool_result

            tools.append(
                StructuredTool.from_function(
                    coroutine=_invoke,
                    name=name,
                    description=f"Fake tool: {name}",
                )
            )
        return tools
