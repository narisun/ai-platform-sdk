"""
Enterprise AI Platform SDK — public API surface.

Observability:
    configure_logging()              — structlog JSON logging
    get_logger(name)                 — structured logger
    setup_telemetry(svc)             — OpenTelemetry tracing + auto-instrumentation
    get_langfuse()                   — LangFuse client for prompt management (or None)
    get_langfuse_callback_handler()  — DEPRECATED: always returns None (traces via OTel)

Prompt management (via LangFuse):
    PromptManager                    — centralized prompt management with caching

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

OOP base classes:
    Application                      — abstract root for all services
    Agent                            — base class for LangGraph agents
    McpService                       — base class for FastMCP servers

Service classes:
    AgentBuilder                     — wraps build_agent / build_specialist_agent
    ChatLLMFactory                   — creates ChatOpenAI instances
    CheckpointerFactory              — creates memory / postgres checkpointers
    ApiKeyVerifier                   — wraps make_api_key_verifier as a class
"""
from .agent import build_agent, build_specialist_agent, make_chat_llm, make_checkpointer
from .auth import AgentContext, assert_secrets_configured
from .authorized_tool import authorized_tool, is_error_response, make_error
from .bridge_health import BridgeHealthMatrix
from .cache import ToolResultCache, cached_tool
from .compaction import make_compaction_modifier
from .config import AgentConfig, MCPConfig
from .llm_client import EnterpriseLLMClient
from .logging import configure_logging, get_logger
from .mcp_server_base import BaseMCPServer, BaseResources, create_base_resources, make_health_router
from .metrics import (
    record_cache_state,
    record_cache_transition,
    record_opa_decision,
    record_opa_circuit_state,
    record_mcp_tool_call,
)
from .prompts import PromptLoader
from .prompt_manager import PromptManager
from .protocols import Authorizer, CacheStore, LLMClient, PortfolioDataSource, ToolBridge
from .resilience import CircuitBreaker
from .security import OpaClient, make_api_key_verifier
from .telemetry import setup_telemetry, get_langfuse, get_langfuse_callback_handler, flush_langfuse
from .models import (
    ErrorDetail,
    ToolResponse,
    make_tool_error,
    make_tool_success,
    SalesforceSummaryData,
    PaymentSummaryData,
    NewsSummaryData,
)

# OOP base classes — Application hierarchy and service wrappers.
from .base import Application, Agent, McpService
from .services import AgentBuilder, ChatLLMFactory, CheckpointerFactory, ApiKeyVerifier

# MCP Bridge — optional dependency (requires `mcp` package).
try:
    from .mcp_bridge import (
        MCPToolBridge,
        reset_session_id,
        set_session_id,
        set_user_auth_token,
        reset_user_auth_token,
    )
except ImportError:
    MCPToolBridge = None  # type: ignore[assignment,misc]
    set_session_id = None  # type: ignore[assignment]
    reset_session_id = None  # type: ignore[assignment]
    set_user_auth_token = None  # type: ignore[assignment]
    reset_user_auth_token = None  # type: ignore[assignment]

__all__ = [
    # Observability
    "configure_logging",
    "get_logger",
    "setup_telemetry",
    "get_langfuse",
    "get_langfuse_callback_handler",
    "flush_langfuse",
    # Prompt management
    "PromptManager",
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
    "PortfolioDataSource",
    "ToolBridge",
    # Resilience
    "CircuitBreaker",
    # Prompt loading
    "PromptLoader",
    # MCP Server base (legacy — prefer McpService for new servers)
    "BaseMCPServer",
    "BaseResources",
    "create_base_resources",
    "make_health_router",
    # OOP base classes
    "Application",
    "Agent",
    "McpService",
    # Service classes
    "AgentBuilder",
    "ChatLLMFactory",
    "CheckpointerFactory",
    "ApiKeyVerifier",
    # Agent factories (legacy — prefer AgentBuilder for new code)
    "build_agent",
    "build_specialist_agent",
    "make_chat_llm",
    "make_checkpointer",
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
    "set_user_auth_token",
    "reset_user_auth_token",
]
