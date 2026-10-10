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
import re
from urllib.parse import urlsplit, urlunsplit

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
    DNS_RESOLVE_CACHE_TTL_SECONDS,
    HEADER_RETRY_AFTER,
    HOST_WWW_PREFIX,
    HTTPS_DEFAULT_PORT,
    HTTP_RETRYABLE_STATUS_CODES,
    HTTP_RETRY_AFTER_MAX_SECONDS,
    HTTP_RETRY_JITTER_MAX,
    HTTP_RETRY_MAX_ATTEMPTS,
    HTTP_RETRY_WAIT_MAX,
    HTTP_RETRY_WAIT_MIN,
    HTTP_RETRY_WAIT_MULTIPLIER,
    SAFE_URL_SCHEMES,
    SITE_LOCAL_IPV6_CIDR,
    URL_RENDER_FORBIDDEN_RE,
    URL_SCHEME_HTTPS,
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
    header = exc.response.headers.get(HEADER_RETRY_AFTER)
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
        parts = urlsplit(str(request.url))
        # Pin scheme and port too, not just hostname (OWASP audit F14) — a
        # hostname-only check lets a redirect to the same allowlisted host on
        # a non-standard port, or an https->http downgrade, pass unnoticed.
        # Every allowed source is fetched over https on the default port, so
        # anything else is a permanent guard failure, same as a host mismatch.
        if (
            parts.hostname not in hosts
            or parts.scheme != URL_SCHEME_HTTPS
            or parts.port not in (None, HTTPS_DEFAULT_PORT)
        ):
            # ValueError, not httpx.RequestError: a host mismatch is a
            # permanent guard failure, not a transient one, and
            # httpx.RequestError is retried by _http_retry's predicate.
            raise ValueError(f"request host mismatch (SSRF guard): {request.url}")
        # Re-check DNS rebinding on every hop this hook fires for, not just
        # the initial fetch — safe_fetchable_url only resolves once at ingest
        # time, so refetch.py's daily re-fetch of stored URLs previously never
        # re-ran this check (OWASP audit F15). Cached per-hostname (see
        # resolves_to_private_ip), so this is a cache hit on every request
        # after the first for a given source host within the TTL.
        if await asyncio.to_thread(resolves_to_private_ip, parts.hostname):
            raise ValueError(
                f"request host resolves to a private/reserved address (SSRF guard): {request.url}"
            )

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


async def http_get_stored_url(
    client: httpx.AsyncClient,
    url: str,
    *,
    source: str | None = None,
) -> httpx.Response:
    """http_get for a stored, untrusted Event.url that is fetched on a
    request path (claim target resolution, claim verification, the claim-edit
    price-mismatch check) rather than through a host-guarded ingest/refetch
    client (OWASP audit #2). Refuses — with ValueError, like host_guard_hook —
    anything but https on the default port to an ALLOWED_SOURCE_HOSTS host
    that resolves to a public address. Callers catch ValueError next to
    httpx.HTTPError. Redirects are not followed (the shared client leaves
    httpx's follow_redirects off), so a 3xx raises via raise_for_status
    rather than hopping to an unchecked host."""
    parts = urlsplit(url)
    if (
        parts.scheme.lower() != URL_SCHEME_HTTPS
        or parts.port not in (None, HTTPS_DEFAULT_PORT)
        or await safe_fetchable_url(url, source) is None
    ):
        raise ValueError(f"event url not fetchable (SSRF guard): {url}")
    return await http_get(client, url)


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


_URL_RENDER_FORBIDDEN = re.compile(URL_RENDER_FORBIDDEN_RE)


def safe_render_url(url: str | None) -> str | None:
    """Validate a user-supplied URL that is only ever *rendered* (href/src/
    email <img>) and return its re-serialized form, or None when unsafe.

    Python's ``urlsplit``/httpx read ``https://evil.com\\@fienta.com/x`` as host
    ``fienta.com`` while a browser (WHATWG) reads host ``evil.com`` — so any
    host pin checked server-side can be bypassed for the *rendered* link
    (OWASP audit M-1). Reject the ambiguity outright: backslashes, controls,
    whitespace anywhere (and non-ASCII in the authority); http(s) only; a host; no userinfo; no
    ``%`` in the authority; no explicit port. Storing the re-serialized URL
    (not the raw input) keeps what we validated identical to what we render.
    """
    if not url or _URL_RENDER_FORBIDDEN.search(url):
        return None
    try:
        parts = urlsplit(url)
        port = parts.port
        hostname = parts.hostname
    except ValueError:
        return None
    if (
        parts.scheme.lower() not in SAFE_URL_SCHEMES
        or not hostname
        or port is not None
        or "@" in parts.netloc
        or "%" in parts.netloc
        or not parts.netloc.isascii()
    ):
        return None
    return urlunsplit(parts)


def normalized_hostname(url: str | None) -> str:
    """URL hostname, lowercased with any leading "www." stripped, or "" if none.

    Shared by refetch.py/pinning.py's per-host dispatch (locale-text and
    price-fallback extractors) so both bare and www variants of a source host
    match the same lookup key.
    """
    hostname = urlsplit(url or "").hostname or ""
    return hostname.removeprefix(HOST_WWW_PREFIX)


def host_matches_domain(hostname: str, domain: str) -> bool:
    """True when ``hostname`` is ``domain`` itself or a subdomain of it.
    The dot-anchored suffix rules out lookalikes ("notgmail.com" vs
    "gmail.com"). Case-sensitive — callers lowercase first when needed."""
    return hostname == domain or hostname.endswith(f".{domain}")


def host_is_allowed(hostname: str | None) -> bool:
    """True when hostname is (or is a subdomain of) an ALLOWED_SOURCE_HOSTS entry."""
    if not hostname:
        return False
    hostname = hostname.lower()
    return any(host_matches_domain(hostname, allowed) for allowed in ALLOWED_SOURCE_HOSTS)


# host -> (verdict, expires_at monotonic time). A source's event batch shares
# 1-4 hostnames, so this turns O(N_new) redundant getaddrinfo() calls per
# ingest run into effectively O(distinct hosts). Not thread-safe against a
# torn read/write under true multi-threading, but this process is single
# event-loop asyncio (each caller reaches this via asyncio.to_thread from the
# same loop), so a stale-by-one-TTL read is the only realistic race — no worse
# than the TOCTOU window already documented below.
_SITE_LOCAL_IPV6 = ipaddress.ip_network(SITE_LOCAL_IPV6_CIDR)
_dns_verdict_cache: dict[str | None, tuple[bool, float]] = {}


def resolves_to_private_ip(hostname: str | None) -> bool:
    """True when hostname has ANY non-public-routable address (or fails to resolve).

    Guards against DNS rebinding on an otherwise-allowlisted host (e.g. a
    misconfigured or compromised DNS record for an ALLOWED_SOURCE_HOSTS
    domain pointing at cloud metadata or an internal service). Resolution
    failure is treated as "private" (fail closed) rather than "unknown, so
    allow" — a source we can't resolve isn't one we should be fetching.

    Verdicts are cached per-hostname for DNS_RESOLVE_CACHE_TTL_SECONDS — an
    ingest run fetches many events from the same 1-4 hostnames, and each
    uncached call is a thread hand-off plus a real DNS round trip.

    Known trade-off (documented, not fixed here): this resolves once at
    check time (now up to DNS_RESOLVE_CACHE_TTL_SECONDS stale). httpx
    re-resolves the host itself when it opens the connection, so a TOCTOU
    window remains between this check and the actual request if a resolver
    returns a different address in the meantime — the cache widens that
    existing window somewhat but does not introduce a new class of risk.
    Closing it fully would require pinning the resolved IP for the
    connection (e.g. a custom httpx transport), which is out of scope here.
    """
    cached = _dns_verdict_cache.get(hostname)
    now = time.monotonic()
    if cached is not None and cached[1] > now:
        return cached[0]

    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        verdict = True
    else:
        # EVERY resolved address must be globally routable: httpx may connect
        # to any answer, so a mixed public + 127.0.0.1 reply is a rebinding
        # vector. is_global also rejects CGNAT 100.64/10 and fec0::/10, which
        # the is_private/is_reserved family misses (OWASP audit L-2).
        verdict = False
        for _family, _type, _proto, _canonname, sockaddr in infos:
            ip = ipaddress.ip_address(sockaddr[0])
            if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
                ip = ip.ipv4_mapped
            if not ip.is_global or ip.is_multicast or ip in _SITE_LOCAL_IPV6:
                verdict = True
                break
        if not infos:
            verdict = True

    _dns_verdict_cache[hostname] = (verdict, now + DNS_RESOLVE_CACHE_TTL_SECONDS)
    return verdict


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

