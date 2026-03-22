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
from .auth import AgentContext, assert_secrets_configured
from .authorized_tool import authorized_tool, is_error_response, make_error
from .bridge_health import BridgeHealthMatrix
from .cache import ToolResultCache, cached_tool
from .compaction import make_compaction_modifier
from .config import AgentConfig, MCPConfig
from .llm_client import EnterpriseLLMClient
from .logging import configure_logging, get_logger
from .mcp_server_base import BaseMCPServer, make_health_router
from .metrics import (
    record_cache_state,
    record_cache_transition,
    record_opa_decision,
    record_opa_circuit_state,
    record_mcp_tool_call,
)
from .protocols import Authorizer, CacheStore, LLMClient, ToolBridge
from .security import OpaClient, make_api_key_verifier
from .telemetry import setup_telemetry
from .models import (
    ErrorDetail,
    ToolResponse,
    make_tool_error,
    make_tool_success,
    SalesforceSummaryData,
    PaymentSummaryData,
    NewsSummaryData,
)

# MCP Bridge — optional dependency (requires `mcp` package).
# Consumers that don't connect to MCP servers (e.g. portfolio-watch) can
# import the SDK without installing the `mcp` package.
try:
    from .mcp_bridge import MCPToolBridge, reset_session_id, set_session_id
except ImportError:
    MCPToolBridge = None  # type: ignore[assignment,misc]
    set_session_id = None  # type: ignore[assignment]
    reset_session_id = None  # type: ignore[assignment]

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
    "assert_secrets_configured",
    # Authorization
    "authorized_tool",
    "make_error",
    "is_error_response",
    # Bridge health
    "BridgeHealthMatrix",
    # Caching
    "ToolResultCache",
    "cached_tool",
    # Compaction
    "make_compaction_modifier",
    # Metrics
    "record_cache_state",
    "record_cache_transition",
    "record_opa_decision",
    "record_opa_circuit_state",
    "record_mcp_tool_call",
    # Protocols (for dependency injection / testability)
    "Authorizer",
    "CacheStore",
    "LLMClient",
    "ToolBridge",
    # MCP Server base
    "BaseMCPServer",
    "make_health_router",
    # Agent factories
    "build_agent",
    "build_specialist_agent",
    "make_chat_llm",
    # Response models
    "ErrorDetail",
    "ToolResponse",
    "make_tool_error",
    "make_tool_success",
    "SalesforceSummaryData",
    "PaymentSummaryData",
    "NewsSummaryData",
    # MCP Bridge
    "MCPToolBridge",
    "set_session_id",
    "reset_session_id",
]
