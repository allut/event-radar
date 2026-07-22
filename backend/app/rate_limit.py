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

limiter = Limiter(key_func=get_remote_address)


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
