"""Platform SDK — typed configuration models and loader.

Every tunable parameter for agents and MCP servers is defined here as a
Pydantic v2 model. Load via `MCPConfig.load()` / `AgentConfig.load()` (or
the underlying `load_config()`). The loader is the single place that
reads os.environ — no other module in the SDK or in service code should
call os.environ.get directly.

Public API:
    AgentConfig
    MCPConfig
    load_config
    ConfigError
    ConfigErrorDetail
    Environment
    ENV_HEADER
"""
from .agent_config import AgentConfig
from .env_isolation import ENV_HEADER, Environment
from .loader import ConfigError, ConfigErrorDetail, load_config
from .mcp_config import MCPConfig

__all__ = [
    "AgentConfig",
    "MCPConfig",
    "load_config",
    "ConfigError",
    "ConfigErrorDetail",
    "Environment",
    "ENV_HEADER",
]
