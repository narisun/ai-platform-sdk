"""
Platform SDK — Protocol definitions for dependency injection and testability.

Define abstract interfaces (Protocols) for all cross-cutting services so that
production code depends on protocols, not concrete implementations. Tests inject
lightweight fakes; production code injects the real implementations.

This enables clean unit testing of graph nodes, MCP servers, and orchestrators
without requiring Docker, Redis, OPA, or live LLM connections.
"""
from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable


@runtime_checkable
class Authorizer(Protocol):
    """Policy-based authorization for tool calls."""

    async def authorize(self, tool_name: str, payload: dict) -> bool:
        """Return True if the tool call is allowed, False otherwise."""
        ...

    async def aclose(self) -> None:
        """Release any underlying resources."""
        ...


@runtime_checkable
class CacheStore(Protocol):
    """Key-value cache with TTL for tool results."""

    async def get(self, key: str) -> Optional[str]:
        """Return cached value or None."""
        ...

    async def set(self, key: str, value: str) -> None:
        """Store value with TTL."""
        ...

    async def aclose(self) -> None:
        """Release any underlying resources."""
        ...


@runtime_checkable
class LLMClient(Protocol):
    """Interface for LLM completion calls."""

    async def generate(
        self, model_route: str, messages: list[dict], **kwargs: Any
    ) -> Any:
        """Send a chat completion request and return the response."""
        ...


@runtime_checkable
class ToolBridge(Protocol):
    """Interface for MCP tool bridge connections."""

    @property
    def is_connected(self) -> bool:
        """True when the bridge is ready for tool calls."""
        ...

    async def connect(self, startup_timeout: float = 60.0) -> "ToolBridge":
        """Start the connection and wait for readiness."""
        ...

    async def disconnect(self) -> None:
        """Shut down the connection."""
        ...

    async def get_langchain_tools(self) -> list:
        """Return LangChain StructuredTool objects for all registered tools."""
        ...
