"""
Platform SDK — LangGraph ReAct agent factory.

Provides two building blocks:

  build_agent(tools, config, prompt)
      Standard ReAct agent. Used by the main enterprise agent service and
      any single-purpose agent.

  build_specialist_agent(tools, config, prompt, model_override)
      Same as build_agent but accepts a per-specialist model override.
      Used by orchestrators that run cheap models for data-collection nodes
      and an expensive model only for synthesis.

Design decisions:
- Temperature is fixed at 0 for deterministic enterprise behaviour.
- Compaction + system prompt are composed into a single state_modifier
  because LangGraph only accepts one modifier argument.
- LangGraph version compatibility is detected at import time via
  inspect.signature so the code works without knowing which exact
  version is installed.
"""
import dataclasses
import inspect
import os
from typing import List, Optional

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


def make_chat_llm(
    model_route: str,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> "ChatOpenAI":
    """
    Construct a LangChain ChatOpenAI client pointed at the LiteLLM proxy.

    Use this for LLM nodes that need LangChain-native features (structured
    output, streaming) but do not need the full ReAct agent scaffolding.

    Args:
        model_route: LiteLLM route name (e.g. "complex-routing").
        base_url:    LiteLLM proxy URL. Defaults to LITELLM_BASE_URL env var.
        api_key:     Bearer token. Defaults to INTERNAL_API_KEY env var.

    Returns:
        Configured ChatOpenAI instance at temperature=0.
    """
    resolved_base_url = base_url or os.environ.get("LITELLM_BASE_URL", "http://localhost:4000/v1")
    resolved_api_key = api_key or os.environ.get("INTERNAL_API_KEY", "")
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

    resolved_base_url = base_url or os.environ.get("LITELLM_BASE_URL", "http://localhost:4000/v1")
    resolved_api_key = api_key or os.environ.get("INTERNAL_API_KEY", "")
    if not resolved_api_key:
        raise ValueError("INTERNAL_API_KEY must be set — see .env.example")

    llm = ChatOpenAI(
        model=config.model_route,
        api_key=resolved_api_key,
        base_url=resolved_base_url,
        temperature=0,
        max_retries=2,
    )

    log.info("build_agent", model=config.model_route, tools=[t.name for t in tools])

    compaction_modifier = make_compaction_modifier(config)

    def _combined_modifier(state) -> List[BaseMessage]:
        messages: List[BaseMessage] = compaction_modifier(state)
        if prompt:
            if not messages or not isinstance(messages[0], SystemMessage):
                messages = [SystemMessage(content=prompt)] + list(messages)
        return messages

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
