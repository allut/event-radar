"""Äriregister (Estonian business register) lookup behind a Protocol.

Production calls the register through the shared ``http_get()`` and caches each
answer for 24 h. A lookup that cannot be answered raises ``RegistryUnavailable``,
so callers fail closed. Tests swap in ``tests/promotions/fakes.py``'s fake.
"""

import time
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import settings
from app.constants.promotions import (
    ARIREGISTER_CACHE_MAX_ENTRIES,
    ARIREGISTER_CACHE_TTL_SECONDS,
    ARIREGISTER_STATUS_DELETED,
    ARIREGISTER_TIMEOUT_SECONDS,
    REGISTRY_LOOKUP_DELETED,
    REGISTRY_LOOKUP_FOUND,
    REGISTRY_LOOKUP_NOT_FOUND,
)
from app.ingestion.http_client import http_get


class RegistryUnavailable(Exception):
    """The register could not be reached or gave an unusable answer."""


@dataclass(frozen=True)
class RegistryResult:
    status: str  # REGISTRY_LOOKUP_FOUND, _DELETED or _NOT_FOUND
    registry_code: str
    legal_name: str | None = None


class RegistryLookup(Protocol):
    async def lookup(self, registry_code: str) -> RegistryResult:
        """Look up one 8-digit registry code. Raises ``RegistryUnavailable``."""
        ...


class AriregisterLookup:
    """The production adapter. Expects the register's company endpoint to answer
    ``GET {base}/{code}`` with JSON carrying ``name`` and ``status`` (a 404 means
    no such company). Credentials are sent as HTTP Basic auth."""

    async def lookup(self, registry_code: str) -> RegistryResult:
        base = settings.ARIREGISTER_BASE_URL.rstrip("/")
        if not base or not settings.ARIREGISTER_USERNAME or not settings.ARIREGISTER_PASSWORD:
            raise RegistryUnavailable("Äriregister is not configured")
        auth = httpx.BasicAuth(settings.ARIREGISTER_USERNAME, settings.ARIREGISTER_PASSWORD)
        try:
            async with httpx.AsyncClient(
                timeout=ARIREGISTER_TIMEOUT_SECONDS, auth=auth
            ) as client:
                response = await http_get(client, f"{base}/{registry_code}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return RegistryResult(REGISTRY_LOOKUP_NOT_FOUND, registry_code)
            raise RegistryUnavailable(f"Äriregister answered {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise RegistryUnavailable("Äriregister request failed") from exc
        try:
            payload = response.json()
            name = str(payload["name"]).strip()
            status = str(payload.get("status", ""))
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise RegistryUnavailable("Äriregister answer was not understood") from exc
        if not name:
            raise RegistryUnavailable("Äriregister answer had no name")
        if status == ARIREGISTER_STATUS_DELETED:
            return RegistryResult(REGISTRY_LOOKUP_DELETED, registry_code, name)
        return RegistryResult(REGISTRY_LOOKUP_FOUND, registry_code, name)


class CachedRegistryLookup:
    """Wraps a lookup with a 24 h in-process cache. Only answers are cached; an
    outage is never remembered. The cache is per process, which is the only
    process there is (no Celery or Redis)."""

    def __init__(self, inner: RegistryLookup, ttl_seconds: float = ARIREGISTER_CACHE_TTL_SECONDS) -> None:
        self._inner = inner
        self._ttl = ttl_seconds
        self._entries: dict[str, tuple[float, RegistryResult]] = {}

    def clear(self) -> None:
        self._entries.clear()

    async def lookup(self, registry_code: str) -> RegistryResult:
        now = time.monotonic()
        hit = self._entries.get(registry_code)
        if hit is not None and now - hit[0] < self._ttl:
            return hit[1]
        result = await self._inner.lookup(registry_code)
        if len(self._entries) >= ARIREGISTER_CACHE_MAX_ENTRIES:
            self._entries.pop(next(iter(self._entries)))
        self._entries[registry_code] = (now, result)
        return result
