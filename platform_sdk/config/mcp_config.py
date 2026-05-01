"""FastMCP server configuration (Pydantic v2)."""
from __future__ import annotations

from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .env_isolation import Environment


class MCPConfig(BaseModel):
    """Configuration for FastMCP servers.

    Covers OPA policy enforcement, result size limits, service identity,
    database connection, Redis cache, and tool-result caching. Loaded
    from `config/default.yaml` + optional `config/<env>.yaml` via the
    SDK's `load_config()` (or `MCPConfig.load()`).
    """

    model_config = ConfigDict(extra="forbid")

    # OPA policy engine
    opa_url: str = "http://localhost:8181/v1/data/mcp/tools/allow"
    opa_timeout_seconds: Annotated[float, Field(gt=0)] = 2.0

    # Result guardrails
    max_result_bytes: Annotated[int, Field(ge=1000)] = 15_000

    # Service identity — stamped into every OPA evaluation.
    environment: Environment
    agent_role: str = "data_analyst_agent"
    service_name: str = "mcp-server"

    # Server runtime
    transport: Literal["stdio", "sse"] = "sse"
    port: Annotated[int, Field(gt=0, le=65535)] = 8080

    # Tool-result caching
    enable_tool_cache: bool = True
    tool_cache_ttl_seconds: Annotated[int, Field(ge=0)] = 300

    # Resilience parameters (circuit breaker, retry, backoff)
    cb_failure_threshold: int = 5
    cb_recovery_timeout: float = 30.0
    opa_max_retries: int = 2
    opa_retry_backoff: float = 0.2
    mcp_reconnect_backoff_cap: float = 60.0
    tool_call_timeout: float = 30.0

    # Database connection pool
    db_host: str = "pgvector"
    db_port: int = 5432
    db_user: str = "admin"
    db_pass: str = ""
    db_name: str = "ai_memory"
    db_require_ssl: bool = False
    statement_cache_size: int = 1024

    # Redis (tool-result cache backend)
    redis_host: str = ""
    redis_port: int = 6379
    redis_password: str = ""

    # MCP server URLs (used by orchestrator agents for service discovery)
    salesforce_mcp_url: str = "http://salesforce-mcp:8081/sse"
    payments_mcp_url: str = "http://payments-mcp:8082/sse"
    news_mcp_url: str = "http://news-search-mcp:8083/sse"
    mcp_sse_url: str = "http://localhost:8080/sse"

    # Registration / self-URL — used by Application._register hook.
    registry_url: str = ""
    service_url: str = ""
    service_version: str = ""

    # Internal Bearer token used for MCP↔registry and MCP↔MCP authentication.
    # Read by make_internal_http_client() and RegistryClient.from_config().
    internal_api_key: str = ""

    _VALID_AGENT_ROLES: ClassVar[set[str]] = {
        "commercial_banking_agent",
        "data_analyst_agent",
        "compliance_agent",
        "analytics_agent",
    }

    @field_validator("opa_url")
    @classmethod
    def _validate_opa_url(cls, v: str) -> str:
        if not v:
            raise ValueError("opa_url must not be empty")
        if not v.startswith(("http://", "https://")):
            raise ValueError(f"opa_url must be an HTTP(S) URL, got: {v}")
        return v

    @field_validator("agent_role")
    @classmethod
    def _validate_agent_role(cls, v: str) -> str:
        if v not in cls._VALID_AGENT_ROLES:
            raise ValueError(f"agent_role='{v}' not in {sorted(cls._VALID_AGENT_ROLES)}")
        return v

    @classmethod
    def load(cls, *, config_dir: str | None = None, env: str | None = None) -> "MCPConfig":
        """Load from `<config_dir>/default.yaml` + optional `<config_dir>/<env>.yaml`."""
        from .loader import load_config
        return load_config(cls, config_dir=config_dir, env=env)
