"""Shared per-IP rate limiter instance.

Lives in its own module (mirroring db.py's role for the engine/session) so that
both app.main (middleware/exception-handler wiring) and routers (per-endpoint
@limiter.limit decorators) can import it without a circular dependency.
"""

import logging
from typing import cast

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ExceptionHandler

from app.constants import LOG_EVENT_RATE_LIMIT_BLOCK

log = logging.getLogger(__name__)


def client_key(request: Request) -> str:
    """Rate-limit / audit-log key: the rightmost X-Forwarded-For entry.

    ProxyHeadersMiddleware(trusted_hosts="*") rewrites request.client from the
    *leftmost* XFF hop (uvicorn's _TrustedHosts.get_trusted_client_address),
    which is attacker-controlled — a client can prepend an arbitrary
    X-Forwarded-For value and every @limiter.limit(...) becomes a no-op. The
    rightmost entry is the one appended by the single trusted hop immediately
    adjacent to this process (Render's proxy), so it is correct whether Render
    appends to or overwrites the header, given exactly one trusted hop between
    the client and this process (see the deployment-invariant comment in
    app/main.py next to ProxyHeadersMiddleware).
    """
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.rsplit(",", 1)[-1].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=client_key)


def _logging_rate_limit_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """Log the blocked request, then defer to slowapi's default 429 response.

    slowapi's default handler is otherwise silent, so per-IP rate-limit blocks
    (scraping / brute-force probes) leave no trace in the log stream. The
    ``event`` field keys the auth/abuse-spike monitor (see docs/observability.md).
    """
    log.warning(
        "rate limit exceeded: path=%s",
        request.url.path,
        extra={"event": LOG_EVENT_RATE_LIMIT_BLOCK, "path": request.url.path},
    )
    return _rate_limit_exceeded_handler(request, exc)


rate_limit_exceeded_handler = cast(ExceptionHandler, _logging_rate_limit_handler)
