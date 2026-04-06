"""
Platform SDK — LangFuse Prompt Management.

Provides centralized prompt management via LangFuse. Prompts are versioned,
A/B testable, and editable in the LangFuse UI without code deploys.

Prompts are cached in-memory with a configurable TTL to reduce load on LangFuse.
If LangFuse is unavailable or a prompt fetch fails, a fallback string is returned.

Usage:
    from platform_sdk.prompt_manager import PromptManager

    pm = PromptManager()

    # Fetch a text prompt with fallback
    prompt = pm.get_prompt(
        "crm_specialist",
        fallback="You are a CRM specialist. Help the user with their customer data."
    )

    # Fetch a chat prompt (list of messages)
    messages = pm.get_chat_prompt(
        "customer_support",
        fallback=[
            {"role": "system", "content": "You are a helpful support agent."},
            {"role": "user", "content": "..."}
        ]
    )

    # Use specific version and label for A/B testing
    prompt = pm.get_prompt("classifier", version=3, label="production")
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from langfuse import Langfuse

logger = logging.getLogger(__name__)


class PromptManager:
    """
    Manage prompts from LangFuse with in-memory caching.

    Provides graceful degradation: if LangFuse is unavailable, returns fallback values.
    Caches prompts in-memory to reduce latency and load on LangFuse.
    """

    def __init__(
        self,
        langfuse: Optional[Langfuse] = None,
        ttl_seconds: int = 300,
    ):
        """
        Initialize the PromptManager.

        Args:
            langfuse: LangFuse client instance. If None, calls get_langfuse() from telemetry.
            ttl_seconds: Cache TTL in seconds (default 300s = 5 minutes).
        """
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, tuple[Any, float]] = {}

        if langfuse is None:
            # Lazy import to avoid circular dependency
            from .telemetry import get_langfuse
            langfuse = get_langfuse()

        self.langfuse = langfuse

    def _is_cached_valid(self, key: str) -> bool:
        """Check if a cached prompt is still valid (not expired)."""
        if key not in self._cache:
            return False
        _, timestamp = self._cache[key]
        return time.time() - timestamp < self.ttl_seconds

    def get_prompt(
        self,
        name: str,
        *,
        version: Optional[int] = None,
        label: Optional[str] = None,
        fallback: Optional[str] = None,
    ) -> str:
        """
        Fetch a text prompt from LangFuse.

        Falls back to the provided fallback string if LangFuse is unavailable
        or the prompt cannot be fetched. Caches results in-memory.

        Args:
            name: Prompt name in LangFuse.
            version: Optional specific version to fetch.
            label: Optional production label (e.g., "production", "staging").
            fallback: Fallback string if LangFuse fetch fails (default: empty string).

        Returns:
            The prompt text, or the fallback value if LangFuse is unavailable.
        """
        cache_key = f"text:{name}:{version}:{label}"

        # Check in-memory cache
        if self._is_cached_valid(cache_key):
            return self._cache[cache_key][0]

        # Try to fetch from LangFuse
        if self.langfuse is None:
            logger.debug(f"LangFuse not configured, using fallback for prompt '{name}'")
            result = fallback or ""
        else:
            try:
                prompt = self.langfuse.get_prompt(
                    name=name,
                    version=version,
                    label=label,
                )
                # The prompt object's .compile() returns the rendered text
                result = prompt.compile() if hasattr(prompt, "compile") else str(prompt)
                logger.debug(f"Fetched prompt '{name}' from LangFuse")
            except Exception as e:
                logger.warning(
                    f"Failed to fetch prompt '{name}' from LangFuse: {e}. "
                    f"Using fallback."
                )
                result = fallback or ""

        # Cache the result
        self._cache[cache_key] = (result, time.time())
        return result

    def get_chat_prompt(
        self,
        name: str,
        *,
        version: Optional[int] = None,
        label: Optional[str] = None,
        fallback: Optional[list[dict[str, str]]] = None,
    ) -> list[dict[str, str]]:
        """
        Fetch a chat prompt (list of messages) from LangFuse.

        Falls back to the provided fallback list if LangFuse is unavailable.
        Caches results in-memory.

        Args:
            name: Prompt name in LangFuse.
            version: Optional specific version to fetch.
            label: Optional production label (e.g., "production", "staging").
            fallback: Fallback list of message dicts if fetch fails (default: empty list).

        Returns:
            List of message dicts [{"role": "system", "content": "..."}, ...],
            or the fallback value if LangFuse is unavailable.
        """
        cache_key = f"chat:{name}:{version}:{label}"

        # Check in-memory cache
        if self._is_cached_valid(cache_key):
            return self._cache[cache_key][0]

        # Try to fetch from LangFuse
        if self.langfuse is None:
            logger.debug(f"LangFuse not configured, using fallback for chat prompt '{name}'")
            result = fallback or []
        else:
            try:
                prompt = self.langfuse.get_prompt(
                    name=name,
                    version=version,
                    label=label,
                    type="chat",
                )
                # For chat prompts, .compile() returns list of message dicts
                result = prompt.compile() if hasattr(prompt, "compile") else (fallback or [])
                logger.debug(f"Fetched chat prompt '{name}' from LangFuse")
            except Exception as e:
                logger.warning(
                    f"Failed to fetch chat prompt '{name}' from LangFuse: {e}. "
                    f"Using fallback."
                )
                result = fallback or []

        # Cache the result
        self._cache[cache_key] = (result, time.time())
        return result

    def invalidate_cache(self, name: Optional[str] = None) -> None:
        """
        Invalidate cached prompts.

        Args:
            name: If provided, only invalidate prompts with this name.
                  If None, clear the entire cache.
        """
        if name is None:
            self._cache.clear()
            logger.debug("Cleared entire prompt cache")
        else:
            keys_to_remove = [k for k in self._cache.keys() if k.startswith(f"text:{name}:") or k.startswith(f"chat:{name}:")]
            for key in keys_to_remove:
                del self._cache[key]
            logger.debug(f"Invalidated cache for prompt '{name}'")
