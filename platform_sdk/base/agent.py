"""Enterprise AI Platform — Agent base class."""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from .application import Application

if TYPE_CHECKING:
    from ..config import AgentConfig


class Agent(Application):
    """Base class for Enterprise AI agents."""

    def __init__(self, name: str, *, config: Optional[AgentConfig] = None) -> None:
        """
        Initialize the agent.

        Args:
            name: The agent name.
            config: Optional AgentConfig to inject. If not provided, will load from environment.
        """
        self._config = config
        super().__init__(name)

    @property
    def agent_config(self) -> AgentConfig:
        """Get the agent configuration typed as AgentConfig."""
        return self.config

    def load_config(self, name: str) -> AgentConfig:
        """
        Load configuration for this agent.

        If config was injected via constructor, returns that.
        Otherwise loads from environment.

        Args:
            name: The agent name.

        Returns:
            The loaded AgentConfig.
        """
        if self._config is not None:
            return self._config

        from ..config import AgentConfig

        return AgentConfig.from_env()
