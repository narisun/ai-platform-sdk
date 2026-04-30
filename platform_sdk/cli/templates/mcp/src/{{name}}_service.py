"""ai-mcp-{{name}} — MCP service class."""
from typing import Any

from platform_sdk import MCPConfig, get_logger, make_error
from platform_sdk.base import McpService

log = get_logger(__name__)


class {{Name}}McpService(McpService):
    cache_ttl_seconds = 300
    requires_database = False
    enable_telemetry = True

    async def on_startup(self) -> None:
        log.info("{{name}}_mcp_ready")

    def register_tools(self, mcp: Any) -> None:
        @mcp.tool()
        async def hello(name: str = "world") -> str:
            return f"Hello, {name}!"
