"""Shared outbound-HTTP infrastructure for ingestion.

Retrying GET/POST (tenacity exponential backoff, Retry-After aware), a
min-interval rate limiter, and the SSRF guards every server-side fetch of an
untrusted URL must pass (host allowlist, private-IP resolution check, and the
per-redirect-hop host_guard_hook).
"""

import asyncio
import http
import ipaddress
import logging
import socket
import time
from collections.abc import Callable, Coroutine
from datetime import UTC
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

from app.constants import (
    ALLOWED_SOURCE_HOSTS,
    HTTP_RETRY_AFTER_MAX_SECONDS,
    HTTP_RETRYABLE_STATUS_CODES,
    HTTP_RETRY_JITTER_MAX,
    HTTP_RETRY_MAX_ATTEMPTS,
    HTTP_RETRY_WAIT_MAX,
    HTTP_RETRY_WAIT_MIN,
    HTTP_RETRY_WAIT_MULTIPLIER,
    SAFE_URL_SCHEMES,
)

log = logging.getLogger(__name__)


def _is_retryable(exc: BaseException) -> bool:
    """Return True for transient HTTP failures worth retrying."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in HTTP_RETRYABLE_STATUS_CODES
    return isinstance(exc, httpx.RequestError)


def retry_after_seconds(exc: BaseException) -> float | None:
    """Parse a 429 response's Retry-After header (seconds or HTTP-date form).

    Returns None if exc isn't a 429 HTTPStatusError or the header is missing/
    unparseable. Capped at HTTP_RETRY_AFTER_MAX_SECONDS so a misbehaving or
    malicious upstream can't stall the retry loop indefinitely.
    """
    if not isinstance(exc, httpx.HTTPStatusError):
        return None
    if exc.response.status_code != http.HTTPStatus.TOO_MANY_REQUESTS:
        return None
    header = exc.response.headers.get("Retry-After")
    if not header:
        return None
    try:
        seconds = float(header)
    except ValueError:
        try:
            dt = parsedate_to_datetime(header)
        except (TypeError, ValueError):
            return None
        if dt.tzinfo is None:
            # RFC 7231 HTTP-dates always carry GMT, but parsedate_to_datetime
            # returns a naive datetime if the source string omits a zone —
            # treat that as UTC rather than letting .timestamp() assume local.
            dt = dt.replace(tzinfo=UTC)
        seconds = dt.timestamp() - time.time()
    return max(0.0, min(seconds, HTTP_RETRY_AFTER_MAX_SECONDS))


def _retry_wait(retry_state: RetryCallState) -> float:
    """Honor a 429's Retry-After header; otherwise jittered exponential backoff."""
    outcome = retry_state.outcome
    if outcome is not None and outcome.failed:
        exc = outcome.exception()
        if exc is not None:
            wait = retry_after_seconds(exc)
            if wait is not None:
                return wait
    base_wait = wait_exponential(
        multiplier=HTTP_RETRY_WAIT_MULTIPLIER,
        min=HTTP_RETRY_WAIT_MIN,
        max=HTTP_RETRY_WAIT_MAX,
    )(retry_state)
    jitter = wait_random(0, HTTP_RETRY_JITTER_MAX)(retry_state)
    return base_wait + jitter


_http_retry = retry(
    retry=retry_if_exception(_is_retryable),
    wait=_retry_wait,
    stop=stop_after_attempt(HTTP_RETRY_MAX_ATTEMPTS),
    reraise=True,
)


class AsyncRateLimiter:
    """Min-interval gate: serializes acquire() calls so they are >= interval apart.

    Used to proactively pace outbound requests to a rate-limited upstream (Fienta)
    instead of relying solely on reactive retry after a 429 is already hit.
    """

    def __init__(self, interval_seconds: float) -> None:
        self._interval = interval_seconds
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._next_allowed - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = time.monotonic()
            self._next_allowed = now + self._interval

    def backoff(self, seconds: float) -> None:
        """Push the next-allowed time out by at least `seconds` from now.

        Called when a request exhausts retries on a 429, so remaining callers
        sharing this limiter back off together instead of piling onto a source
        that has already signalled it's overloaded.
        """
        candidate = time.monotonic() + seconds
        if candidate > self._next_allowed:
            self._next_allowed = candidate


def host_guard_hook(
    allowed_hosts: str | None | frozenset[str | None],
) -> Callable[[httpx.Request], Coroutine[Any, Any, None]]:
    """Build a client `request` event hook enforcing every request — including
    each redirect hop httpx follows — stays within allowed_hosts (SSRF guard).

    httpx fires the `request` hook once per hop inside its redirect loop, so
    this is the only point that can validate a redirect's *destination* host;
    pre-fetch checks elsewhere only validate the un-redirected URL. Accepts a
    single host or a frozenset when a source legitimately spans more than one
    host (e.g. a deliberate cross-host lookup against a fixed, hardcoded URL).
    """
    raw_hosts: frozenset[str | None] = (
        allowed_hosts
        if isinstance(allowed_hosts, frozenset)
        else frozenset({allowed_hosts})
    )
    # Drop None — a malformed configured URL whose hostname parses to None
    # must never become an allowed host; that would let any redirect target
    # that also parses to a None hostname (e.g. a non-network scheme) bypass
    # the guard. Excluding it makes a misconfigured source fail closed.
    hosts: frozenset[str] = frozenset(h for h in raw_hosts if h is not None)

    async def hook(request: httpx.Request) -> None:
        if urlsplit(str(request.url)).hostname not in hosts:
            # ValueError, not httpx.RequestError: a host mismatch is a
            # permanent guard failure, not a transient one, and
            # httpx.RequestError is retried by _http_retry's predicate.
            raise ValueError(f"request host mismatch (SSRF guard): {request.url}")

    return hook


@_http_retry
async def http_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
) -> httpx.Response:
    """Shared HTTP GET with exponential-backoff retry for transient failures."""
    r = await client.get(url, params=params, headers=headers)
    r.raise_for_status()
    return r


@_http_retry
async def http_post(
    client: httpx.AsyncClient,
    url: str,
    *,
    data: dict | None = None,
    json_body: dict | None = None,
    headers: dict | None = None,
    files: dict[str, Any] | None = None,
) -> httpx.Response:
    """Shared HTTP POST with exponential-backoff retry for transient failures.

    `files` is httpx's multipart mapping (e.g. Cloudinary's signed image upload) —
    kept alongside `data`/`json_body` rather than a separate helper so every
    outbound POST shares one retry/Retry-After policy."""
    r = await client.post(url, data=data, json=json_body, headers=headers, files=files)
    r.raise_for_status()
    return r


def safe_external_url(url: str | None, source: str | None = None) -> str | None:
    """Drop URLs whose scheme isn't http(s) — guards against stored XSS via
    javascript:/data: URLs from untrusted sources rendered into <a href>/<img src>.

    Scheme-only: safe for values that are only ever rendered client-side
    (e.g. Event.image_url) and never fetched by our own server. Values that
    ARE fetched server-side (e.g. Event.url, re-fetched daily by
    app/ingestion/refetch.py) must go through safe_fetchable_url instead,
    which additionally pins the host against SSRF."""
    if not url:
        return None
    scheme = urlsplit(url).scheme.lower()
    if scheme not in SAFE_URL_SCHEMES:
        log.warning(
            "dropped non-http(s) url from source %s: scheme=%s", source, scheme
        )
        return None
    return url


def host_is_allowed(hostname: str | None) -> bool:
    """True when hostname is (or is a subdomain of) an ALLOWED_SOURCE_HOSTS entry."""
    if not hostname:
        return False
    hostname = hostname.lower()
    return any(
        hostname == allowed or hostname.endswith(f".{allowed}")
        for allowed in ALLOWED_SOURCE_HOSTS
    )


def resolves_to_private_ip(hostname: str | None) -> bool:
    """True when hostname has no public-routable address (or fails to resolve).

    Guards against DNS rebinding on an otherwise-allowlisted host (e.g. a
    misconfigured or compromised DNS record for an ALLOWED_SOURCE_HOSTS
    domain pointing at cloud metadata or an internal service). Resolution
    failure is treated as "private" (fail closed) rather than "unknown, so
    allow" — a source we can't resolve isn't one we should be fetching.

    Known trade-off (documented, not fixed here): this resolves once at
    check time. httpx re-resolves the host itself when it opens the
    connection, so a narrow TOCTOU window remains between this check and the
    actual request if a resolver returns a different address a moment later.
    Closing that fully would require pinning the resolved IP for the
    connection (e.g. a custom httpx transport), which is out of scope here.
    """
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return True
    for family, _type, _proto, _canonname, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if not (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False  # at least one public address — good enough to allow
    return True  # every resolved address was non-public


async def safe_fetchable_url(url: str | None, source: str | None = None) -> str | None:
    """Drop any URL that is not safe for OUR server to fetch (SSRF guard).

    Use for values later fetched server-side — currently Event.url, re-fetched
    daily by app/ingestion/refetch.py. Layers on top of safe_external_url's
    scheme check: the host must also be in ALLOWED_SOURCE_HOSTS and must not
    resolve to a private/reserved/loopback address. The DNS check runs in a
    thread (asyncio.to_thread) — it's blocking I/O and this is called from
    the ingestion run loop, which shares the event loop with the FastAPI app.
    """
    scheme_checked = safe_external_url(url, source)
    if scheme_checked is None:
        return None
    hostname = urlsplit(scheme_checked).hostname
    if not host_is_allowed(hostname):
        log.warning(
            "dropped fetchable url from source %s: host not allowlisted (%s)",
            source,
            hostname,
        )
        return None
    if await asyncio.to_thread(resolves_to_private_ip, hostname):
        log.warning(
            "dropped fetchable url from source %s: host resolves to a "
            "private/reserved/unresolvable address (%s)",
            source,
            hostname,
        )
        return None
    return scheme_checked

