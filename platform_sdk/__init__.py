"""
Enterprise AI Platform SDK.

Public surface area — everything a new agent or MCP server needs:

  Observability
    configure_logging()     — set up structlog JSON logging
    get_logger(name)        — get a structured logger
    setup_telemetry(svc)    — initialise OpenTelemetry (idempotent)

  LLM client
    EnterpriseLLMClient     — thin wrapper around LiteLLM proxy

  Configuration
    AgentConfig             — typed config for LangGraph agents (from_env())
    MCPConfig               — typed config for FastMCP servers (from_env())

  Security
    OpaClient               — async OPA decision client (fail-closed, retry)
    make_api_key_verifier() — FastAPI Bearer-token dependency factory

  Caching
    ToolResultCache         — Redis-backed tool result cache (graceful degradation)
    cached_tool(cache)      — decorator that adds cache get/set to an async tool

  Compaction
    make_compaction_modifier(config) — LangGraph state_modifier for context trimming

  Agent factory
    build_agent(tools, config, prompt) — build a LangGraph ReAct agent with
                                         compaction and LiteLLM routing wired in
"""
from .agent import build_agent
from .cache import ToolResultCache, cached_tool
from .compaction import make_compaction_modifier
from .config import AgentConfig, MCPConfig
from .llm_client import EnterpriseLLMClient
from .logging import configure_logging, get_logger
from .security import OpaClient, make_api_key_verifier
from .telemetry import setup_telemetry

__all__ = [
    # Observability
    "configure_logging",
    "get_logger",
    "setup_telemetry",
    # LLM client
    "EnterpriseLLMClient",
    # Configuration
    "AgentConfig",
    "MCPConfig",
    # Security
    "OpaClient",
    "make_api_key_verifier",
    # Caching
    "ToolResultCache",
    "cached_tool",
    # Compaction
    "make_compaction_modifier",
    # Agent factory
    "build_agent",
]
