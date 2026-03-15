"""
Structured logging configuration for the Enterprise AI Platform.

Every log entry is emitted as JSON with a consistent schema so
Dynatrace / CloudWatch / any log aggregator can index and alert on it.

Example usage:
    from platform_sdk import configure_logging, get_logger

    configure_logging()          # Call once at startup
    log = get_logger(__name__)
    log.info("agent_started", model="gpt-4o-mini", tool_count=3)
    log.error("opa_timeout", tool="execute_read_query", latency_ms=2100)
"""
import logging
import os

import structlog


def configure_logging(level: str | None = None) -> None:
    """
    Configure structlog for JSON output in production, pretty output locally.

    Call once at application startup before any log messages are emitted.
    """
    log_level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()

    # Shared processors applied to every log record
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    # Use JSON in non-interactive environments (containers, CI)
    is_interactive = os.getenv("TERM") or os.getenv("CI") is None
    if is_interactive and os.getenv("LOG_FORMAT") != "json":
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(log_level)

    # Quiet noisy third-party loggers
    for noisy in ("httpx", "asyncpg", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a named structlog logger. Use module __name__ as the name."""
    return structlog.get_logger(name)
