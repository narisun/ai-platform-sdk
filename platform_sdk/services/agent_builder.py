"""Enterprise AI Platform — AgentBuilder service class."""
from __future__ import annotations

import dataclasses
import inspect
from typing import Optional

from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from ..compaction import make_compaction_modifier
from ..config import AgentConfig
from ..logging import get_logger
from .chat_llm_factory import ChatLLMFactory

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


class AgentBuilder:
    """
    Service class that wraps build_agent and build_specialist_agent functions.

    Builds compiled LangGraph ReAct agents with optional per-agent model overrides.
    """

    def __init__(self, config: AgentConfig, llm_factory: ChatLLMFactory) -> None:
        """
        Initialize AgentBuilder with an AgentConfig and ChatLLMFactory.

        Args:
            config: AgentConfig instance.
            llm_factory: ChatLLMFactory instance for creating LLM clients.
        """
        self._config = config
        self._llm_factory = llm_factory

    def build(
        self,
        tools: list,
        prompt: str = "",
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        """
        Build a compiled LangGraph ReAct agent.

        Args:
            tools:    LangChain StructuredTool objects.
            prompt:   System prompt string.
            base_url: LiteLLM proxy URL. Defaults to config.litellm_base_url.
            api_key:  Bearer token. Defaults to config.internal_api_key.

        Returns:
            Compiled LangGraph CompiledGraph.
        """
        llm = self._llm_factory.create(
            self._config.model_route, base_url=base_url, api_key=api_key
        )

        log.info("build_agent", model=self._config.model_route, tools=[t.name for t in tools])

        compaction_modifier = make_compaction_modifier(self._config)

        def _combined_modifier(state) -> list[BaseMessage]:
            messages: list[BaseMessage] = compaction_modifier(state)
            if prompt:
                if not messages or not isinstance(messages[0], SystemMessage):
                    messages = [SystemMessage(content=prompt)] + list(messages)
            return messages

        if _MODIFIER_KWARG is not None:
            return create_react_agent(llm, tools, **{_MODIFIER_KWARG: _combined_modifier})
        else:
            log.warning(
                "compaction_skipped", reason="LangGraph version too old for modifier API"
            )
            return create_react_agent(llm, tools, prompt=prompt)

    def build_specialist(
        self,
        tools: list,
        prompt: str = "",
        model_override: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        """
        Build a specialist ReAct agent with an optional per-agent model override.

        Used to run cheap models (Haiku / GPT-4o-mini) for data-collection
        specialist nodes while reserving expensive models (Sonnet / GPT-4o)
        for the synthesis node.

        Args:
            tools:          LangChain StructuredTool objects.
            prompt:         System prompt string.
            model_override: LiteLLM route name, e.g. "fast-routing".
                            If None or same as config.model_route, uses default model.
            base_url:       LiteLLM proxy URL. Defaults to config.litellm_base_url.
            api_key:        Bearer token. Defaults to config.internal_api_key.

        Returns:
            Compiled LangGraph CompiledGraph.

        Example:
            crm_agent = builder.build_specialist(
                sf_tools,
                crm_prompt,
                model_override=config.specialist_model_route
            )
        """
        effective_config = self._config
        effective_llm_factory = self._llm_factory

        if model_override and model_override != self._config.model_route:
            effective_config = dataclasses.replace(
                self._config, model_route=model_override
            )
            effective_llm_factory = ChatLLMFactory(effective_config)

        builder = AgentBuilder(effective_config, effective_llm_factory)
        return builder.build(
            tools,
            prompt=prompt,
            base_url=base_url,
            api_key=api_key,
        )
