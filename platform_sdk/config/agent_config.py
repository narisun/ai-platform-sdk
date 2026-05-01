"""LangGraph agent configuration (Pydantic v2)."""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .env_isolation import Environment


class AgentConfig(BaseModel):
    """Configuration for LangGraph agents.

    Covers model routing (including multi-agent tiering), LLM endpoint,
    context compaction, session checkpointing, tool-result caching,
    and the application's database URL. Loaded via `AgentConfig.load()`.
    """

    model_config = ConfigDict(extra="forbid")

    environment: Environment

    # ---- Primary model routing ----
    model_route: str = "complex-routing"
    summary_model_route: str = "fast-routing"

    # ---- Multi-agent model tiering ----
    router_model_route: str = "fast-routing"
    specialist_model_route: str = "fast-routing"
    synthesis_model_route: str = "complex-routing"

    # ---- LLM endpoint (LiteLLM proxy) ----
    litellm_base_url: str = "http://localhost:4000/v1"
    internal_api_key: str = ""

    # ---- Session / checkpointer ----
    checkpointer_type: str = "memory"  # "memory" | "postgres"
    checkpointer_db_url: str = ""

    # ---- Conversation store (replaces the ad-hoc os.getenv("DATABASE_URL")) ----
    database_url: str = ""

    # ---- Context compaction ----
    enable_compaction: bool = True
    context_token_limit: Annotated[int, Field(ge=100)] = 6_000

    # ---- Safety limits ----
    recursion_limit: int = 10  # silently clamped via validator below
    max_message_length: Annotated[int, Field(ge=100)] = 32_000

    # ---- Tool-result caching ----
    enable_tool_cache: bool = True
    tool_cache_ttl_seconds: Annotated[int, Field(ge=0)] = 300

    # ---- MCP bridge startup ----
    mcp_startup_timeout: float = 120.0

    # ---- Synthesis settings ----
    chart_max_data_points: int = 20

    # ---- Registration / self-URL — for Application._register hook ----
    registry_url: str = ""
    service_url: str = ""
    service_version: str = ""

    @field_validator("recursion_limit")
    @classmethod
    def _clamp_recursion_limit(cls, v: int) -> int:
        # Preserve historical clamp: max(1, min(v, 50)).
        return max(1, min(v, 50))

    @field_validator("model_route")
    @classmethod
    def _validate_model_route(cls, v: str) -> str:
        if not v:
            raise ValueError("model_route must not be empty")
        return v

    @classmethod
    def load(cls, *, config_dir: str | None = None, env: str | None = None) -> "AgentConfig":
        from .loader import load_config
        return load_config(cls, config_dir=config_dir, env=env)
