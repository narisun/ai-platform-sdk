"""
EnterpriseLLMClient — thin wrapper around the LiteLLM proxy.

Provides a single, consistent interface for all LLM calls so services
never import openai directly or hardcode endpoint/key configuration.

Telemetry is set up separately via setup_telemetry(); this client
assumes it has already been called.

Example:
    from platform_sdk import EnterpriseLLMClient, setup_telemetry, configure_logging

    configure_logging()
    setup_telemetry("ai-agents")
    client = EnterpriseLLMClient()
    response = await client.generate("complex-routing", messages)
"""
import os
from openai import AsyncOpenAI
from .logging import get_logger

log = get_logger(__name__)


class EnterpriseLLMClient:
    """
    Async LLM client that routes all calls through the LiteLLM proxy.

    Configuration is read entirely from environment variables — no
    hardcoded defaults beyond localhost for local development.
    """

    def __init__(self) -> None:
        base_url = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000/v1")
        api_key = os.environ.get("INTERNAL_API_KEY")

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
