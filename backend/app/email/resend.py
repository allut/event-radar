"""Single-attempt Resend send shared by every request-path email sender.

Falls back to log-only when RESEND_API_KEY is unset (dev / CI).
"""

import logging

import httpx

from app.config import settings
from app.constants import (
    AUTHORIZATION_HEADER,
    BEARER_PREFIX,
    LOG_EVENT_EMAIL_SEND_FAILED,
    RESEND_ERROR_SNIPPET_LEN,
    RESEND_SEND_URL,
    RESEND_TIMEOUT_SECONDS,
)
from app.email.brand import brand_mark_attachments

log = logging.getLogger(__name__)


def resend_http_client() -> httpx.AsyncClient:
    """Build an ``httpx.AsyncClient`` for a fan-out caller to open once and
    reuse across all its sends (via ``send_resend_email``'s ``http_client``
    param), instead of a fresh connection pool + TLS handshake per email."""
    return httpx.AsyncClient(timeout=RESEND_TIMEOUT_SECONDS)


async def send_resend_email(
    payload: dict,
    *,
    http_client: httpx.AsyncClient | None = None,
    log_label: str,
    log_ref: str,
) -> None:
    """POST ``payload`` to Resend exactly once and log the outcome. ``payload``
    carries everything except ``from`` and the brand-mark attachment, which are
    added here. ``log_ref`` must already be PII-safe (``mask_email()`` for an
    address).

    Deliberately not routed through the retrying ``http_post``: these sends are
    awaited synchronously inside rate-limited, user-facing request handlers
    (magic link, contact form, report/claim notifications) — a 5-attempt
    exponential backoff on a Resend hiccup would stall the request up to ~150s
    instead of failing fast, and every caller already swallows the failure.
    The batch digest send in ``digest.py`` has a different policy and does use
    ``http_post``."""
    if not settings.RESEND_API_KEY:
        log.warning(
            "RESEND_API_KEY not set — %s NOT sent (%s)", log_label, log_ref
        )
        return

    headers = {AUTHORIZATION_HEADER: f"{BEARER_PREFIX}{settings.RESEND_API_KEY}"}
    body = {"from": settings.RESEND_FROM_ADDRESS, **payload}
    if attachments := brand_mark_attachments(payload.get("html", "")):
        body["attachments"] = attachments
    if http_client is not None:
        resp = await http_client.post(RESEND_SEND_URL, headers=headers, json=body)
    else:
        async with resend_http_client() as client:
            resp = await client.post(RESEND_SEND_URL, headers=headers, json=body)

    if resp.status_code not in (httpx.codes.OK, httpx.codes.CREATED):
        log.error(
            "Resend API error sending %s (%s): %s %s",
            log_label,
            log_ref,
            resp.status_code,
            resp.text[:RESEND_ERROR_SNIPPET_LEN],
            extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
        )
    else:
        log.info("%s sent (%s)", log_label, log_ref)
