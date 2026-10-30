"""Organizer emails for a Promotion an admin ended early or voided (#601).

Each carries the admin's reason, which is the P2B statement of reasons, in the
Organizer's locale. Reuses the claim-resolution shell: an intro, the reason as
the note, and a dashboard button.
"""

from datetime import date

import httpx

from app.email.claim_resolution import (
    build_resolution_html,
    build_resolution_text,
    send_resolution_email,
)
from app.i18n import t, ti


async def _send_notice(
    key: str,
    to_email: str,
    event_title: str,
    start: date,
    end: date,
    reason: str,
    locale: str,
    http_client: httpx.AsyncClient | None,
    log_label: str,
) -> None:
    intro = ti(
        f"{key}.intro",
        locale,
        event_title=event_title,
        start=start.isoformat(),
        end=end.isoformat(),
    )
    await send_resolution_email(
        to_email,
        t(f"{key}.subject", locale),
        build_resolution_html(subject_key=key, intro=intro, note=reason, locale=locale),
        build_resolution_text(intro=intro, note=reason),
        http_client,
        log_label,
    )


async def send_promotion_ended_email(
    to_email: str,
    event_title: str,
    start: date,
    end: date,
    reason: str,
    locale: str,
    http_client: httpx.AsyncClient | None = None,
) -> None:
    await _send_notice(
        "email.promotion_ended", to_email, event_title, start, end, reason, locale,
        http_client, "promotion-ended",
    )


async def send_promotion_void_email(
    to_email: str,
    event_title: str,
    start: date,
    end: date,
    reason: str,
    locale: str,
    http_client: httpx.AsyncClient | None = None,
) -> None:
    await _send_notice(
        "email.promotion_void", to_email, event_title, start, end, reason, locale,
        http_client, "promotion-void",
    )


async def send_promotion_request_declined_email(
    to_email: str,
    event_title: str,
    start: date,
    end: date,
    reason: str,
    locale: str,
    http_client: httpx.AsyncClient | None = None,
) -> None:
    await _send_notice(
        "email.promotion_request_declined", to_email, event_title, start, end, reason,
        locale, http_client, "promotion-request-declined",
    )


async def send_promotion_late_refund_email(
    to_email: str,
    event_title: str,
    start: date,
    end: date,
    reason: str,
    locale: str,
    http_client: httpx.AsyncClient | None = None,
) -> None:
    await _send_notice(
        "email.promotion_late_refund", to_email, event_title, start, end, reason, locale,
        http_client, "promotion-late-refund",
    )
