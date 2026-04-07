"""
OpenTelemetry-first observability stack for the Enterprise AI Platform.

All traces — infrastructure AND LLM — flow through OpenTelemetry:

    Services → OTel SDK → OTel Collector → LangFuse / Datadog / Honeycomb / etc.

LLM traces are captured automatically via OpenLLMetry's LangChain instrumentor
(opentelemetry-instrumentation-langchain). No vendor-specific callback handlers
are injected into agent code.

LangFuse SDK is retained ONLY for the PromptManager feature (prompt versioning
and retrieval). It is not used for trace collection.

Call setup_telemetry(service_name) once at application startup — not at
module import time — so environment variables are guaranteed to be loaded.

Example:
    from platform_sdk import setup_telemetry, get_langfuse
    setup_telemetry("analytics-agent")

    # Use LangFuse client for prompt management only
    langfuse = get_langfuse()
    if langfuse:
        prompt = langfuse.get_prompt("my-prompt")
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


def setup_telemetry(service_name: str | None = None) -> None:
    """
    Initialise OpenTelemetry tracing and (optionally) the LangFuse client.

    Idempotent — safe to call multiple times; only initialises once.

    OTel: If OTEL_EXPORTER_OTLP_ENDPOINT is not set, tracing is silently
          skipped (useful in unit tests). When set, ALL traces (infrastructure
          + LLM) are sent to the OTel Collector via OTLP.

    LangFuse client: If LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set,
                     a LangFuse client is initialized for prompt management.
                     This client is NOT used for trace collection — traces
                     flow through OTel → OTel Collector → LangFuse OTLP endpoint.
    """
    global _otel_initialized, _langfuse_client
    if _otel_initialized:
        return

    # ── OTel tracing ──────────────────────────────────────────
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        name = service_name or os.getenv("SERVICE_NAME", "enterprise-ai-service")
        resource = Resource(attributes={"service.name": name})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}"))
        )
        trace.set_tracer_provider(provider)

        # Auto-instrument OpenAI SDK (LLM calls via LiteLLM)
        try:
            from opentelemetry.instrumentation.openai import OpenAIInstrumentor
            OpenAIInstrumentor().instrument()
        except ImportError:
            logger.debug("opentelemetry-instrumentation-openai not installed — skipping")

        # Auto-instrument LangChain/LangGraph (agent orchestration traces)
        try:
            from opentelemetry.instrumentation.langchain import LangchainInstrumentor
            LangchainInstrumentor().instrument()
            logger.info("LangChain/LangGraph OTel instrumentation enabled")
        except ImportError:
            logger.debug("opentelemetry-instrumentation-langchain not installed — skipping")

        logger.info("OpenTelemetry initialised", extra={"service": name, "endpoint": endpoint})
    else:
        logger.info("OTEL_EXPORTER_OTLP_ENDPOINT not set — OTel tracing disabled")

    # ── LangFuse client (prompt management only) ──────────────
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")

    if public_key and secret_key:
        try:
            from langfuse import Langfuse
            host = os.getenv("LANGFUSE_HOST", "http://langfuse:3000")

            # Detect v3 vs v2 API (v3 uses base_url, v2 uses host)
            try:
                _langfuse_client = Langfuse(
                    public_key=public_key,
                    secret_key=secret_key,
                    base_url=host,
                )
                logger.info("LangFuse client initialised (v3 API)", extra={"host": host})
            except TypeError:
                _langfuse_client = Langfuse(
                    public_key=public_key,
                    secret_key=secret_key,
                    host=host,
                )
                logger.info("LangFuse client initialised (v2 API)", extra={"host": host})
        except ImportError:
            logger.info("langfuse package not installed — prompt management disabled")
            _langfuse_client = None
        except Exception as e:
            logger.warning(f"Failed to initialize LangFuse client: {e}")
            _langfuse_client = None
    else:
        logger.info("LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY not set — LangFuse client disabled")
        _langfuse_client = None

    _otel_initialized = True


def get_langfuse() -> Optional[object]:
    """
    Get the singleton LangFuse client for prompt management, or None.

    This client is for prompt retrieval/versioning only. Trace collection
    goes through OpenTelemetry, not through this client.

    Call setup_telemetry() first to initialize.
    """
    return _langfuse_client


def flush_langfuse() -> None:
    """
    Flush any buffered LangFuse events.

    Call this during graceful shutdown to ensure all pending operations complete.
    """
    if _langfuse_client is not None:
        try:
            _langfuse_client.flush()
        except Exception as e:
            logger.warning(f"Failed to flush LangFuse: {e}")


# ── Deprecated — kept for backward compatibility during migration ──

def get_langfuse_callback_handler() -> None:
    """
    DEPRECATED: LLM traces now flow through OpenTelemetry automatically.

    The LangChain/LangGraph instrumentor captures all LLM spans via OTel.
    No callback handler injection is needed. This function always returns
    None so existing call sites degrade gracefully.
    """
    logger.debug(
        "get_langfuse_callback_handler() is deprecated — "
        "LLM traces are captured automatically via OTel LangChain instrumentor"
    )
    return None
