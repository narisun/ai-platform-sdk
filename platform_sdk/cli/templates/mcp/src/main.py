"""ai-mcp-{{name}} — FastMCP entry point."""
import os

from mcp.server.fastmcp import FastMCP
from platform_sdk import configure_logging, get_logger

from .{{name}}_service import {{Name}}McpService

configure_logging()
log = get_logger(__name__)

TRANSPORT = os.environ.get("MCP_TRANSPORT", "stdio")
service = {{Name}}McpService("ai-mcp-{{name}}")

if TRANSPORT == "sse":
    mcp = FastMCP(
        "ai-mcp-{{name}}",
        lifespan=service.lifespan,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
    )
else:
    mcp = FastMCP("ai-mcp-{{name}}", lifespan=service.lifespan)

service.register_tools(mcp)


if __name__ == "__main__":
    log.info("mcp_server_starting", transport=TRANSPORT)
    mcp.run(transport=TRANSPORT)
