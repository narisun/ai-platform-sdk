"""
Enterprise AI Platform SDK — public API surface.

Observability:
    configure_logging()              — structlog JSON logging
    get_logger(name)                 — structured logger
    setup_telemetry(svc)             — OpenTelemetry init (idempotent)

LLM client:
    EnterpriseLLMClient              — thin LiteLLM proxy wrapper

Configuration:
    AgentConfig                      — typed config for agents (from_env())
    MCPConfig                        — typed config for MCP servers (from_env())

Security:
    OpaClient                        — async OPA client (fail-closed, retry)
    make_api_key_verifier()          — FastAPI Bearer-token dependency
    AgentContext                     — JWT-verified RM session context
                                       (role, assigned_account_ids, clearance)

Caching:
    ToolResultCache                  — Redis-backed tool result cache
    cached_tool(cache)               — decorator: cache get/set for async tools

Compaction:
    make_compaction_modifier(config) — LangGraph state_modifier for token trimming

Agent factories:
    build_agent(tools, config, prompt)
        Standard ReAct agent with compaction + LiteLLM routing.

    build_specialist_agent(tools, config, prompt, model_override)
        Same as build_agent but accepts a per-specialist model override.
        Used by orchestrators for model tiering (cheap specialists,
        expensive synthesis).
"""
from .agent import build_agent, build_specialist_agent, make_chat_llm
from .auth import AgentContext
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
    "AgentContext",
    # Caching
    "ToolResultCache",
    "cached_tool",
    # Compaction
    "make_compaction_modifier",
    # Agent factories
    "build_agent",
    "build_specialist_agent",
    "make_chat_llm",
]
