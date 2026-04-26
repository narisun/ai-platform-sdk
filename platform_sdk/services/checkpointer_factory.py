"""Enterprise AI Platform — CheckpointerFactory service class."""
from __future__ import annotations

from typing import Any

from ..config import AgentConfig
from ..logging import get_logger

log = get_logger(__name__)


class CheckpointerFactory:
    """
    Service class that wraps the make_checkpointer factory function.

    Creates a LangGraph checkpointer based on configuration.
    Centralises the memory-vs-postgres branching that was duplicated in
    every graph builder.
    """

    def __init__(self, config: AgentConfig) -> None:
        """
        Initialize CheckpointerFactory with an AgentConfig.

        Args:
            config: AgentConfig instance with checkpointer_type and checkpointer_db_url.
        """
        self._config = config

    def create(self) -> Any:
        """
        Create a LangGraph checkpointer based on configuration.

        Returns a MemorySaver or AsyncPostgresSaver depending on configuration.

        Returns:
            A LangGraph-compatible checkpointer (MemorySaver or AsyncPostgresSaver).
        """
        if self._config.checkpointer_type == "postgres" and self._config.checkpointer_db_url:
            try:
                from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

                checkpointer = AsyncPostgresSaver.from_conn_string(
                    self._config.checkpointer_db_url
                )
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
