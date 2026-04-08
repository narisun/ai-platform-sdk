"""
LangGraph agent configuration.

Covers model routing (including multi-agent tiering), LLM endpoint,
context compaction, session checkpointing, and tool-result caching.
"""
from __future__ import annotations

from dataclasses import dataclass

from .helpers import _env, _env_bool, _env_float, _env_int


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

    # ---- Synthesis settings ----
    # Maximum number of data points per chart component.  Large arrays (40+
    # items) often cause malformed structured output from the LLM.  The value
    # is forwarded to the synthesis node via make_synthesis_node() and also
    # rendered into the synthesis system prompt so the LLM knows the limit.
    chart_max_data_points: int = 20

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
    def from_env(cls) -> AgentConfig:
        """Read configuration from environment variables, falling back to defaults."""
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
            chart_max_data_points=_env_int("CHART_MAX_DATA_POINTS", cls.chart_max_data_points),
        )
