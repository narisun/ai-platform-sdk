"""Async client for the ai-registry service.

Owns:
  - lookup(name) -> RegistryEntry
      cache-first; refreshes on stale; soft-fails to stale cache
      on registry outages within stale_cache_max_seconds.
  - register_self(payload), deregister(), heartbeat task, refresh task
      (added in Task 3 alongside register/deregister and the background tasks)

The client is owned by Application._register() — every agent and MCP gets one
on startup automatically. Service code never instantiates this directly.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

import httpx

from ..logging import get_logger
from ..resilience import CircuitBreaker
from .exceptions import RegistryUnreachable, ServiceNotFound
from .models import RegistryEntry

log = get_logger(__name__)


@dataclass(frozen=True)
class _CacheEntry:
    entry: RegistryEntry
    fetched_at: float

    def fresh(self, refresh_seconds: float) -> bool:
        return (time.monotonic() - self.fetched_at) < refresh_seconds

    def age(self) -> float:
        return time.monotonic() - self.fetched_at


class RegistryClient:
    def __init__(
        self,
        *,
        registry_url: str,
        api_key: str,
        heartbeat_seconds: float = 15.0,
        refresh_seconds: float = 30.0,
        stale_cache_max_seconds: float = 300.0,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self._url = registry_url.rstrip("/")
        self._api_key = api_key
        self._heartbeat_seconds = heartbeat_seconds
        self._refresh_seconds = refresh_seconds
        self._stale_cache_max_seconds = stale_cache_max_seconds
        self._cache: dict[str, _CacheEntry] = {}
        self._client = httpx.AsyncClient(
            base_url=self._url,
            timeout=httpx.Timeout(connect=1.0, read=5.0, write=5.0, pool=5.0),
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
        )
        self._cb = CircuitBreaker(
            name="registry",
            failure_threshold=5,
            recovery_timeout=30.0,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def lookup(self, name: str) -> RegistryEntry:
        cached = self._cache.get(name)
        if cached and cached.fresh(self._refresh_seconds):
            return cached.entry

        if self._cb.is_open:
            log.warning("registry_circuit_open", name=name)
            return self._stale_or_raise(name, cached)

        try:
            entry = await self._fetch(name)
        except (RegistryUnreachable, httpx.HTTPError) as exc:
            log.warning("registry_unreachable", name=name, error=str(exc))
            self._cb.record_failure()
            return self._stale_or_raise(name, cached)

        self._cb.record_success()
        self._cache[name] = _CacheEntry(entry=entry, fetched_at=time.monotonic())
        return entry

    def _stale_or_raise(self, name: str, cached: Optional[_CacheEntry]) -> RegistryEntry:
        if cached is not None and cached.age() < self._stale_cache_max_seconds:
            log.warning("registry_unreachable_using_stale", name=name, age=cached.age())
            return cached.entry
        raise ServiceNotFound(name)

    async def _fetch(self, name: str) -> RegistryEntry:
        try:
            r = await self._client.get(f"/api/services/{name}")
        except httpx.RequestError as exc:
            raise RegistryUnreachable(str(exc)) from exc
        if r.status_code == 404:
            raise ServiceNotFound(name)
        if r.status_code >= 500:
            raise RegistryUnreachable(f"registry {r.status_code}")
        r.raise_for_status()
        return RegistryEntry.model_validate(r.json())

    # ------------------------------------------------------------------
    # Registration / deregistration
    # ------------------------------------------------------------------

    async def register_self(self, payload: dict) -> None:
        """POST /api/services with a RegistrationRequest. 409 is idempotent."""
        try:
            r = await self._client.post("/api/services", json=payload)
        except httpx.RequestError as exc:
            raise RegistryUnreachable(str(exc)) from exc
        if r.status_code == 409:
            log.info("registration_idempotent", name=payload["name"])
            return
        r.raise_for_status()
        log.info("registration", name=payload["name"], url=payload["url"], type=payload["type"])
        self._registered_name = payload["name"]

    async def deregister(self, name: str) -> None:
        """DELETE /api/services/{name}. Logs but does not raise on failure."""
        try:
            await self._client.delete(f"/api/services/{name}")
            log.info("deregistration", name=name)
        except httpx.HTTPError as exc:
            log.warning("deregistration_failed", name=name, error=str(exc))

    # ------------------------------------------------------------------
    # Heartbeat task
    # ------------------------------------------------------------------

    async def start_heartbeat(self, name: str) -> None:
        if getattr(self, "_heartbeat_task", None) is not None:
            return
        self._heartbeat_name = name

        async def _loop() -> None:
            while True:
                try:
                    r = await self._client.post(f"/api/services/{name}/heartbeat")
                    if r.status_code != 200:
                        log.warning("heartbeat_non_200", name=name, status=r.status_code)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.warning("heartbeat_failed", name=name, error=str(exc))
                await asyncio.sleep(self._heartbeat_seconds)

        self._heartbeat_task = asyncio.create_task(_loop())

    async def stop_heartbeat(self) -> None:
        task = getattr(self, "_heartbeat_task", None)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self._heartbeat_task = None

    # ------------------------------------------------------------------
    # Refresh task — repopulate full cache periodically
    # ------------------------------------------------------------------

    async def start_refresh(self) -> None:
        if getattr(self, "_refresh_task", None) is not None:
            return

        async def _loop() -> None:
            while True:
                await asyncio.sleep(self._refresh_seconds)
                try:
                    r = await self._client.get("/api/services")
                    if r.status_code == 200:
                        body = r.json()
                        services = body.get("services", body) if isinstance(body, dict) else body
                        for raw in services:
                            entry = RegistryEntry.model_validate(raw)
                            self._cache[entry.name] = _CacheEntry(
                                entry=entry, fetched_at=time.monotonic()
                            )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.warning("refresh_failed", error=str(exc))

        self._refresh_task = asyncio.create_task(_loop())

    async def stop_refresh(self) -> None:
        task = getattr(self, "_refresh_task", None)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self._refresh_task = None
