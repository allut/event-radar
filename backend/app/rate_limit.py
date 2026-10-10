"""Shared per-IP rate limiter instance.

Lives in its own module (mirroring db.py's role for the engine/session) so that
both app.main (middleware/exception-handler wiring) and routers (per-endpoint
@limiter.limit decorators) can import it without a circular dependency.
"""

import ipaddress
import logging
import secrets
from typing import cast

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ExceptionHandler

from app.config import settings
from app.constants import (
    HEADER_X_CLIENT_IP,
    HEADER_X_EDGE_AUTH,
    HEADER_X_FORWARDED_FOR,
    LOG_EVENT_RATE_LIMIT_BLOCK,
    RATE_LIMIT_IPV6_PREFIX_LEN,
)

log = logging.getLogger(__name__)


def client_key(request: Request) -> str:
    """Rate-limit / audit-log key: the real client IP.

    Production topology is two hops — browser -> Cloudflare Pages Function
    proxy -> Render -> uvicorn (see frontend/functions/api/[[path]].ts and
    docs/security.md) — so the rightmost X-Forwarded-For entry Render's own
    proxy appends is always a Cloudflare egress address, not the visitor
    (OWASP audit G-1). The Cloudflare Function forwards the true client IP as
    X-Client-IP alongside X-Edge-Auth, a shared secret proving the header came
    from that Function and not directly from an onrender.com caller (who could
    otherwise forge X-Client-IP outright). Only trusted when both the secret
    is configured and the header matches it — a stray/absent header falls
    back to the rightmost-XFF heuristic below, which is still correct for the
    single Render hop when accessed directly.
    """
    edge_auth = request.headers.get(HEADER_X_EDGE_AUTH, "")
    if settings.EDGE_SHARED_SECRET and secrets.compare_digest(
        edge_auth, settings.EDGE_SHARED_SECRET
    ):
        client_ip = request.headers.get(HEADER_X_CLIENT_IP, "").strip()
        if client_ip:
            return _bucket_ip(client_ip)

    xff = request.headers.get(HEADER_X_FORWARDED_FOR, "")
    if xff:
        return _bucket_ip(xff.rsplit(",", 1)[-1].strip())
    return _bucket_ip(get_remote_address(request))


def _bucket_ip(raw: str) -> str:
    """Collapse an IPv6 address to its /64 prefix. A single subscriber is
    routinely handed a whole /64, so keying on the full address lets one client
    rotate through 2**64 "distinct" IPs and dodge every limit and the admin
    login lockout (OWASP audit L-10). IPv4-mapped IPv6 reverts to IPv4;
    anything unparseable is returned unchanged."""
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return raw
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        network = ipaddress.ip_network(f"{ip}/{RATE_LIMIT_IPV6_PREFIX_LEN}", strict=False)
        return str(network.network_address) + f"/{RATE_LIMIT_IPV6_PREFIX_LEN}"
    return str(ip)


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
