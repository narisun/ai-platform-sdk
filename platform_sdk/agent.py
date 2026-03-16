"""
Platform SDK — LangGraph ReAct agent factory.

Provides one reusable building block:

build_agent(tools, config, prompt, base_url, api_key)
    Constructs a compiled LangGraph CompiledGraph backed by the LiteLLM
    proxy, with compaction wired in automatically when
    config.enable_compaction is True.

This replaces the hand-rolled build_enterprise_agent() in agents/src/graph.py
so every new agent service starts from the same proven baseline — correct
compaction, correct LiteLLM routing, deterministic temperature.

Example:
    from platform_sdk import AgentConfig
    from platform_sdk.agent import build_agent

    config = AgentConfig.from_env()
    agent  = build_agent(tools, config=config, prompt=system_prompt)

    result = await agent.ainvoke(
        {"messages": [HumanMessage(content=user_msg)]},
        config={"recursion_limit": config.recursion_limit},
    )

Design decisions:
- LITELLM_BASE_URL and INTERNAL_API_KEY are read from environment at
  call time (not import time) so tests can override them easily.
- Temperature is fixed at 0 for deterministic enterprise behaviour.
- max_retries=2 lets LiteLLM handle provider failover transparently.
- compaction modifier is combined with the system prompt via a single
  state_modifier callable — LangGraph only accepts one state_modifier,
  so we must compose them here rather than stacking decorators.
"""
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

# Detect which modifier parameter name this version of LangGraph supports.
# - state_modifier  → introduced in LangGraph ~0.2.x (newer)
# - messages_modifier → the original name (older, still works in newer as alias)
# Using runtime introspection means the code works without knowing which
# exact version is installed, and survives future renames automatically.
_REACT_AGENT_PARAMS = inspect.signature(create_react_agent).parameters
if "state_modifier" in _REACT_AGENT_PARAMS:
    _MODIFIER_KWARG = "state_modifier"
elif "messages_modifier" in _REACT_AGENT_PARAMS:
    _MODIFIER_KWARG = "messages_modifier"
else:
    _MODIFIER_KWARG = None  # very old version — fall back to prompt= only

log.debug("langgraph_compat", modifier_kwarg=_MODIFIER_KWARG)


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
        tools:    List of LangChain StructuredTool objects.
        config:   AgentConfig instance.  Defaults to AgentConfig.from_env().
        prompt:   System prompt string injected before user messages.
        base_url: LiteLLM proxy URL.  Defaults to LITELLM_BASE_URL env var
                  or "http://localhost:4000/v1".
        api_key:  Bearer token for LiteLLM.  Defaults to INTERNAL_API_KEY
                  env var.

    Returns:
        A compiled LangGraph CompiledGraph ready for ainvoke / astream.

    Raises:
        ValueError: If no API key is available.
    """
    if config is None:
        config = AgentConfig.from_env()

    resolved_base_url = base_url or os.environ.get(
        "LITELLM_BASE_URL", "http://localhost:4000/v1"
    )
    resolved_api_key = api_key or os.environ.get("INTERNAL_API_KEY", "")
    if not resolved_api_key:
        raise ValueError("INTERNAL_API_KEY must be set — see .env.example")

    llm = ChatOpenAI(
        model=config.model_route,
        api_key=resolved_api_key,
        base_url=resolved_base_url,
        temperature=0,       # Deterministic for enterprise use
        max_retries=2,       # LiteLLM handles provider failover
    )

    log.info(
        "build_agent",
        model=config.model_route,
        compaction=config.enable_compaction,
        token_limit=config.context_token_limit,
        tools=[t.name for t in tools],
    )

    # Compose system-prompt injection and context compaction into a single
    # modifier callable.  LangGraph only accepts one modifier argument, so
    # we must combine both concerns here rather than stacking two decorators.
    compaction_modifier = make_compaction_modifier(config)

    def _combined_modifier(state) -> List[BaseMessage]:
        # 1. Apply compaction (trims oldest messages when over token budget)
        messages: List[BaseMessage] = compaction_modifier(state)

        # 2. Prepend system message if a prompt was provided and one isn't
        #    already the first message (avoids duplicate system messages on
        #    multi-turn conversations where it was already prepended).
        if prompt:
            if not messages or not isinstance(messages[0], SystemMessage):
                messages = [SystemMessage(content=prompt)] + list(messages)

        return messages

    if _MODIFIER_KWARG is not None:
        # Preferred path: wire compaction + system prompt via the modifier API
        agent_executor = create_react_agent(llm, tools, **{_MODIFIER_KWARG: _combined_modifier})
    else:
        # Fallback for very old LangGraph builds that predate the modifier API:
        # pass the system prompt directly and skip compaction gracefully.
        log.warning(
            "compaction_skipped",
            reason="Installed LangGraph version does not support a modifier parameter — "
                   "upgrade to langgraph>=0.1.5 to enable compaction",
        )
        agent_executor = create_react_agent(llm, tools, prompt=prompt)

    return agent_executor
