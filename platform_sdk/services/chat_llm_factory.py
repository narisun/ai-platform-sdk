"""Enterprise AI Platform — ChatLLMFactory service class."""
from __future__ import annotations

from typing import Optional

from langchain_openai import ChatOpenAI

from ..config import AgentConfig


class ChatLLMFactory:
    """
    Service class that wraps the make_chat_llm factory function.

    Constructs a LangChain ChatOpenAI client pointed at the LiteLLM proxy.
    Use this for LLM nodes that need LangChain-native features (structured
    output, streaming) but do not need the full ReAct agent scaffolding.
    """

    def __init__(self, config: AgentConfig) -> None:
        """
        Initialize ChatLLMFactory with an AgentConfig.

        Args:
            config: AgentConfig instance with litellm_base_url and internal_api_key.
        """
        self._config = config

    def create(
        self,
        model_route: str,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> ChatOpenAI:
        """
        Create a configured ChatOpenAI instance.

        Args:
            model_route: LiteLLM route name (e.g. "complex-routing").
            base_url:    LiteLLM proxy URL. Falls back to config.litellm_base_url.
            api_key:     Bearer token. Falls back to config.internal_api_key.

        Returns:
            Configured ChatOpenAI instance at temperature=0.

        Raises:
            ValueError: If no API key can be resolved.
        """
        resolved_base_url = base_url or self._config.litellm_base_url
        resolved_api_key = api_key or self._config.internal_api_key
        if not resolved_api_key:
            raise ValueError("INTERNAL_API_KEY must be set — see .env.example")

        return ChatOpenAI(
            model=model_route,
            api_key=resolved_api_key,
            base_url=resolved_base_url,
            temperature=0,
            max_retries=2,
        )
