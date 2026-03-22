"""
Platform SDK — Typed configuration dataclasses.

Every tunable parameter for agents and MCP servers is defined here with
sensible defaults and read from environment variables via from_env().
"""
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class AgentConfig:
    """
    Configuration for LangGraph agents.

    Covers model routing (including multi-agent tiering), context
    compaction, session checkpointing, and tool-result caching.
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
        raw_recursion = int(os.environ.get("AGENT_RECURSION_LIMIT", str(cls.recursion_limit)))
        return cls(
            model_route=os.environ.get("AGENT_MODEL_ROUTE", cls.model_route),
            summary_model_route=os.environ.get("SUMMARY_MODEL_ROUTE", cls.summary_model_route),
            router_model_route=os.environ.get("ROUTER_MODEL_ROUTE", cls.router_model_route),
            specialist_model_route=os.environ.get("SPECIALIST_MODEL_ROUTE", cls.specialist_model_route),
            synthesis_model_route=os.environ.get("SYNTHESIS_MODEL_ROUTE", cls.synthesis_model_route),
            checkpointer_type=os.environ.get("CHECKPOINTER_TYPE", cls.checkpointer_type),
            checkpointer_db_url=os.environ.get("CHECKPOINTER_DB_URL", cls.checkpointer_db_url),
            enable_compaction=os.environ.get("ENABLE_COMPACTION", "true").lower() == "true",
            context_token_limit=int(
                os.environ.get("AGENT_CONTEXT_TOKEN_LIMIT", str(cls.context_token_limit))
            ),
            recursion_limit=max(1, min(raw_recursion, 50)),
            max_message_length=int(
                os.environ.get("MAX_MESSAGE_LENGTH", str(cls.max_message_length))
            ),
            enable_tool_cache=os.environ.get("ENABLE_TOOL_CACHE", "true").lower() == "true",
            tool_cache_ttl_seconds=int(
                os.environ.get("TOOL_CACHE_TTL", str(cls.tool_cache_ttl_seconds))
            ),
        )


@dataclass
class MCPConfig:
    """
    Configuration for FastMCP servers.

    Covers OPA policy enforcement, result size limits, service identity,
    and tool-result caching.

    Example:
        config = MCPConfig.from_env()
        opa    = OpaClient(config)
        cache  = ToolResultCache.from_env(ttl_seconds=config.tool_cache_ttl_seconds)
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
    # Set to 0 for pgBouncer compatibility (disables prepared statement cache)
    statement_cache_size: int = 1024

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
            opa_url=os.environ.get("OPA_URL", cls.opa_url),
            opa_timeout_seconds=float(
                os.environ.get("OPA_TIMEOUT", str(cls.opa_timeout_seconds))
            ),
            max_result_bytes=int(
                os.environ.get("MAX_RESULT_BYTES", str(cls.max_result_bytes))
            ),
            environment=os.environ.get("ENVIRONMENT", cls.environment),
            agent_role=os.environ.get("AGENT_ROLE", cls.agent_role),
            enable_tool_cache=os.environ.get("ENABLE_TOOL_CACHE", "true").lower() == "true",
            tool_cache_ttl_seconds=int(
                os.environ.get("TOOL_CACHE_TTL", str(cls.tool_cache_ttl_seconds))
            ),
            cb_failure_threshold=int(
                os.environ.get("CB_FAILURE_THRESHOLD", str(cls.cb_failure_threshold))
            ),
            cb_recovery_timeout=float(
                os.environ.get("CB_RECOVERY_TIMEOUT", str(cls.cb_recovery_timeout))
            ),
            opa_max_retries=int(
                os.environ.get("OPA_MAX_RETRIES", str(cls.opa_max_retries))
            ),
            opa_retry_backoff=float(
                os.environ.get("OPA_RETRY_BACKOFF", str(cls.opa_retry_backoff))
            ),
            mcp_reconnect_backoff_cap=float(
                os.environ.get("MCP_RECONNECT_BACKOFF_CAP", str(cls.mcp_reconnect_backoff_cap))
            ),
            tool_call_timeout=float(
                os.environ.get("TOOL_CALL_TIMEOUT", str(cls.tool_call_timeout))
            ),
            statement_cache_size=int(
                os.environ.get("STATEMENT_CACHE_SIZE", str(cls.statement_cache_size))
            ),
        )
