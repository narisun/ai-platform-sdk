"""Application auto-loads from config_model when no config is passed."""
from __future__ import annotations

from typing import ClassVar

import pytest
from pydantic import BaseModel, ConfigDict

from platform_sdk.config.env_isolation import Environment

pytestmark = pytest.mark.unit


class _StubConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    environment: Environment
    name: str = "stub"
    registry_url: str = ""
    service_url: str = ""
    service_version: str = ""
    internal_api_key: str = ""

    @classmethod
    def load(cls, *, config_dir=None, env=None):
        # Test version: synthesize a value rather than read YAML.
        return cls(environment=env or "dev")


def test_application_uses_config_model_when_no_config(monkeypatch):
    from platform_sdk.base.application import Application

    class _App(Application):
        config_model: ClassVar[type[BaseModel]] = _StubConfig

    monkeypatch.setenv("ENVIRONMENT", "dev")
    a = _App(name="x")
    assert a.config.environment == "dev"
    assert a.environment == "dev"


def test_application_uses_explicit_config_when_passed():
    from platform_sdk.base.application import Application

    class _App(Application):
        config_model: ClassVar[type[BaseModel]] = _StubConfig

    explicit = _StubConfig(environment="prod")
    a = _App(name="x", config=explicit)
    assert a.config is explicit
    assert a.environment == "prod"


def test_application_without_config_model_raises():
    from platform_sdk.base.application import Application

    class _Bad(Application):
        pass  # no config_model

    with pytest.raises(NotImplementedError):
        _Bad(name="x")
