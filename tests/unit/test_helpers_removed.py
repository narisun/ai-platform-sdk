"""platform_sdk.config.helpers and its functions are gone."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_helpers_module_removed():
    with pytest.raises(ImportError):
        import platform_sdk.config.helpers  # noqa: F401


def test_env_helpers_not_exported():
    from platform_sdk import config as cfg_module

    for name in ("_env", "_env_int", "_env_float", "_env_bool"):
        assert not hasattr(cfg_module, name), f"{name} should not be exported"


def test_config_init_exports_load_machinery():
    from platform_sdk.config import ConfigError, Environment, load_config

    assert ConfigError is not None
    assert load_config is not None
    assert Environment is not None
