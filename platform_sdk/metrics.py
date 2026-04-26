"""
Platform SDK — OpenTelemetry metrics for circuit breakers, OPA, and caching.

Exposes key operational metrics as OpenTelemetry instruments so ops teams
can create alerts and dashboards for infrastructure health.

LLM-specific observability (token counts, cost, latency) is handled by LangFuse,
which is initialized via setup_telemetry(). These OTel metrics cover infrastructure
health and can be consumed by any OTel-compatible backend (Grafana, Datadog, etc.).

Metrics exposed:
    cache_circuit_breaker_state (gauge)       - 0=closed, 1=open
    cache_circuit_breaker_transitions (counter)- by state transition
    cache_consecutive_failures (gauge)        - current failure count
    opa_decisions_total (counter)             - by tool and decision
    opa_latency_seconds (histogram)           - authorization call latency
    opa_circuit_breaker_state (gauge)         - 0=closed, 1=open
    mcp_tool_calls_total (counter)            - by tool and outcome
    mcp_tool_latency_seconds (histogram)      - tool call latency

Usage:
    from platform_sdk.metrics import record_opa_decision, record_cache_state

    record_opa_decision(tool="execute_read_query", allowed=True, latency=0.05)
    record_cache_state(circuit_open=False, consecutive_failures=0)
"""
from __future__ import annotations

import logging
from typing import Optional

from .logging import get_logger

logger = logging.getLogger(__name__)
log = get_logger(__name__)

# Lazy initialization — metrics are only created if OTel is available
_meter = None
_instruments: dict = {}


def _get_meter():
    """Lazily create an OpenTelemetry Meter."""
    global _meter
    if _meter is not None:
        return _meter
    try:
        from opentelemetry import metrics as otel_metrics
        _meter = otel_metrics.get_meter("platform_sdk", "0.3.0")
    except ImportError:
        _meter = None
    return _meter


def _get_or_create(name: str, kind: str, **kwargs):
    """Get or lazily create an OTel instrument."""
    if name in _instruments:
        return _instruments[name]
    meter = _get_meter()
    if meter is None:
        return None
    try:
        if kind == "counter":
            inst = meter.create_counter(name, **kwargs)
        elif kind == "histogram":
            inst = meter.create_histogram(name, **kwargs)
        elif kind == "gauge":
            inst = meter.create_up_down_counter(name, **kwargs)
        else:
            return None
        _instruments[name] = inst
        return inst
    except Exception as exc:
        log.warning("otel_instrument_failed", name=name, error=str(exc))
        return None


# ---------------------------------------------------------------------------
# Cache circuit breaker metrics
# ---------------------------------------------------------------------------

def record_cache_state(circuit_open: bool, consecutive_failures: int) -> None:
    """Record cache circuit breaker state."""
    gauge = _get_or_create(
        "cache.circuit_breaker.state", "gauge",
        description="Cache circuit breaker state (0=closed, 1=open)",
        unit="1",
    )
    if gauge:
        gauge.add(1 if circuit_open else 0, {"component": "redis_cache"})

    failures_gauge = _get_or_create(
        "cache.consecutive_failures", "gauge",
        description="Cache consecutive failure count",
        unit="1",
    )
    if failures_gauge:
        failures_gauge.add(consecutive_failures, {"component": "redis_cache"})


def record_cache_transition(from_state: str, to_state: str) -> None:
    """Record cache circuit breaker state transition."""
    counter = _get_or_create(
        "cache.circuit_breaker.transitions", "counter",
        description="Cache circuit breaker state transitions",
        unit="1",
    )
    if counter:
        counter.add(1, {"from_state": from_state, "to_state": to_state})


# ---------------------------------------------------------------------------
# OPA authorization metrics
# ---------------------------------------------------------------------------

def record_opa_decision(tool: str, allowed: bool, latency: float) -> None:
    """Record an OPA authorization decision with latency."""
    counter = _get_or_create(
        "opa.decisions.total", "counter",
        description="Total OPA authorization decisions",
        unit="1",
    )
    if counter:
        counter.add(1, {"tool": tool, "decision": "allow" if allowed else "deny"})

    histogram = _get_or_create(
        "opa.latency.seconds", "histogram",
        description="OPA authorization call latency",
        unit="s",
    )
    if histogram:
        histogram.record(latency, {"tool": tool})


def record_opa_circuit_state(circuit_open: bool, consecutive_failures: int) -> None:
    """Record OPA circuit breaker state."""
    gauge = _get_or_create(
        "opa.circuit_breaker.state", "gauge",
        description="OPA circuit breaker state (0=closed, 1=open)",
        unit="1",
    )
    if gauge:
        gauge.add(1 if circuit_open else 0, {"component": "opa"})


# ---------------------------------------------------------------------------
# MCP tool call metrics
# ---------------------------------------------------------------------------

def record_mcp_tool_call(
    tool: str, outcome: str, latency: float, bridge_url: Optional[str] = None
) -> None:
    """Record an MCP tool call with outcome and latency.

    Args:
        tool: Tool name (e.g., "execute_read_query")
        outcome: "success", "error", "timeout", "unavailable"
        latency: Call duration in seconds
        bridge_url: Optional SSE URL for the bridge
    """
    counter = _get_or_create(
        "mcp.tool_calls.total", "counter",
        description="Total MCP tool calls",
        unit="1",
    )
    if counter:
        attrs = {"tool": tool, "outcome": outcome}
        if bridge_url:
            attrs["bridge"] = bridge_url
        counter.add(1, attrs)

    histogram = _get_or_create(
        "mcp.tool_latency.seconds", "histogram",
        description="MCP tool call latency",
        unit="s",
    )
    if histogram:
        histogram.record(latency, {"tool": tool, "outcome": outcome})
