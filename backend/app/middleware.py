import logging
from urllib.parse import urlsplit

from fastapi import Request, Response, status
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import settings
from app.constants.core import APP_ENV_DEVELOPMENT
from app.constants.http import (
    ASGI_MESSAGE_TYPE_REQUEST,
    ASGI_MESSAGE_TYPE_RESPONSE_BODY,
    ASGI_MESSAGE_TYPE_RESPONSE_START,
    ASGI_SCOPE_TYPE_HTTP,
    HEADER_HOST,
    HEADER_ORIGIN,
)
from app.constants.log_events import LOG_EVENT_HOST_REJECTED
from app.constants.ops import DEV_DB_LOCAL_HOSTS
from app.constants.security import (
    CSRF_UNSAFE_METHODS,
    ERROR_CSRF_ORIGIN_MISMATCH,
    HSTS_HEADER_NAME,
    HSTS_HEADER_VALUE,
    SECURITY_HEADERS,
    TRUSTED_HOST_REJECT_BODY,
)
from app.rate_limit import client_key

log = logging.getLogger(__name__)


class CsrfOriginCheckMiddleware:
    """Reject a mutating request whose Origin header doesn't match a trusted
    origin, with 403.

    Second CSRF layer behind SameSite=Strict now that #26 has moved session
    auth to a cookie — a foreign page's fetch/form submission carries the
    cookie automatically, which a Bearer header never did.

    A request with no Origin header is let through — browsers omit it on
    simple/no-CORS navigations for some methods, and server-to-server callers
    (the Resend inbound-mail webhook, RFC 8058 one-click unsubscribe POSTs
    from mail clients) never send one either. Non-mutating methods (GET,
    HEAD, OPTIONS, ...) are never checked.
    """

    def __init__(self, app: ASGIApp, trusted_origins: frozenset[str]) -> None:
        self.app = app
        self.trusted_origins = trusted_origins

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            {"detail": ERROR_CSRF_ORIGIN_MISMATCH},
            status_code=status.HTTP_403_FORBIDDEN,
        )
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != ASGI_SCOPE_TYPE_HTTP
            or scope["method"] not in CSRF_UNSAFE_METHODS
        ):
            await self.app(scope, receive, send)
            return

        origin = Headers(scope=scope).get(HEADER_ORIGIN)
        if origin is not None and origin not in self.trusted_origins:
            await self._reject(scope, receive, send)
            return

        await self.app(scope, receive, send)


class HostCheckMiddleware:
    """TrustedHostMiddleware with path exemptions — Render's health probe hits
    this process over the private network, so its Host header is the
    instance's internal address, not BACKEND_URL's hostname. That IP rotates
    per deploy and Starlette's allowed_hosts takes no CIDR, so the probe path
    is exempted instead."""

    def __init__(
        self, app: ASGIApp, allowed_hosts: list[str], exempt_paths: frozenset[str]
    ) -> None:
        self._app = app
        self._guarded = TrustedHostMiddleware(app, allowed_hosts=allowed_hosts)
        self._exempt_paths = exempt_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == ASGI_SCOPE_TYPE_HTTP
            and scope.get("path") in self._exempt_paths
        ):
            await self._app(scope, receive, send)
            return

        saw_400 = False
        rejected = False
        # This middleware is registered outside (wraps around) the
        # add_security_headers layer, so TrustedHostMiddleware's own 400
        # response — built and sent directly, without ever calling
        # self.app — never passes through that layer (L-1 in the OWASP
        # audit). A pass-through response (self.app called, valid host)
        # already carries the headers by the time it reaches here, since
        # add_security_headers sits further in; MutableHeaders.__setitem__
        # replaces rather than duplicates an existing value, so setting them
        # unconditionally on every 400 is safe either way. The response.start
        # message is held back until response.body arrives (TrustedHost's
        # rejection is always exactly these two messages) so the body can
        # still be inspected for the log line below before headers are sent.
        pending_start: Message | None = None

        async def _send(message: Message) -> None:
            nonlocal saw_400, rejected, pending_start
            if message["type"] == ASGI_MESSAGE_TYPE_RESPONSE_START:
                saw_400 = message["status"] == status.HTTP_400_BAD_REQUEST
                if saw_400:
                    pending_start = message
                    return
            elif message["type"] == ASGI_MESSAGE_TYPE_RESPONSE_BODY:
                if saw_400 and pending_start is not None:
                    if TRUSTED_HOST_REJECT_BODY in message.get("body", b""):
                        rejected = True
                    headers = MutableHeaders(raw=pending_start["headers"])
                    for name, value in SECURITY_HEADERS.items():
                        headers[name] = value
                    await send(pending_start)
                    pending_start = None
                saw_400 = False
            await send(message)

        await self._guarded(scope, receive, _send)
        if rejected:
            log.warning(
                "Host header rejected: host=%r path=%r client=%r",
                Headers(scope=scope).get(HEADER_HOST),
                scope.get("path"),
                client_key(Request(scope)),
                extra={"event": LOG_EVENT_HOST_REJECTED},
            )


class _BodyTooLarge(Exception):
    """Internal sentinel — never escapes MaxBodySizeMiddleware.__call__."""


class MaxBodySizeMiddleware:
    """Reject a request body over MAX_REQUEST_BODY_BYTES with 413.

    Nothing else in the stack caps request size — IMAGE_UPLOAD_MAX_BYTES only
    bounds what the upload handler reads after Starlette has already received
    and spooled the full multipart body. A ``Content-Length`` request is
    rejected up front, before the body is read at all; a chunked request (no
    ``Content-Length``) is rejected mid-stream once the running total crosses
    the limit, via the wrapped ``receive`` callable.

    This sends the 413 response itself (an ASGI ``Response.__call__``) rather
    than raising ``HTTPException`` — Starlette places every ``add_middleware``
    entry *outside* its internal ``ExceptionMiddleware`` (which is innermost,
    right next to the router), so an ``HTTPException`` raised from here would
    never reach it and would surface as a generic 500 from
    ``ServerErrorMiddleware`` instead of the intended 413.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        # This middleware is registered outside (wraps around) the
        # add_security_headers layer, so a response built here never passes
        # through it — set the headers directly, or this 413 ships without
        # CSP/nosniff/etc. (L-1 in the OWASP audit).
        response = JSONResponse(
            {"detail": f"Request body exceeds {self.max_bytes} bytes."},
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            headers=SECURITY_HEADERS,
        )
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != ASGI_SCOPE_TYPE_HTTP:
            await self.app(scope, receive, send)
            return

        content_length = Headers(scope=scope).get("content-length")
        if content_length is not None:
            try:
                too_large = int(content_length) > self.max_bytes
            except ValueError:
                too_large = False
            if too_large:
                await self._reject(scope, receive, send)
                return

        seen = 0

        async def limited_receive() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == ASGI_MESSAGE_TYPE_REQUEST:
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    raise _BodyTooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLarge:
            await self._reject(scope, receive, send)


def resolve_allowed_hosts() -> list[str]:
    """Host allowlist for HostCheckMiddleware: Render's auto-injected public
    hostname plus BACKEND_URL's. Local/dev hostnames are dropped — outside
    development they mean the env var was never set, and installing the
    middleware on that allowlist 400s all public traffic (the 0.1.6 outage).
    An empty result means the caller skips the middleware entirely: Host
    validation is cache-poisoning hardening only, so degrading it beats
    taking the API down."""
    candidates = [
        settings.RENDER_EXTERNAL_HOSTNAME.strip().lower(),
        (urlsplit(settings.BACKEND_URL).hostname or "").lower(),
    ]
    hosts: list[str] = []
    for host in candidates:
        if host and host not in DEV_DB_LOCAL_HOSTS and host not in hosts:
            hosts.append(host)
    if not hosts:
        log.error(
            "Host allowlist could not be resolved (RENDER_EXTERNAL_HOSTNAME=%r, "
            "BACKEND_URL=%r both empty/local) — HostCheckMiddleware will NOT be "
            "installed; Host-header validation is disabled",
            settings.RENDER_EXTERNAL_HOSTNAME,
            settings.BACKEND_URL,
        )
    return hosts


async def add_security_headers(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    """Set CSP/nosniff/frame-ancestors/referrer-policy on every response — defense
    in depth against XSS and clickjacking. HSTS is added only in production, since
    it's only safe to advertise over HTTPS (Render terminates TLS in front of us;
    local dev runs over plain http://localhost)."""
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers[name] = value
    if settings.APP_ENV != APP_ENV_DEVELOPMENT:
        response.headers[HSTS_HEADER_NAME] = HSTS_HEADER_VALUE
    return response
