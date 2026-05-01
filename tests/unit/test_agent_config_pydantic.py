"""AgentConfig is now Pydantic v2 BaseModel with load()."""
from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

pytestmark = pytest.mark.unit


def test_agent_config_is_basemodel():
    from platform_sdk.config import AgentConfig

    assert issubclass(AgentConfig, BaseModel)


def test_agent_config_forbids_extra_fields():
    from platform_sdk.config import AgentConfig

    with pytest.raises(ValidationError):
        AgentConfig(environment="dev", typoed=1)


def test_agent_config_recursion_limit_clamped():
    """Existing behaviour: recursion_limit is silently clamped to [1, 50]."""
    from platform_sdk.config import AgentConfig

    cfg_low = AgentConfig(environment="dev", recursion_limit=0)
    assert cfg_low.recursion_limit == 1

    cfg_high = AgentConfig(environment="dev", recursion_limit=999)
    assert cfg_high.recursion_limit == 50


def test_agent_config_database_url_field_present():
    """Hoisted from analytics-agent's os.getenv leak."""
    from platform_sdk.config import AgentConfig

    cfg = AgentConfig(environment="dev", database_url="postgres://x")
    assert cfg.database_url == "postgres://x"


def test_agent_config_load_classmethod(tmp_path):
    from platform_sdk.config import AgentConfig

    (tmp_path / "default.yaml").write_text(
        "environment: dev\nmodel_route: complex-routing\n"
    )
    cfg = AgentConfig.load(config_dir=str(tmp_path), env="dev")

    assert cfg.environment == "dev"
    assert cfg.model_route == "complex-routing"


def test_agent_config_no_from_env():
    from platform_sdk.config import AgentConfig

    assert not hasattr(AgentConfig, "from_env")


def test_agent_config_environment_strict_literal():
    from platform_sdk.config import AgentConfig

    AgentConfig(environment="dev")
    AgentConfig(environment="staging")
    AgentConfig(environment="prod")

    with pytest.raises(ValidationError):
        AgentConfig(environment="local")


def test_agent_config_model_route_must_be_non_empty():
    from platform_sdk.config import AgentConfig

    with pytest.raises(ValidationError):
        AgentConfig(environment="dev", model_route="")


def test_agent_config_max_message_length_minimum():
    from platform_sdk.config import AgentConfig

    AgentConfig(environment="dev", max_message_length=100)
    with pytest.raises(ValidationError):
        AgentConfig(environment="dev", max_message_length=99)
