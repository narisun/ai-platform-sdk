"""FastAPI app factory base — symmetric to platform_sdk.base.McpService.lifespan().

Provides BaseAgentApp: subclasses declare service_name, mcp_servers, and
implement build_dependencies() + routes(). The base class handles telemetry,
MCP bridge connection, checkpointer construction, and conversation-store
wiring during a FastAPI lifespan.
"""
from .base import BaseAgentApp

__all__ = ["BaseAgentApp"]
