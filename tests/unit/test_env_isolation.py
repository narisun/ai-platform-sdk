"""Tests for env_isolation primitives."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_environment_literal_accepts_valid_values():
    from typing import get_args

    from platform_sdk.config.env_isolation import Environment

    assert set(get_args(Environment)) == {"dev", "staging", "prod"}


def test_env_header_constant_value():
    from platform_sdk.config.env_isolation import ENV_HEADER

    assert ENV_HEADER == "X-Environment"
