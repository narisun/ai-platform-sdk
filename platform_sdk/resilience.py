"""
Platform SDK — Reusable circuit breaker.

Extracts the circuit-breaker pattern that was duplicated in OpaClient
(security.py) and ToolResultCache (cache.py) into a single reusable class.

Usage:
    from platform_sdk.resilience import CircuitBreaker

    cb = CircuitBreaker(name="opa", failure_threshold=5, recovery_timeout=30.0)

    if cb.is_open:
        return False  # fail fast

    try:
        result = await do_something()
        cb.record_success()
        return result
    except TransientError:
        cb.record_failure()
"""
import time
from dataclasses import dataclass, field

from .logging import get_logger

log = get_logger(__name__)


@dataclass
class CircuitBreaker:
    """
    Lightweight circuit breaker with configurable threshold and recovery.

    After ``failure_threshold`` consecutive failures the circuit opens and
    all calls are short-circuited for ``recovery_timeout`` seconds.  After
    the timeout elapses a single probe is allowed through; if it succeeds
    the circuit closes.

    Thread/async safety: the state fields are simple scalars updated
    atomically by CPython's GIL.  No lock is needed for single-process
    async servers (which is how all MCP servers and agents run).

    Multi-worker limitation
    ───────────────────────
    Circuit state is stored in process memory.  In multi-worker deployments
    (multiple Uvicorn/Gunicorn workers or Kubernetes replicas), each worker
    has an independent copy of this object.  Worker A may open the circuit
    after N failures while Workers B and C continue sending requests — the
    circuit-open protection is effectively limited to 1/num_workers of traffic.

    This is acceptable for the current single-worker deployment model.  If
    you scale to multiple workers, back the circuit state in a shared store
    (e.g. Redis via the existing ToolResultCache infrastructure) using atomic
    increment and compare-and-swap operations.  Track this as a known limitation
    until then and monitor ``circuit_opened`` log events in your observability
    platform to detect cascading failure patterns.
    """

    name: str
    failure_threshold: int = 5
    recovery_timeout: float = 30.0

    # Internal state — not part of the public API
    _failures: int = field(default=0, init=False, repr=False)
    _open_until: float = field(default=0.0, init=False, repr=False)

    @property
    def is_open(self) -> bool:
        """True when the circuit is open (fail-fast mode)."""
        if self._failures < self.failure_threshold:
            return False
        if time.monotonic() >= self._open_until:
            # Recovery timeout elapsed — allow a probe
            return False
        return True

    @property
    def consecutive_failures(self) -> int:
        """Current consecutive failure count (useful for metrics/logging)."""
        return self._failures

    def record_success(self) -> None:
        """Reset the circuit on a successful call."""
        if self._failures > 0:
            log.info("circuit_closed", name=self.name, after_failures=self._failures)
        self._failures = 0

    def record_failure(self) -> None:
        """Track a failure.  Opens the circuit if threshold is reached."""
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._open_until = time.monotonic() + self.recovery_timeout
            log.warning(
                "circuit_opened",
                name=self.name,
                failures=self._failures,
                recovery_seconds=self.recovery_timeout,
            )
