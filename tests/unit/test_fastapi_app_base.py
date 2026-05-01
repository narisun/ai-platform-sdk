"""Unit tests for platform_sdk.fastapi_app.BaseAgentApp."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_subclass_must_implement_build_dependencies():
    from platform_sdk.config import AgentConfig
    from platform_sdk.fastapi_app import BaseAgentApp

    class Incomplete(BaseAgentApp):
        service_name = "incomplete"

    app = Incomplete(config=AgentConfig(environment="dev"))
    with pytest.raises(NotImplementedError):
        app.build_dependencies(bridges={}, checkpointer=None, store=None)


def test_create_app_returns_fastapi_instance_with_correct_title():
    """create_app() must be pure — no env reads, no I/O."""
    from fastapi import FastAPI
    from platform_sdk.config import AgentConfig
    from platform_sdk.fastapi_app import BaseAgentApp

    class Minimal(BaseAgentApp):
        service_name = "minimal"
        mcp_servers: dict = {}
        requires_checkpointer = False
        requires_conversation_store = False

        def build_dependencies(self, *, bridges, checkpointer, store):
            return {"sentinel": "ok"}

        def routes(self):
            return []

    app_obj = Minimal(config=AgentConfig(environment="dev"))
    fastapi_app = app_obj.create_app()
    assert isinstance(fastapi_app, FastAPI)
    assert fastapi_app.title == "minimal"


@pytest.mark.asyncio
async def test_lifespan_calls_build_dependencies_and_attaches_to_state():
    from platform_sdk.config import AgentConfig
    from platform_sdk.fastapi_app import BaseAgentApp

    class Probe(BaseAgentApp):
        service_name = "probe"
        mcp_servers: dict = {}
        enable_telemetry = False
        requires_checkpointer = False
        requires_conversation_store = False

        def build_dependencies(self, *, bridges, checkpointer, store):
            return {"probe_deps": True}

        def routes(self):
            return []

    app_obj = Probe(config=AgentConfig(environment="dev"))
    fastapi_app = app_obj.create_app()
    async with fastapi_app.router.lifespan_context(fastapi_app):
        assert fastapi_app.state.deps == {"probe_deps": True}


@pytest.mark.asyncio
async def test_lifespan_skips_telemetry_when_disabled(monkeypatch):
    """enable_telemetry=False must not call setup_telemetry()."""
    from platform_sdk.config import AgentConfig
    from platform_sdk.fastapi_app import BaseAgentApp

    calls: list = []
    monkeypatch.setattr(
        "platform_sdk.telemetry.setup_telemetry",
        lambda name: calls.append(name),
    )

    class NoTelemetry(BaseAgentApp):
        service_name = "no-telemetry"
        mcp_servers: dict = {}
        enable_telemetry = False
        requires_checkpointer = False
        requires_conversation_store = False

        def build_dependencies(self, *, bridges, checkpointer, store):
            return {}

        def routes(self):
            return []

    fastapi_app = NoTelemetry(config=AgentConfig(environment="dev")).create_app()
    async with fastapi_app.router.lifespan_context(fastapi_app):
        pass
    assert calls == []


@pytest.mark.asyncio
async def test_on_started_hook_runs_after_build_dependencies():
    """on_started() must run with deps attached and after build_dependencies()."""
    from platform_sdk.config import AgentConfig
    from platform_sdk.fastapi_app import BaseAgentApp

    order: list = []

    class WithHook(BaseAgentApp):
        service_name = "with-hook"
        mcp_servers: dict = {}
        enable_telemetry = False
        requires_checkpointer = False
        requires_conversation_store = False

        def build_dependencies(self, *, bridges, checkpointer, store):
            order.append("build")
            return {"x": 1}

        def routes(self):
            return []

        async def on_started(self, deps, *, bridges, config, checkpointer, store):
            order.append("started")
            assert deps == {"x": 1}

    fastapi_app = WithHook(config=AgentConfig(environment="dev")).create_app()
    async with fastapi_app.router.lifespan_context(fastapi_app):
        pass
    assert order == ["build", "started"]


@pytest.mark.asyncio
async def test_lifespan_raises_when_store_required_but_missing():
    from platform_sdk.config import AgentConfig
    from platform_sdk.fastapi_app import BaseAgentApp

    class BadStore(BaseAgentApp):
        service_name = "bad-store"
        mcp_servers: dict = {}
        enable_telemetry = False
        requires_conversation_store = True

        def build_dependencies(self, *, bridges, checkpointer, store):
            return {}

        def routes(self):
            return []
        # build_conversation_store NOT overridden → returns None

    fastapi_app = BadStore(config=AgentConfig(environment="dev")).create_app()
    with pytest.raises(NotImplementedError, match="requires_conversation_store=True"):
        async with fastapi_app.router.lifespan_context(fastapi_app):
            pass


def test_service_title_and_description_overrides_apply():
    from platform_sdk.config import AgentConfig
    from platform_sdk.fastapi_app import BaseAgentApp

    class Titled(BaseAgentApp):
        service_name = "x-y-z"
        service_title = "Pretty Name"
        service_description = "Pretty description here."

        def build_dependencies(self, *, bridges, checkpointer, store):
            return {}

        def routes(self):
            return []

    fastapi_app = Titled(config=AgentConfig(environment="dev")).create_app()
    assert fastapi_app.title == "Pretty Name"
    assert fastapi_app.description == "Pretty description here."


def test_service_title_falls_back_to_service_name():
    from platform_sdk.config import AgentConfig
    from platform_sdk.fastapi_app import BaseAgentApp

    class NoTitle(BaseAgentApp):
        service_name = "no-title"

        def build_dependencies(self, *, bridges, checkpointer, store):
            return {}

        def routes(self):
            return []

    fastapi_app = NoTitle(config=AgentConfig(environment="dev")).create_app()
    assert fastapi_app.title == "no-title"


@pytest.mark.asyncio
async def test_lifespan_ready_log_uses_underscore_form(monkeypatch):
    """Service names with hyphens should still log <name>_ready (underscore form)."""
    from platform_sdk.fastapi_app import BaseAgentApp
    import platform_sdk.fastapi_app.base as base_mod

    info_calls: list = []

    class _RecorderLogger:
        def info(self, event, **kw):
            info_calls.append(event)

        def warning(self, event, **kw):
            pass

        def error(self, event, **kw):
            pass

        def debug(self, event, **kw):
            pass

    monkeypatch.setattr(base_mod, "get_logger", lambda name: _RecorderLogger())

    class HyphenName(BaseAgentApp):
        service_name = "my-service-name"
        mcp_servers: dict = {}
        enable_telemetry = False
        requires_checkpointer = False
        requires_conversation_store = False

        def build_dependencies(self, *, bridges, checkpointer, store):
            return {}

        def routes(self):
            return []

    from platform_sdk.config import AgentConfig
    fastapi_app = HyphenName(config=AgentConfig(environment="dev")).create_app()
    async with fastapi_app.router.lifespan_context(fastapi_app):
        pass
    assert "my_service_name_ready" in info_calls
    assert "my-service-name_ready" not in info_calls
