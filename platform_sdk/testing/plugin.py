"""Pytest plugin — shared fixtures for SDK consumers.

Auto-registered via [project.entry-points.pytest11] in pyproject.toml.
Any pytest run in a process where enterprise-ai-platform-sdk is installed
gets these fixtures.
"""
from __future__ import annotations

import os
import time
from typing import Callable

import pytest

from . import TEST_PERSONAS


@pytest.fixture(scope="session")
def jwt_secret() -> str:
    return os.environ.get("JWT_SECRET", "test-secret-change-in-prod")


@pytest.fixture(scope="session")
def hmac_secret() -> str:
    return os.environ.get("CONTEXT_HMAC_SECRET", "test-context-secret-change-in-prod")


@pytest.fixture(scope="session")
def internal_api_key() -> str:
    return os.environ.get("INTERNAL_API_KEY", "test-key")


def _make_jwt(payload: dict, secret: str) -> str:
    import jwt as pyjwt
    now = int(time.time())
    return pyjwt.encode(
        {"iat": now, "exp": now + 3600, **payload},
        secret,
        algorithm="HS256",
    )


def _persona_to_jwt_payload(persona: dict) -> dict:
    return {
        "sub": persona["rm_id"],
        "name": persona["rm_name"],
        "role": persona["role"],
        "team_id": persona["team_id"],
        "assigned_account_ids": persona["assigned_account_ids"],
        "compliance_clearance": persona["compliance_clearance"],
    }


@pytest.fixture(scope="session")
def make_persona_jwt(jwt_secret: str) -> Callable[[dict], str]:
    def _make(persona: dict) -> str:
        return _make_jwt(persona, jwt_secret)
    return _make


@pytest.fixture(scope="session")
def persona_manager() -> dict:
    return _persona_to_jwt_payload(TEST_PERSONAS["manager"])


@pytest.fixture(scope="session")
def persona_senior_rm() -> dict:
    return _persona_to_jwt_payload(TEST_PERSONAS["senior_rm"])


@pytest.fixture(scope="session")
def persona_rm() -> dict:
    return _persona_to_jwt_payload(TEST_PERSONAS["rm"])


@pytest.fixture(scope="session")
def persona_readonly() -> dict:
    return _persona_to_jwt_payload(TEST_PERSONAS["readonly"])
