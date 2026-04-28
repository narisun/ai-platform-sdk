"""Enterprise AI Platform — Application base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import structlog

from ..logging import get_logger


class Application(ABC):
    """Root base class for all Enterprise AI applications (agents and MCP services)."""

    def __init__(self, name: str) -> None:
        """
        Initialize the application.

        Args:
            name: The application name.
        """
        self.name = name
        self.config = self.load_config(name)

    @property
    def logger(self) -> structlog.BoundLogger:
        """Get a structlog logger for this application."""
        return get_logger(self.name)

    @abstractmethod
    def load_config(self, name: str) -> Any:
        """
        Load configuration for this application.

        Subclasses must override to return their specific config type.

        Args:
            name: The application name.

        Returns:
            The loaded configuration object.
        """
        ...

    async def startup(self) -> None:
        """
        Async startup hook. Override in subclasses if needed.
        """
        pass

    async def shutdown(self) -> None:
        """
        Async shutdown hook. Override in subclasses if needed.
        """
        pass
