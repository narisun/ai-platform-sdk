"""
Platform SDK — LangGraph ReAct agent factory.

Provides four building blocks:

  build_agent(tools, config, prompt)
      Standard ReAct agent. Used by the main enterprise agent service and
      any single-purpose agent.

  build_specialist_agent(tools, config, prompt, model_override)
      Same as build_agent but accepts a per-specialist model override.
      Used by orchestrators that run cheap models for data-collection nodes
      and an expensive model only for synthesis.

  make_checkpointer(config)
      Synchronous factory — returns the correct LangGraph checkpointer but
      does NOT call setup().  Use only when checkpoint tables are guaranteed
      to already exist (e.g. tests with a pre-migrated database).

  setup_checkpointer(config)  [async]
      Async factory — creates AND initialises the checkpointer.  This is
      the correct function to call from a FastAPI lifespan or any async
      startup context.  It calls checkpointer.setup() for Postgres savers,
      which creates the checkpoint tables if they do not already exist.

Design decisions:
- Temperature is fixed at 0 for deterministic enterprise behaviour.
- Compaction + system prompt are composed into a single state_modifier
  because LangGraph only accepts one modifier argument.
- System prompt is prepended BEFORE compaction runs so the system message
  is always present when trim_messages evaluates include_system=True.
- LangGraph version compatibility is detected at import time via
  inspect.signature so the code works without knowing which exact
  version is installed.
"""
import dataclasses
import inspect
from typing import Optional

from langchain_core.messages import BaseMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from .compaction import make_compaction_modifier
from .config import AgentConfig
from .logging import get_logger

log = get_logger(__name__)

# Detect which modifier kwarg this LangGraph version supports
_REACT_AGENT_PARAMS = inspect.signature(create_react_agent).parameters
if "state_modifier" in _REACT_AGENT_PARAMS:
    _MODIFIER_KWARG = "state_modifier"
elif "messages_modifier" in _REACT_AGENT_PARAMS:
    _MODIFIER_KWARG = "messages_modifier"
else:
    _MODIFIER_KWARG = None

log.debug("langgraph_compat", modifier_kwarg=_MODIFIER_KWARG)


def make_checkpointer(config: Optional[AgentConfig] = None):
    """
    Create a LangGraph checkpointer based on configuration (synchronous).

    Centralises the memory-vs-postgres branching that was duplicated in
    every graph builder.

    Args:
        config: AgentConfig with checkpointer_type and checkpointer_db_url.
                Defaults to AgentConfig.from_env().

    Returns:
        A LangGraph-compatible checkpointer (MemorySaver or AsyncPostgresSaver).

    WARNING: For Postgres checkpointers this does NOT call checkpointer.setup(),
    so the checkpoint tables may not exist yet.  Prefer ``setup_checkpointer``
    from an async context (e.g. FastAPI lifespan) which calls setup() for you.
    Use make_checkpointer() only when tables are guaranteed to already exist.
    """
    if config is None:
        config = AgentConfig.from_env()

    if config.checkpointer_type == "postgres" and config.checkpointer_db_url:
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            checkpointer = AsyncPostgresSaver.from_conn_string(config.checkpointer_db_url)
            log.info("checkpointer_ready", type="postgres")
            return checkpointer
        except ImportError:
            log.warning(
                "postgres_checkpointer_unavailable",
                fallback="memory",
                reason="langgraph-checkpoint-postgres not installed",
            )

    from langgraph.checkpoint.memory import MemorySaver
    checkpointer = MemorySaver()
    log.info("checkpointer_ready", type="memory")
    return checkpointer


async def setup_checkpointer(config: Optional[AgentConfig] = None):
    """
    Async factory — creates AND initialises the checkpointer.

    This is the correct entry point from async contexts (FastAPI lifespan,
    pytest fixtures with event loops, etc.).  It calls ``checkpointer.setup()``
    for Postgres savers, which creates the checkpoint tables if they do not
    already exist.  Without this call the first multi-turn request will fail
    with a "relation does not exist" error.

    Args:
        config: AgentConfig with checkpointer_type and checkpointer_db_url.
                Defaults to AgentConfig.from_env().

    Returns:
        An initialised LangGraph-compatible checkpointer.

    Example (FastAPI lifespan)::

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            app.state.checkpointer = await setup_checkpointer()
            graph = build_analytics_graph(bridges, config,
                                          checkpointer=app.state.checkpointer)
            yield
    """
    checkpointer = make_checkpointer(config)
    if hasattr(checkpointer, "setup"):
        await checkpointer.setup()
        log.info("checkpointer_setup_complete", type=type(checkpointer).__name__)
    return checkpointer


def make_chat_llm(
    model_route: str,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    config: Optional[AgentConfig] = None,
) -> "ChatOpenAI":
    """
    Construct a LangChain ChatOpenAI client pointed at the LiteLLM proxy.

    Use this for LLM nodes that need LangChain-native features (structured
    output, streaming) but do not need the full ReAct agent scaffolding.

    Args:
        model_route: LiteLLM route name (e.g. "complex-routing").
        base_url:    LiteLLM proxy URL. Falls back to config.litellm_base_url.
        api_key:     Bearer token. Falls back to config.internal_api_key.
        config:      AgentConfig. Defaults to AgentConfig.from_env().

    Returns:
        Configured ChatOpenAI instance at temperature=0.
    """
    if config is None:
        config = AgentConfig.from_env()
    resolved_base_url = base_url or config.litellm_base_url
    resolved_api_key = api_key or config.internal_api_key
    if not resolved_api_key:
        raise ValueError("INTERNAL_API_KEY must be set — see .env.example")

    return ChatOpenAI(
        model=model_route,
        api_key=resolved_api_key,
        base_url=resolved_base_url,
        temperature=0,
        max_retries=2,
    )


def build_agent(
    tools: list,
    config: Optional[AgentConfig] = None,
    prompt: str = "",
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
):
    """
    Build a compiled LangGraph ReAct agent.

    Args:
        tools:    LangChain StructuredTool objects.
        config:   AgentConfig. Defaults to AgentConfig.from_env().
        prompt:   System prompt string.
        base_url: LiteLLM proxy URL. Defaults to LITELLM_BASE_URL env var.
        api_key:  Bearer token. Defaults to INTERNAL_API_KEY env var.

    Returns:
        Compiled LangGraph CompiledGraph.
    """
    if config is None:
        config = AgentConfig.from_env()

    llm = make_chat_llm(config.model_route, base_url=base_url, api_key=api_key)

    log.info("build_agent", model=config.model_route, tools=[t.name for t in tools])

    compaction_modifier = make_compaction_modifier(config)

    def _combined_modifier(state) -> list[BaseMessage]:
        # 1. Extract raw message list from state (list or dict depending on LangGraph version)
        messages: list[BaseMessage] = (
            state if isinstance(state, list) else state.get("messages", [])
        )
        # 2. Prepend system prompt BEFORE compaction so trim_messages can protect it
        #    via include_system=True.  If system prompt is added after compaction, a
        #    long conversation could exceed the token limit on the very next step.
        if prompt:
            if not messages or not isinstance(messages[0], SystemMessage):
                messages = [SystemMessage(content=prompt)] + list(messages)
        # 3. Run compaction — system message is now present and will be preserved
        return compaction_modifier(messages)

    if _MODIFIER_KWARG is not None:
        return create_react_agent(llm, tools, **{_MODIFIER_KWARG: _combined_modifier})
    else:
        log.warning("compaction_skipped", reason="LangGraph version too old for modifier API")
        return create_react_agent(llm, tools, prompt=prompt)


def build_specialist_agent(
    tools: list,
    config: Optional[AgentConfig] = None,
    prompt: str = "",
    model_override: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
):
    """
    Build a specialist ReAct agent with an optional per-agent model override.

    Used by orchestrators to run cheap models (Haiku / GPT-4o-mini) for
    data-collection specialist nodes while reserving expensive models
    (Sonnet / GPT-4o) for the synthesis node.

    Args:
        model_override: LiteLLM route name, e.g. "fast-routing".
                        If None, falls back to config.model_route.
        (all other args same as build_agent)

    Example:
        crm_agent  = build_specialist_agent(sf_tools, config, crm_prompt,
                         model_override=config.specialist_model_route)
        synth_llm  = ChatOpenAI(model=config.synthesis_model_route, ...)
    """
    if config is None:
        config = AgentConfig.from_env()

    effective_config = config
    if model_override and model_override != config.model_route:
        effective_config = dataclasses.replace(config, model_route=model_override)

    return build_agent(
        tools,
        config=effective_config,
        prompt=prompt,
        base_url=base_url,
        api_key=api_key,
    )
