"""
Platform SDK — LangGraph context compaction.

Provides one reusable building block:

make_compaction_modifier(config)
    Returns a LangGraph state_modifier callable that trims the message list
    when the estimated token count exceeds config.context_token_limit.

    The modifier is injected into create_react_agent via the state_modifier
    parameter so compaction happens transparently on every agent step.

    When config.enable_compaction is False a lightweight pass-through is
    returned so callers never need an if/else branch.

Example:
    from platform_sdk import AgentConfig
    from platform_sdk.compaction import make_compaction_modifier

    config   = AgentConfig.from_env()
    modifier = make_compaction_modifier(config)

    agent = create_react_agent(llm, tools, state_modifier=modifier)

Design decisions:
- Uses langchain_core.messages.trim_messages with strategy="last" so the most
  recent context is always preserved.
- include_system=True retains the system message even after trimming.
- token_counter uses tiktoken (cl100k_base) by default for fast, accurate
  counts.  Falls back to a character / 4 heuristic when tiktoken is not
  installed so the module is importable in environments without it.
- When compaction fires, an INFO log is emitted with before/after token counts
  so operators can tune context_token_limit.
"""
from typing import Callable, List, Optional, Sequence

from langchain_core.messages import BaseMessage, SystemMessage

from .config import AgentConfig
from .logging import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Token counter
# ---------------------------------------------------------------------------

def _make_token_counter() -> Callable[[Sequence[BaseMessage]], int]:
    """
    Return a token-counting callable compatible with trim_messages.

    Tries tiktoken first (accurate); falls back to len(text)/4 heuristic.
    """
    try:
        import tiktoken  # type: ignore[import]

        enc = tiktoken.get_encoding("cl100k_base")

        def _tiktoken_count(messages: Sequence[BaseMessage]) -> int:
            total = 0
            for m in messages:
                content = m.content if isinstance(m.content, str) else str(m.content)
                total += len(enc.encode(content))
            return total

        log.debug("compaction_token_counter", backend="tiktoken")
        return _tiktoken_count

    except ImportError:
        log.warning(
            "compaction_token_counter",
            backend="heuristic",
            reason="tiktoken not installed — install it for accurate counts",
        )

        def _heuristic_count(messages: Sequence[BaseMessage]) -> int:
            total = 0
            for m in messages:
                content = m.content if isinstance(m.content, str) else str(m.content)
                total += max(1, len(content) // 4)
            return total

        return _heuristic_count


# Lazily initialised on first use so:
# (a) import-time warnings don't fire in environments without tiktoken,
# (b) tests that monkeypatch the env or install tiktoken after import get
#     the correct backend without restarting the process.
_token_counter: Optional[Callable[[Sequence[BaseMessage]], int]] = None


def _get_token_counter() -> Callable[[Sequence[BaseMessage]], int]:
    """Return the module-level token counter, initialising it on first call."""
    global _token_counter
    if _token_counter is None:
        _token_counter = _make_token_counter()
    return _token_counter


# ---------------------------------------------------------------------------
# TokenAwareCompactionModifier — class API satisfying CompactionModifier Protocol
# ---------------------------------------------------------------------------

class TokenAwareCompactionModifier:
    """Trim message history to fit a token budget while preserving the system prompt.

    Wraps the same logic as the legacy ``make_compaction_modifier()`` factory
    but in a constructor-injected class. Satisfies the
    ``CompactionModifier`` Protocol used by the analytics-agent port layer.

    Behavior preserved from the legacy implementation:
      - Lazy tiktoken initialisation via the module's ``_get_token_counter()``.
      - Falls through to a character/4 heuristic when tiktoken is unavailable.
      - Uses ``trim_messages(strategy="last", include_system=True,
        allow_partial=False)`` for the primary trim.
      - Min-message guard: if a single oversized message would otherwise leave
        fewer than 2 messages, keeps system message(s) plus the last
        non-system message so the LLM always has the current request.

    Args:
        token_limit: Maximum tokens to keep across the message list.
        encoding: tiktoken encoding name (default: ``"cl100k_base"``). The
            module's shared token counter currently always uses
            ``cl100k_base``; this parameter is reserved for future use.
    """

    def __init__(
        self,
        token_limit: int,
        encoding: str = "cl100k_base",
    ) -> None:
        self._token_limit = token_limit
        self._encoding_name = encoding

    def apply(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        """Return a possibly-trimmed message list that fits inside the budget."""
        if not messages:
            return messages

        counter = _get_token_counter()
        before_tokens = counter(messages)

        if before_tokens <= self._token_limit:
            return messages

        # Lazy import — keeps module import cheap.
        from langchain_core.messages import trim_messages  # type: ignore[import]

        trimmed = trim_messages(
            messages,
            max_tokens=self._token_limit,
            strategy="last",
            token_counter=counter,
            include_system=True,
            allow_partial=False,
        )

        # Min-message guard: if a single oversized message caused trim_messages
        # to return fewer than 2 messages, preserve at least
        # [system + last user] so the LLM always has the current request.
        if len(trimmed) < 2 and len(messages) >= 2:
            system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
            non_system  = [m for m in messages if not isinstance(m, SystemMessage)]
            oversized_tokens = counter([non_system[-1]]) if non_system else 0
            log.warning(
                "compaction_min_guard_applied",
                reason="A single message exceeds the token limit; "
                       "keeping system message + last user message only.",
                oversized_message_tokens=oversized_tokens,
                limit=self._token_limit,
                hint="Increase context_token_limit or truncate large tool responses "
                     "before they enter the message history.",
            )
            trimmed = system_msgs + ([non_system[-1]] if non_system else [])

        after_tokens = counter(trimmed)
        log.info(
            "compaction_applied",
            before_messages=len(messages),
            after_messages=len(trimmed),
            before_tokens=before_tokens,
            after_tokens=after_tokens,
            limit=self._token_limit,
        )

        return trimmed  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Compaction modifier factory
# ---------------------------------------------------------------------------

def make_compaction_modifier(config: AgentConfig) -> Callable:
    """
    Return a LangGraph state_modifier that trims messages to fit the token budget.

    The returned callable receives the full agent state and returns a (possibly
    shorter) list of messages to pass to the LLM.

    When config.enable_compaction is False a no-op pass-through is returned.

    Args:
        config: AgentConfig instance (use AgentConfig.from_env() in services).

    Returns:
        A callable suitable for create_react_agent's state_modifier parameter.
    """
    if not config.enable_compaction:
        log.info("compaction_disabled")

        def _passthrough(state) -> List[BaseMessage]:
            messages = state if isinstance(state, list) else state.get("messages", [])
            return messages  # type: ignore[return-value]

        return _passthrough

    limit = config.context_token_limit
    log.info("compaction_enabled", token_limit=limit)

    def _modifier(state) -> List[BaseMessage]:
        # state is either a list of messages or a dict with "messages" key,
        # depending on the LangGraph version and graph shape.
        messages: List[BaseMessage] = (
            state if isinstance(state, list) else state.get("messages", [])
        )

        counter = _get_token_counter()
        before_tokens = counter(messages)

        if before_tokens <= limit:
            return messages

        # Lazy import — services that don't use compaction don't pay the
        # import cost; also avoids a hard dependency on langchain_core for
        # users who only import config/security.
        from langchain_core.messages import trim_messages  # type: ignore[import]

        trimmed = trim_messages(
            messages,
            max_tokens=limit,
            strategy="last",          # keep most recent messages
            token_counter=counter,
            include_system=True,      # never evict the system message
            allow_partial=False,      # never split a message mid-content
        )

        # Min-message guard: if a single oversized message caused trim_messages
        # to return fewer than 2 messages, preserve at least [system + last user]
        # so the LLM always has the current request in context.
        if len(trimmed) < 2 and len(messages) >= 2:
            system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
            non_system  = [m for m in messages if not isinstance(m, SystemMessage)]
            oversized_tokens = counter([non_system[-1]]) if non_system else 0
            log.warning(
                "compaction_min_guard_applied",
                reason="A single message exceeds the token limit; "
                       "keeping system message + last user message only.",
                oversized_message_tokens=oversized_tokens,
                limit=limit,
                hint="Increase context_token_limit or truncate large tool responses "
                     "before they enter the message history.",
            )
            trimmed = system_msgs + ([non_system[-1]] if non_system else [])

        after_tokens = counter(trimmed)
        log.info(
            "compaction_applied",
            before_messages=len(messages),
            after_messages=len(trimmed),
            before_tokens=before_tokens,
            after_tokens=after_tokens,
            limit=limit,
        )

        return trimmed  # type: ignore[return-value]

    return _modifier
