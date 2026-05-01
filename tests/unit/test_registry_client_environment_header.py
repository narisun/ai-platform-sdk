"""RegistryClient stamps X-Environment from the supplied config."""
from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.unit


def _stub_config(env="dev", api_key="k", registry_url=""):
    class _C:
        environment = env
        internal_api_key = api_key
    _C.registry_url = registry_url
    return _C()


@pytest.mark.asyncio
async def test_registry_client_sends_x_environment(monkeypatch):
    """A RegistryClient instantiated from config sends X-Environment on every request."""
    from platform_sdk.registry.client import RegistryClient

    captured: list[httpx.Request] = []

    async def _mock_send(self, req, *a, **kw):
        captured.append(req)
        return httpx.Response(200, json={"ok": True, "services": []})

    monkeypatch.setattr(httpx.AsyncClient, "send", _mock_send)

    client = RegistryClient.from_config(_stub_config(env="staging"), registry_url="http://reg:8090")
    try:
        # Any method that issues a GET will do; lookup is the simplest.
        try:
            await client.lookup("data-mcp")
        except Exception:
            pass
        # Walk captured requests; at least one must carry the header.
        assert captured, "expected at least one request"
        assert captured[0].headers.get("X-Environment") == "staging"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_from_config_uses_registry_url_attribute(monkeypatch):
    """If registry_url= isn't passed but config.registry_url is set, use it."""
    from platform_sdk.registry.client import RegistryClient

    captured: list[httpx.Request] = []

    async def _mock_send(self, req, *a, **kw):
        captured.append(req)
        return httpx.Response(200, json={"ok": True, "services": []})

    monkeypatch.setattr(httpx.AsyncClient, "send", _mock_send)

    cfg = _stub_config(env="dev", registry_url="http://from-config:8090")
    client = RegistryClient.from_config(cfg)
    try:
        try:
            await client.lookup("data-mcp")
        except Exception:
            pass
        assert captured
        assert "from-config:8090" in str(captured[0].url)
    finally:
        await client.aclose()


def test_from_config_raises_when_no_registry_url():
    """If neither argument nor config provides a registry_url, fail loudly."""
    from platform_sdk.registry.client import RegistryClient

    cfg = _stub_config(env="dev", registry_url="")
    with pytest.raises(ValueError):
        RegistryClient.from_config(cfg)
