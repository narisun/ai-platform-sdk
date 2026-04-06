"""
OpenTelemetry + LangFuse observability stack for the Enterprise AI Platform.

OTel handles infrastructure traces (spans for service calls, cache operations, etc.),
while LangFuse provides LLM observability (prompt versions, LLM calls, token counts).

Call setup_telemetry(service_name) once at application startup — not at
module import time — so environment variables are guaranteed to be loaded.

Example:
    from platform_sdk import setup_telemetry, get_langfuse, get_langfuse_callback_handler
    setup_telemetry("ai-agents")

    # Use LangFuse client directly
    langfuse = get_langfuse()
    if langfuse:
        langfuse.trace(name="agent_run", ...)

    # Or use callback handler for LangChain/LangGraph integration
    # IMPORTANT: Each call returns a NEW handler (one handler = one trace).
    handler = get_langfuse_callback_handler()
    # Pass to runnable.invoke(..., config={"callbacks": [handler]})
"""
import os
import logging
from typing import Optional

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

logger = logging.getLogger(__name__)

_otel_initialized = False
_langfuse_client: Optional[object] = None

# Store LangFuse connection config so we can create fresh handlers per request
_langfuse_config: Optional[dict] = None

# Resolved import for CallbackHandler (set once during setup_telemetry)
_CallbackHandler: Optional[type] = None


def _resolve_langfuse_imports():
    """
    Resolve the correct LangFuse import paths.

    Langfuse v3 moved the CallbackHandler to langfuse.langchain and
    renamed the 'host' parameter to 'base_url'. This function detects
    the installed version and returns the correct classes.

    Returns:
        Tuple of (Langfuse class, CallbackHandler class, host_param_name)
    """
    # First, check if langfuse is installed at all
    try:
        import langfuse as _lf
        logger.info("langfuse package found", extra={"version": getattr(_lf, "__version__", "unknown")})
    except Exception as e:
        logger.warning("langfuse package cannot be imported: %s: %s", type(e).__name__, e)
        return None, None, None

    # Try v3 import path first (langfuse >= 2.7 / 3.x)
    try:
        from langfuse import Langfuse
        from langfuse.langchain import CallbackHandler
        logger.info("Using langfuse v3 import path (langfuse.langchain.CallbackHandler)")
        return Langfuse, CallbackHandler, "base_url"
    except Exception as e:
        logger.debug("langfuse v3 import path failed: %s: %s", type(e).__name__, e)

    # Fall back to v2 import path
    try:
        from langfuse import Langfuse
        from langfuse.callback import CallbackHandler
        logger.info("Using langfuse v2 import path (langfuse.callback.CallbackHandler)")
        return Langfuse, CallbackHandler, "host"
    except Exception as e:
        logger.warning("langfuse v2 import path also failed: %s: %s", type(e).__name__, e)

    # langfuse is installed but neither CallbackHandler path works
    logger.warning(
        "langfuse is installed (v%s) but no compatible CallbackHandler found. "
        "Try: pip install 'langfuse>=2.0.0' 'langchain-core>=0.2.0'",
        getattr(_lf, "__version__", "unknown"),
    )
    return None, None, None


def setup_telemetry(service_name: str | None = None) -> None:
    """
    Initialise OpenTelemetry and LangFuse observability stack.

    Idempotent — safe to call multiple times; only initialises once.

    OTel: If OTEL_EXPORTER_OTLP_ENDPOINT is not set, infrastructure tracing
          is silently skipped (useful in unit tests).

    LangFuse: If LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY are not set,
              LangFuse is silently disabled. Otherwise initialized with env vars:
              - LANGFUSE_PUBLIC_KEY (required)
              - LANGFUSE_SECRET_KEY (required)
              - LANGFUSE_HOST (defaults to http://langfuse:3000)
    """
    global _otel_initialized, _langfuse_client, _langfuse_config, _CallbackHandler
    if _otel_initialized:
        return

    # Setup OTel tracing
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        name = service_name or os.getenv("SERVICE_NAME", "enterprise-ai-service")
        resource = Resource(attributes={"service.name": name})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}"))
        )
        trace.set_tracer_provider(provider)

        # Instrument the OpenAI client (used via LiteLLM)
        try:
            from opentelemetry.instrumentation.openai import OpenAIInstrumentor
            OpenAIInstrumentor().instrument()
        except ImportError:
            logger.debug("opentelemetry-instrumentation-openai not installed — skipping")

        logger.info("OpenTelemetry initialised", extra={"service": name, "endpoint": endpoint})
    else:
        logger.info("OTEL_EXPORTER_OTLP_ENDPOINT not set — OTel tracing disabled")

    # Setup LangFuse for LLM observability
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")

    if public_key and secret_key:
        LangfuseClass, CallbackHandlerClass, host_param = _resolve_langfuse_imports()

        if LangfuseClass is None:
            logger.warning("langfuse package not installed — LangFuse disabled")
            _langfuse_client = None
            _langfuse_config = None
            _CallbackHandler = None
        else:
            try:
                host = os.getenv("LANGFUSE_HOST", "http://langfuse:3000")

                # Store config for creating per-request callback handlers.
                # Use the correct parameter name based on SDK version.
                _langfuse_config = {
                    "public_key": public_key,
                    "secret_key": secret_key,
                    host_param: host,  # 'base_url' for v3, 'host' for v2
                }
                _CallbackHandler = CallbackHandlerClass

                # Create the singleton Langfuse client (for direct API usage)
                _langfuse_client = LangfuseClass(
                    public_key=public_key,
                    secret_key=secret_key,
                    **{host_param: host},
                )
                logger.info("LangFuse initialised", extra={"host": host, "sdk_host_param": host_param})
            except Exception as e:
                logger.warning(f"Failed to initialize LangFuse: {e}")
                _langfuse_client = None
                _langfuse_config = None
                _CallbackHandler = None
    else:
        logger.info("LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY not set — LangFuse disabled")
        _langfuse_client = None
        _langfuse_config = None

    _otel_initialized = True


def get_langfuse() -> Optional[object]:
    """
    Get the singleton LangFuse client, or None if not configured.

    Call setup_telemetry() first to initialize.

    Returns:
        langfuse.Langfuse client instance, or None if LangFuse is not configured.
    """
    return _langfuse_client


def get_langfuse_callback_handler() -> Optional[object]:
    """
    Create a FRESH LangFuse CallbackHandler for LangChain/LangGraph integration.

    Each call returns a new handler instance. Each CallbackHandler is stateful
    and represents a single trace — reusing the same instance across requests
    causes traces to be silently dropped or merged.

    Usage:
        handler = get_langfuse_callback_handler()
        if handler:
            result = chain.invoke(input, config={"callbacks": [handler]})

    Call setup_telemetry() first to initialize.

    Returns:
        A new CallbackHandler instance, or None if LangFuse is not configured.
    """
    if _langfuse_config is None or _CallbackHandler is None:
        return None

    try:
        return _CallbackHandler(**_langfuse_config)
    except Exception as e:
        logger.warning(f"Failed to create LangFuse callback handler: {e}")
        return None


def flush_langfuse() -> None:
    """
    Flush any buffered LangFuse events.

    Call this during graceful shutdown to ensure all traces are sent.
    """
    if _langfuse_client is not None:
        try:
            _langfuse_client.flush()
        except Exception as e:
            logger.warning(f"Failed to flush LangFuse: {e}")
