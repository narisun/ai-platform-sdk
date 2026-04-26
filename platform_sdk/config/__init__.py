"""
Platform SDK — Typed configuration dataclasses.

Every tunable parameter for agents and MCP servers is defined here with
sensible defaults and read from environment variables via ``from_env()``.

This module is the **single source of truth** for all environment-variable
based configuration. Production code outside this file (and ``auth.py``
for security secrets) should never call ``os.environ.get`` directly —
instead, read from the ``AgentConfig`` or ``MCPConfig`` instance.
"""

from .agent_config import AgentConfig
from .mcp_config import MCPConfig
from .helpers import _env, _env_bool, _env_float, _env_int

__all__ = [
    "AgentConfig",
    "MCPConfig",
    "_env",
    "_env_int",
    "_env_float",
    "_env_bool",
]
