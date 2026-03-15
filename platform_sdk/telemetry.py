"""
OpenTelemetry setup for the Enterprise AI Platform.

Call setup_telemetry(service_name) once at application startup — not at
module import time — so environment variables are guaranteed to be loaded.

Example:
    from platform_sdk import setup_telemetry
    setup_telemetry("ai-agents")
"""
import os
import logging
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

logger = logging.getLogger(__name__)

_initialized = False


def setup_telemetry(service_name: str | None = None) -> None:
    """
    Initialise OpenTelemetry with the OTLP exporter.

    Idempotent — safe to call multiple times; only initialises once.
    If OTEL_EXPORTER_OTLP_ENDPOINT is not set, telemetry is silently
    skipped (useful in unit tests).
    """
    global _initialized
    if _initialized:
        return

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        logger.info("OTEL_EXPORTER_OTLP_ENDPOINT not set — telemetry disabled")
        _initialized = True
        return

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

    _initialized = True
    logger.info("OpenTelemetry initialised", extra={"service": name, "endpoint": endpoint})
