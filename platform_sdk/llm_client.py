"""
EnterpriseLLMClient — thin wrapper around the LiteLLM proxy.

Provides a single, consistent interface for all LLM calls so services
never import openai directly or hardcode endpoint/key configuration.

Telemetry is set up separately via setup_telemetry(); this client
assumes it has already been called.

Example:
    from platform_sdk import EnterpriseLLMClient, AgentConfig, setup_telemetry, configure_logging

    configure_logging()
    setup_telemetry("ai-agents")
    config = AgentConfig.from_env()
    client = EnterpriseLLMClient(config=config)
    response = await client.generate("complex-routing", messages)
"""
from typing import Optional
from openai import AsyncOpenAI
from .config import AgentConfig
from .logging import get_logger

log = get_logger(__name__)


class EnterpriseLLMClient:
    """
    Async LLM client that routes all calls through the LiteLLM proxy.

    Configuration is read from ``AgentConfig`` which centralises all
    environment-variable access.
    """

    def __init__(self, config: Optional[AgentConfig] = None) -> None:
        if config is None:
            config = AgentConfig.from_env()

        base_url = config.litellm_base_url
        api_key = config.internal_api_key

        if not api_key:
            raise ValueError(
                "INTERNAL_API_KEY environment variable is required. "
                "See .env.example for setup instructions."
            )

        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        log.info("llm_client_ready", base_url=base_url)

    async def generate(
        self,
        model_route: str,
        messages: list[dict],
        **kwargs,
    ):
        """
        Call a model route defined in the LiteLLM config.

        Args:
            model_route: The model_name from litellm config (e.g. "complex-routing").
            messages:    OpenAI-format message list.
            **kwargs:    Forwarded to chat.completions.create (temperature, max_tokens, etc.)

        Returns:
            OpenAI ChatCompletion response object.
        """
        log.debug("llm_request", model_route=model_route, message_count=len(messages))
        response = await self._client.chat.completions.create(
            model=model_route,
            messages=messages,
            **kwargs,
        )
        log.debug(
            "llm_response",
            model_route=model_route,
            prompt_tokens=response.usage.prompt_tokens if response.usage else None,
            completion_tokens=response.usage.completion_tokens if response.usage else None,
        )
        return response
