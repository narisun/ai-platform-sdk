"""make_internal_http_client stamps X-Environment and Bearer auth."""
from __future__ import annotations

import asyncio

import httpx
import pytest

pytestmark = pytest.mark.unit


def _stub_config(env="dev", api_key="k"):
    """A bag-of-fields stub that quacks like an SDK config object."""
    class _C:
        environment = env
        internal_api_key = api_key
    return _C()


def _close(client):
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(client.aclose())
    finally:
        loop.close()


def test_factory_returns_async_client():
    from platform_sdk.http import make_internal_http_client

    client = make_internal_http_client(_stub_config())
    try:
        assert isinstance(client, httpx.AsyncClient)
    finally:
        _close(client)


def test_factory_sets_x_environment_header():
    from platform_sdk.http import make_internal_http_client

    client = make_internal_http_client(_stub_config(env="staging"))
    try:
        assert client.headers.get("X-Environment") == "staging"
    finally:
        _close(client)


def test_factory_sets_bearer_auth_header():
    from platform_sdk.http import make_internal_http_client

    client = make_internal_http_client(_stub_config(api_key="my-secret-key"))
    try:
        assert client.headers.get("Authorization") == "Bearer my-secret-key"
    finally:
        _close(client)


def test_factory_omits_authorization_when_no_api_key():
    """A service without internal_api_key should not include Bearer."""
    from platform_sdk.http import make_internal_http_client

    client = make_internal_http_client(_stub_config(api_key=""))
    try:
        assert "Authorization" not in client.headers
    finally:
        _close(client)
