"""platform-sdk error classes.

Currently exports:
  UnsupportedSchemaError — raised by MCPToolBridge._convert_schema when an
                            MCP tool's inputSchema uses a JSON Schema keyword
                            this SDK cannot translate ($ref / allOf / anyOf /
                            oneOf at the top level). Phase 6.5 P0 fix.
"""
from __future__ import annotations


class UnsupportedSchemaError(Exception):
    """Raised when an MCP tool's inputSchema cannot be converted.

    Carries the offending tool name and the unsupported keyword so the
    caller can render a meaningful diagnostic without regex-parsing the
    error message.
    """

    def __init__(self, tool_name: str, keyword: str) -> None:
        self.tool_name = tool_name
        self.keyword = keyword
        super().__init__(
            f"MCP tool {tool_name!r} schema uses unsupported keyword {keyword!r}"
        )
