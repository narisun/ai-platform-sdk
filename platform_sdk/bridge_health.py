"""
Platform SDK — MCP Bridge Health Matrix.

Tracks which MCP bridges connected successfully at startup and exposes
their health status for readiness probes and operational dashboards.

Replaces the all-or-nothing startup pattern with graceful degradation:
bridges that fail to connect at startup continue reconnecting in the
background, while the agent starts serving requests with available bridges.

Usage (RM Prep orchestrator):
    from platform_sdk.bridge_health import BridgeHealthMatrix

    health = BridgeHealthMatrix()
    crm_bridge = MCPToolBridge(crm_url)
    payments_bridge = MCPToolBridge(payments_url)

    health.register("crm", crm_bridge)
    health.register("payments", payments_bridge)

    # Non-blocking startup — returns immediately with status
    await health.connect_all(startup_timeout=10.0)

    # Readiness probe
    status = health.readiness()
    # {"status": "degraded", "bridges": {"crm": "connected", "payments": "reconnecting"}}
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from .logging import get_logger

log = get_logger(__name__)


class BridgeHealthMatrix:
    """Tracks connection health of multiple MCP bridges.

    Provides a centralized view of which bridges are healthy, degraded,
    or disconnected. Supports the /health/ready endpoint pattern.
    """

    def __init__(self) -> None:
        self._bridges: dict[str, Any] = {}  # name → MCPToolBridge
        self._startup_status: dict[str, str] = {}  # name → status string

    def register(self, name: str, bridge: Any) -> None:
        """Register a bridge for health tracking."""
        self._bridges[name] = bridge
        self._startup_status[name] = "registered"

    async def connect_all(
        self,
        startup_timeout: float = 10.0,
    ) -> dict[str, str]:
        """Connect all registered bridges concurrently with a shared timeout.

        Returns a status dict: {bridge_name: "connected" | "reconnecting" | "failed"}.
        Bridges that don't connect within startup_timeout continue reconnecting
        in the background — the agent starts in a degraded state.
        """
        results: dict[str, str] = {}

        async def _connect_one(name: str, bridge: Any) -> tuple[str, str]:
            try:
                await bridge.connect(startup_timeout=startup_timeout)
                if bridge.is_connected:
                    return name, "connected"
                else:
                    return name, "reconnecting"
            except Exception as exc:
                log.error("bridge_startup_failed", bridge=name, error=str(exc))
                return name, "failed"

        # Connect all bridges concurrently
        tasks = [
            _connect_one(name, bridge)
            for name, bridge in self._bridges.items()
        ]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        for result in completed:
            if isinstance(result, Exception):
                log.error("bridge_connect_error", error=str(result))
                continue
            name, status = result
            results[name] = status
            self._startup_status[name] = status

        # Log summary
        connected = sum(1 for s in results.values() if s == "connected")
        total = len(results)
        log.info(
            "bridge_health_matrix",
            connected=connected,
            total=total,
            degraded=connected < total,
            statuses=results,
        )

        return results

    async def disconnect_all(self) -> None:
        """Disconnect all registered bridges."""
        for name, bridge in self._bridges.items():
            try:
                await bridge.disconnect()
                self._startup_status[name] = "disconnected"
            except Exception as exc:
                log.warning("bridge_disconnect_error", bridge=name, error=str(exc))

    def readiness(self) -> dict[str, Any]:
        """Return readiness status for all bridges.

        Status values:
        - "ok": All bridges connected
        - "degraded": Some bridges connected, others reconnecting
        - "unavailable": No bridges connected
        """
        bridge_status = {}
        for name, bridge in self._bridges.items():
            if bridge.is_connected:
                bridge_status[name] = "connected"
            elif self._startup_status.get(name) == "reconnecting":
                bridge_status[name] = "reconnecting"
            else:
                bridge_status[name] = "disconnected"

        connected = sum(1 for s in bridge_status.values() if s == "connected")
        total = len(bridge_status)

        if connected == total and total > 0:
            overall = "ok"
        elif connected > 0:
            overall = "degraded"
        else:
            overall = "unavailable"

        return {
            "status": overall,
            "bridges": bridge_status,
        }

    def is_bridge_available(self, name: str) -> bool:
        """Check if a specific bridge is connected."""
        bridge = self._bridges.get(name)
        return bridge is not None and bridge.is_connected

    def get_bridge(self, name: str) -> Optional[Any]:
        """Get a registered bridge by name."""
        return self._bridges.get(name)
