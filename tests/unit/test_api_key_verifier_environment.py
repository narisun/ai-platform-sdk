"""make_api_key_verifier(environment=...) rejects mismatched X-Environment."""
from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


def _build_app(verify):
    app = FastAPI()

    @app.get("/protected")
    async def protected(_: str = Depends(verify)):
        return {"ok": True}

    return TestClient(app)


def test_request_with_matching_environment_succeeds(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "secret")
    from platform_sdk.security import make_api_key_verifier

    verify = make_api_key_verifier(environment="dev")
    client = _build_app(verify)

    r = client.get(
        "/protected",
        headers={"Authorization": "Bearer secret", "X-Environment": "dev"},
    )
    assert r.status_code == 200


def test_request_with_mismatched_environment_returns_403(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "secret")
    from platform_sdk.security import make_api_key_verifier

    verify = make_api_key_verifier(environment="prod")
    client = _build_app(verify)

    r = client.get(
        "/protected",
        headers={"Authorization": "Bearer secret", "X-Environment": "dev"},
    )
    assert r.status_code == 403
    body = r.json()
    assert body["detail"]["error"] == "environment_mismatch"
    assert body["detail"]["expected"] == "prod"
    assert body["detail"]["got"] == "dev"


def test_request_without_x_environment_returns_403(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "secret")
    from platform_sdk.security import make_api_key_verifier

    verify = make_api_key_verifier(environment="prod")
    client = _build_app(verify)

    r = client.get("/protected", headers={"Authorization": "Bearer secret"})
    assert r.status_code == 403


def test_environment_none_disables_isolation(monkeypatch):
    """Passing environment=None preserves legacy auth-only behaviour."""
    monkeypatch.setenv("INTERNAL_API_KEY", "secret")
    from platform_sdk.security import make_api_key_verifier

    verify = make_api_key_verifier()  # no environment arg
    client = _build_app(verify)

    r = client.get("/protected", headers={"Authorization": "Bearer secret"})
    assert r.status_code == 200
