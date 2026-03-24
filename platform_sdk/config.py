"""
Platform SDK — Typed configuration dataclasses.

Every tunable parameter for agents and MCP servers is defined here with
sensible defaults and read from environment variables via ``from_env()``.

This module is the **single source of truth** for all environment-variable
based configuration.  Production code outside this file (and ``auth.py``
for security secrets) should never call ``os.environ.get`` directly —
instead, read from the ``AgentConfig`` or ``MCPConfig`` instance.
"""
import os
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Helper for reading typed env vars with defaults
# ---------------------------------------------------------------------------

def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)))


def _env_float(name: str, default: float) -> float:
    return float(os.environ.get(name, str(default)))


def _env_bool(name: str, default: bool = True) -> bool:
    return os.environ.get(name, str(default).lower()).lower() == "true"


@dataclass
class AgentConfig:
    """
    Configuration for LangGraph agents.

    Covers model routing (including multi-agent tiering), LLM endpoint,
    context compaction, session checkpointing, and tool-result caching.
    All fields can be overridden via environment variables.

    Example:
        config = AgentConfig.from_env()
        agent  = build_agent(tools, config=config, prompt=system_prompt)
    """
    # ---- Primary model routing (backward compatible) ----
    model_route: str          = "complex-routing"
    summary_model_route: str  = "fast-routing"

    # ---- Multi-agent model tiering (orchestrator pattern) ----
    # router_model_route:     Haiku-class — intent parsing, routing decisions
    # specialist_model_route: Haiku-class — CRM / Payments / News specialists
    # synthesis_model_route:  Sonnet-class — final brief synthesis
    router_model_route: str      = "fast-routing"
    specialist_model_route: str  = "fast-routing"
    synthesis_model_route: str   = "complex-routing"

    # ---- LLM endpoint (LiteLLM proxy) ----
    litellm_base_url: str  = "http://localhost:4000/v1"
    internal_api_key: str  = ""

    # ---- Session / checkpointer ----
    # "memory" = MemorySaver (dev/test), "postgres" = PostgresSaver (prod)
    checkpointer_type: str       = "memory"
    checkpointer_db_url: str     = ""

    # ---- Context compaction ----
    enable_compaction: bool  = True
    context_token_limit: int = 6_000

    # ---- Safety limits ----
    recursion_limit: int     = 10
    max_message_length: int  = 32_000

    # ---- Tool-result caching ----
    enable_tool_cache: bool     = True
    tool_cache_ttl_seconds: int = 300

    # ---- MCP bridge startup ----
    mcp_startup_timeout: float = 120.0

    def __post_init__(self) -> None:
        """Validate configuration at construction time (fail-fast)."""
        errors: list[str] = []
        if self.context_token_limit < 100:
            errors.append(f"context_token_limit={self.context_token_limit} is too low (min 100)")
        if self.max_message_length < 100:
            errors.append(f"max_message_length={self.max_message_length} is too low (min 100)")
        if self.tool_cache_ttl_seconds < 0:
            errors.append(f"tool_cache_ttl_seconds={self.tool_cache_ttl_seconds} cannot be negative")
        if not self.model_route:
            errors.append("model_route must not be empty")
        if errors:
            raise ValueError(f"AgentConfig validation failed: {'; '.join(errors)}")

    @classmethod
    def from_env(cls) -> "AgentConfig":
        raw_recursion = _env_int("AGENT_RECURSION_LIMIT", cls.recursion_limit)
        return cls(
            model_route=_env("AGENT_MODEL_ROUTE", cls.model_route),
            summary_model_route=_env("SUMMARY_MODEL_ROUTE", cls.summary_model_route),
            router_model_route=_env("ROUTER_MODEL_ROUTE", cls.router_model_route),
            specialist_model_route=_env("SPECIALIST_MODEL_ROUTE", cls.specialist_model_route),
            synthesis_model_route=_env("SYNTHESIS_MODEL_ROUTE", cls.synthesis_model_route),
            litellm_base_url=_env("LITELLM_BASE_URL", cls.litellm_base_url),
            internal_api_key=_env("INTERNAL_API_KEY", cls.internal_api_key),
            checkpointer_type=_env("CHECKPOINTER_TYPE", cls.checkpointer_type),
            checkpointer_db_url=_env("CHECKPOINTER_DB_URL", cls.checkpointer_db_url),
            enable_compaction=_env_bool("ENABLE_COMPACTION"),
            context_token_limit=_env_int("AGENT_CONTEXT_TOKEN_LIMIT", cls.context_token_limit),
            recursion_limit=max(1, min(raw_recursion, 50)),
            max_message_length=_env_int("MAX_MESSAGE_LENGTH", cls.max_message_length),
            enable_tool_cache=_env_bool("ENABLE_TOOL_CACHE"),
            tool_cache_ttl_seconds=_env_int("TOOL_CACHE_TTL", cls.tool_cache_ttl_seconds),
            mcp_startup_timeout=_env_float("MCP_STARTUP_TIMEOUT", cls.mcp_startup_timeout),
        )


@dataclass
class MCPConfig:
    """
    Configuration for FastMCP servers.

    Covers OPA policy enforcement, result size limits, service identity,
    database connection, Redis cache, and tool-result caching.

    Example:
        config = MCPConfig.from_env()
        opa    = OpaClient(config)
        cache  = ToolResultCache.from_config(config)
    """
    # OPA policy engine
    opa_url: str              = "http://localhost:8181/v1/data/mcp/tools/allow"
    opa_timeout_seconds: float = 2.0

    # Result guardrails
    max_result_bytes: int     = 15_000             # truncate oversized query results

    # Service identity — stamped into every OPA evaluation so callers cannot
    # inject a different environment or role via tool arguments (H3 finding).
    environment: str          = "prod"
    agent_role: str           = "data_analyst_agent"
    service_name: str         = "mcp-server"

    # Server runtime
    transport: str            = "sse"
    port: int                 = 8080

    # Tool-result caching
    enable_tool_cache: bool   = True
    tool_cache_ttl_seconds: int = 300

    # Resilience parameters (circuit breaker, retry, backoff)
    cb_failure_threshold: int = 5       # consecutive failures before opening circuit
    cb_recovery_timeout: float = 30.0   # seconds before probing after circuit opens
    opa_max_retries: int = 2            # OPA authorization retry count
    opa_retry_backoff: float = 0.2      # seconds between OPA retries
    mcp_reconnect_backoff_cap: float = 60.0  # max seconds between MCP reconnect attempts
    tool_call_timeout: float = 30.0     # timeout for individual MCP tool calls (seconds)

    # Database connection pool
    db_host: str             = "pgvector"
    db_port: int             = 5432
    db_user: str             = "admin"
    db_pass: str             = ""
    db_name: str             = "ai_memory"
    db_require_ssl: bool     = False
    # Set to 0 for pgBouncer compatibility (disables prepared statement cache)
    statement_cache_size: int = 1024

    # Redis (tool-result cache backend)
    redis_host: str          = ""
    redis_port: int          = 6379
    redis_password: str      = ""

    # MCP server URLs (used by orchestrator agents for service discovery)
    salesforce_mcp_url: str  = "http://salesforce-mcp:8081/sse"
    payments_mcp_url: str    = "http://payments-mcp:8082/sse"
    news_mcp_url: str        = "http://news-search-mcp:8083/sse"
    mcp_sse_url: str         = "http://localhost:8080/sse"

    _VALID_ENVIRONMENTS = {"dev", "local", "staging", "prod", "test"}
    _VALID_AGENT_ROLES = {
        "commercial_banking_agent", "data_analyst_agent", "compliance_agent",
        "rm_prep_agent", "portfolio_watch_agent",
    }

    def __post_init__(self) -> None:
        """Validate configuration at construction time (fail-fast)."""
        errors: list[str] = []
        if not self.opa_url:
            errors.append("opa_url must not be empty")
        elif not self.opa_url.startswith(("http://", "https://")):
            errors.append(f"opa_url must be an HTTP(S) URL, got: {self.opa_url}")
        if self.environment not in self._VALID_ENVIRONMENTS:
            errors.append(
                f"environment='{self.environment}' not in {self._VALID_ENVIRONMENTS}"
            )
        if self.agent_role not in self._VALID_AGENT_ROLES:
            errors.append(
                f"agent_role='{self.agent_role}' not in {self._VALID_AGENT_ROLES}"
            )
        if self.opa_timeout_seconds <= 0:
            errors.append(f"opa_timeout_seconds={self.opa_timeout_seconds} must be positive")
        if self.max_result_bytes < 1000:
            errors.append(f"max_result_bytes={self.max_result_bytes} is too low (min 1000)")
        if self.tool_cache_ttl_seconds < 0:
            errors.append(f"tool_cache_ttl_seconds={self.tool_cache_ttl_seconds} cannot be negative")
        if errors:
            raise ValueError(f"MCPConfig validation failed: {'; '.join(errors)}")

    @classmethod
    def from_env(cls) -> "MCPConfig":
        """Read configuration from environment variables, falling back to defaults."""
        return cls(
            opa_url=_env("OPA_URL", cls.opa_url),
            opa_timeout_seconds=_env_float("OPA_TIMEOUT", cls.opa_timeout_seconds),
            max_result_bytes=_env_int("MAX_RESULT_BYTES", cls.max_result_bytes),
            environment=_env("ENVIRONMENT", cls.environment),
            agent_role=_env("AGENT_ROLE", cls.agent_role),
            service_name=_env("SERVICE_NAME", cls.service_name),
            transport=_env("MCP_TRANSPORT", cls.transport),
            port=_env_int("PORT", cls.port),
            enable_tool_cache=_env_bool("ENABLE_TOOL_CACHE"),
            tool_cache_ttl_seconds=_env_int("TOOL_CACHE_TTL", cls.tool_cache_ttl_seconds),
            cb_failure_threshold=_env_int("CB_FAILURE_THRESHOLD", cls.cb_failure_threshold),
            cb_recovery_timeout=_env_float("CB_RECOVERY_TIMEOUT", cls.cb_recovery_timeout),
            opa_max_retries=_env_int("OPA_MAX_RETRIES", cls.opa_max_retries),
            opa_retry_backoff=_env_float("OPA_RETRY_BACKOFF", cls.opa_retry_backoff),
            mcp_reconnect_backoff_cap=_env_float("MCP_RECONNECT_BACKOFF_CAP", cls.mcp_reconnect_backoff_cap),
            tool_call_timeout=_env_float("TOOL_CALL_TIMEOUT", cls.tool_call_timeout),
            db_host=_env("DB_HOST", cls.db_host),
            db_port=_env_int("DB_PORT", cls.db_port),
            db_user=_env("DB_USER", cls.db_user),
            db_pass=_env("DB_PASS", cls.db_pass),
            db_name=_env("DB_NAME", cls.db_name),
            db_require_ssl=_env_bool("DB_REQUIRE_SSL", False),
            statement_cache_size=_env_int("STATEMENT_CACHE_SIZE", cls.statement_cache_size),
            redis_host=_env("REDIS_HOST", cls.redis_host),
            redis_port=_env_int("REDIS_PORT", cls.redis_port),
            redis_password=_env("REDIS_PASSWORD", cls.redis_password),
            salesforce_mcp_url=_env("SALESFORCE_MCP_URL", cls.salesforce_mcp_url),
            payments_mcp_url=_env("PAYMENTS_MCP_URL", cls.payments_mcp_url),
            news_mcp_url=_env("NEWS_MCP_URL", cls.news_mcp_url),
            mcp_sse_url=_env("MCP_SSE_URL", cls.mcp_sse_url),
        )
