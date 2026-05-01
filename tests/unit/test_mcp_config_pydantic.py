"""MCPConfig is now a Pydantic v2 BaseModel with extra='forbid' and load()."""
from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

pytestmark = pytest.mark.unit


def test_mcp_config_is_pydantic_basemodel():
    from platform_sdk.config import MCPConfig

    assert issubclass(MCPConfig, BaseModel)


def test_mcp_config_forbids_extra_fields():
    from platform_sdk.config import MCPConfig

    with pytest.raises(ValidationError) as exc:
        MCPConfig(environment="dev", typoed_field=123)

    assert "typoed_field" in str(exc.value)


def test_mcp_config_environment_strict_literal():
    from platform_sdk.config import MCPConfig

    MCPConfig(environment="dev")
    MCPConfig(environment="staging")
    MCPConfig(environment="prod")

    with pytest.raises(ValidationError):
        MCPConfig(environment="local")
    with pytest.raises(ValidationError):
        MCPConfig(environment="production")


def test_mcp_config_transport_literal():
    from platform_sdk.config import MCPConfig

    MCPConfig(environment="dev", transport="sse")
    MCPConfig(environment="dev", transport="stdio")

    with pytest.raises(ValidationError):
        MCPConfig(environment="dev", transport="grpc")


def test_mcp_config_port_range():
    from platform_sdk.config import MCPConfig

    MCPConfig(environment="dev", port=8080)

    with pytest.raises(ValidationError):
        MCPConfig(environment="dev", port=0)
    with pytest.raises(ValidationError):
        MCPConfig(environment="dev", port=70000)


def test_mcp_config_load_classmethod_calls_loader(tmp_path, monkeypatch):
    from platform_sdk.config import MCPConfig

    (tmp_path / "default.yaml").write_text(
        "environment: dev\nport: 9000\nopa_url: http://opa:8181/v1/data/mcp\n"
    )
    cfg = MCPConfig.load(config_dir=str(tmp_path), env="dev")

    assert cfg.environment == "dev"
    assert cfg.port == 9000


def test_mcp_config_no_from_env():
    from platform_sdk.config import MCPConfig

    assert not hasattr(MCPConfig, "from_env")


def test_mcp_config_opa_url_must_be_non_empty():
    from platform_sdk.config import MCPConfig
    with pytest.raises(ValidationError) as exc:
        MCPConfig(environment="dev", opa_url="")
    assert "opa_url" in str(exc.value)


def test_mcp_config_opa_url_must_be_http_or_https():
    from platform_sdk.config import MCPConfig
    with pytest.raises(ValidationError) as exc:
        MCPConfig(environment="dev", opa_url="ftp://opa/policy")
    assert "opa_url" in str(exc.value)


def test_mcp_config_agent_role_must_be_in_valid_set():
    from platform_sdk.config import MCPConfig
    # Valid roles pass.
    for role in ("commercial_banking_agent", "data_analyst_agent",
                 "compliance_agent", "analytics_agent"):
        MCPConfig(environment="dev", agent_role=role)
    # Invalid role rejected.
    with pytest.raises(ValidationError) as exc:
        MCPConfig(environment="dev", agent_role="not_a_real_role")
    assert "agent_role" in str(exc.value)
