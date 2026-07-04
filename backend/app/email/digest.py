"""Daily 5 digest email — HTML build + Resend delivery."""

from __future__ import annotations

import asyncio
import html as html_lib
import logging
from collections.abc import Sequence
from datetime import date, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import (
    DIGEST_MAX_WHY_GO_BULLETS,
    DIGEST_SEND_CONCURRENCY,
    RESEND_ERROR_SNIPPET_LEN,
    RESEND_SEND_URL,
    RESEND_TIMEOUT_SECONDS,
    TALLINN_TZ,
)
from app.email import styles
from app.email.styles import DIGEST_CSS
from app.email.templates import (
    DIGEST_DOCUMENT,
    EVENT_BLOCK,
    EVENT_BULLET,
    EVENT_IMAGE,
    EVENT_IMAGE_BAND,
    EVENT_PRICE_PILL,
    EVENT_TICKETS_ROW,
    EVENT_TITLE_LINK,
    EVENT_VENUE,
)
from app.i18n import day_name, month_name, t, ti
from app.ingestion.base import http_post
from app.models.models import DailyFeed, Event, User
from app.routers.utils import (
    mask_email,
    resolve_title,
    resolve_why_go,
    select_events_with_classification,
)

log = logging.getLogger(__name__)


def _format_feed_date(d: date, locale: str) -> str:
    dow = d.weekday()  # 0=Mon
    # Grammar differs per locale; the order of day/month/day-number is not key→string.
    if locale == "et":
        return f"{day_name(dow, locale)}, {d.day}. {month_name(d.month, locale)}"
    if locale == "ru":
        return f"{day_name(dow, locale)}, {d.day} {month_name(d.month, locale)}"
    return f"{day_name(dow, locale)}, {month_name(d.month, locale)} {d.day}"


def _format_event_time(starts_at: datetime, locale: str) -> str:
    local = starts_at.astimezone(TALLINN_TZ)
    day_str = _format_feed_date(local.date(), locale)
    return f"{day_str}, {local.strftime('%H:%M')}"


def build_digest_html(
    events: Sequence[Event],
    feed_date: date,
    locale: str,
    frontend_url: str,
) -> str:
    date_str = _format_feed_date(feed_date, locale)
    subject_label = t("digest.subject_label", locale)
    unsubscribe_url = f"{frontend_url}/settings"

    event_blocks: list[str] = []
    for event in events:
        cl = event.classification
        bullets = resolve_why_go(cl, locale)[:DIGEST_MAX_WHY_GO_BULLETS]
        time_str = html_lib.escape(_format_event_time(event.starts_at, locale))
        event_href = f"{frontend_url}/events/{event.id}"

        venue_str = html_lib.escape(event.venue_name or "")
        venue_html = (
            EVENT_VENUE.format(s_venue=styles.S_VENUE, venue=venue_str)
            if venue_str
            else ""
        )

        if event.price_min is not None:
            price_val = float(event.price_min)
            price_max_val = float(event.price_max) if event.price_max is not None else None
            if price_val == 0:
                if price_max_val is not None and price_max_val > 0:
                    max_amount = f"{price_max_val:.2f}".rstrip("0").rstrip(".")
                    price_str = ti("digest.price_free_with_paid", locale, amount=max_amount)
                else:
                    price_str = t("digest.price_free", locale)
            else:
                amount = f"{price_val:.2f}".rstrip("0").rstrip(".")
                price_str = ti("digest.price_from", locale, amount=amount)
                if event.has_free_tier:
                    price_str = f"{price_str} · {t('digest.price_free_options', locale)}"
        else:
            price_str = ""
        price_html = (
            EVENT_PRICE_PILL.format(s_price_pill=styles.S_PRICE_PILL, price=price_str)
            if price_str
            else ""
        )

        if event.image_url:
            image_html = EVENT_IMAGE.format(
                event_href=event_href,
                image_url=html_lib.escape(event.image_url, quote=True),
                title=html_lib.escape(resolve_title(event, locale)),
                s_img=styles.S_IMG,
            )
        else:
            category = (cl.categories[0] if cl and cl.categories else "event").replace("_", " ")
            image_html = EVENT_IMAGE_BAND.format(
                event_href=event_href,
                s_band=styles.S_BAND,
                s_band_diamond=styles.S_BAND_DIAMOND,
                s_band_category=styles.S_BAND_CATEGORY,
                category=html_lib.escape(category.upper()),
            )

        safe_title = html_lib.escape(resolve_title(event, locale))
        title_link = EVENT_TITLE_LINK.format(
            href=event_href, title=safe_title, s_title_link=styles.S_TITLE_LINK
        )
        bullets_html = "".join(
            EVENT_BULLET.format(
                text=html_lib.escape(b),
                s_bullet_row=styles.S_BULLET_ROW,
                s_diamond=styles.S_DIAMOND,
            )
            for b in bullets
        )
        tickets_row_html = (
            EVENT_TICKETS_ROW.format(
                s_footer_row=styles.S_FOOTER_ROW,
                s_tickets_link=styles.S_TICKETS_LINK,
                href=html_lib.escape(event.url, quote=True),
                label=t("digest.tickets", locale),
            )
            if event.url
            else ""
        )

        event_blocks.append(
            EVENT_BLOCK.format(
                s_card_wrap=styles.S_CARD_WRAP,
                s_card=styles.S_CARD,
                image_html=image_html,
                s_body=styles.S_BODY,
                s_meta=styles.S_META,
                s_time=styles.S_TIME,
                time_str=time_str,
                venue_html=venue_html,
                price_html=price_html,
                title_link=title_link,
                bullets_html=bullets_html,
                tickets_row_html=tickets_row_html,
            )
        )

    events_html = (
        "\n".join(event_blocks)
        if event_blocks
        else f"<p>{t('digest.no_events', locale)}</p>"
    )
    settings_label = t("digest.unsubscribe", locale)

    return DIGEST_DOCUMENT.format(
        css=DIGEST_CSS,
        s_page=styles.S_PAGE,
        s_container=styles.S_CONTAINER,
        s_header_pad=styles.S_HEADER_PAD,
        s_eyebrow=styles.S_EYEBROW,
        s_h1=styles.S_H1,
        subject_label=subject_label,
        date_str=date_str,
        s_date=styles.S_DATE,
        s_feed_btn_wrap=styles.S_FEED_BTN_WRAP,
        s_feed_btn=styles.S_FEED_BTN,
        feed_url=frontend_url,
        open_feed_label=t("digest.open_feed", locale),
        s_events_pad=styles.S_EVENTS_PAD,
        events_html=events_html,
        s_footer=styles.S_FOOTER,
        s_footer_link=styles.S_FOOTER_LINK,
        unsubscribe_url=unsubscribe_url,
        settings_label=settings_label,
    )


# ---------------------------------------------------------------------------
# Send one digest email
# ---------------------------------------------------------------------------


async def send_digest_email(
    to_email: str,
    locale: str,
    events: Sequence[Event],
    feed_date: date,
) -> None:
    if not settings.RESEND_API_KEY:
        log.warning(
            "RESEND_API_KEY not set — digest NOT sent to %s", mask_email(to_email)
        )
        return

    html = build_digest_html(events, feed_date, locale, settings.FRONTEND_URL)
    subject = ti(
        "digest.subject_template", locale, date=_format_feed_date(feed_date, locale)
    )

    async with httpx.AsyncClient(timeout=RESEND_TIMEOUT_SECONDS) as client:
        try:
            await http_post(
                client,
                RESEND_SEND_URL,
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                json_body={
                    "from": settings.RESEND_FROM_ADDRESS,
                    "to": [to_email],
                    "subject": subject,
                    "html": html,
                },
            )
        except httpx.HTTPStatusError as exc:
            log.error(
                "Resend digest error for %s: %s %s",
                mask_email(to_email),
                exc.response.status_code,
                exc.response.text[:RESEND_ERROR_SNIPPET_LEN],
            )
            raise RuntimeError(
                f"Resend returned {exc.response.status_code} for digest to {mask_email(to_email)}"
            ) from exc
    log.info("Digest sent to %s (%d events)", mask_email(to_email), len(events))


# ---------------------------------------------------------------------------
# Batch sender — queries DB, sends to all opted-in users
# ---------------------------------------------------------------------------


async def send_daily_digests(
    db: AsyncSession, *, dry_run: bool = False
) -> dict[str, int]:
    """
    Send today's Daily 5 digest to all opted-in users.
    Runs at 07:00 Europe/Tallinn (one hour after build_daily_feeds).
    Returns summary dict for logging.
    """
    today = datetime.now(TALLINN_TZ).date()

    users = (
        await db.scalars(select(User).where(User.email_digest_opt_in.is_(True)))
    ).all()

    if not users:
        return {"sent": 0, "skipped": 0, "total_opted_in": 0, "dry_run": dry_run}

    user_ids = [u.id for u in users]

    feeds = (
        await db.scalars(
            select(DailyFeed).where(
                DailyFeed.user_id.in_(user_ids),
                DailyFeed.feed_date == today,
            )
        )
    ).all()

    feed_by_user: dict[int, list[int]] = {f.user_id: f.event_ids for f in feeds}

    all_event_ids: set[int] = set()
    for eids in feed_by_user.values():
        all_event_ids.update(eids)

    if not all_event_ids:
        return {
            "sent": 0,
            "skipped": len(users),
            "total_opted_in": len(users),
            "dry_run": dry_run,
        }

    events = (
        await db.scalars(
            select_events_with_classification().where(
                Event.id.in_(all_event_ids),
                Event.is_explicit.is_(False),
                Event.is_non_event.is_(False),
            )
        )
    ).all()
    event_map: dict[int, Event] = {e.id: e for e in events}

    user_map: dict[int, User] = {u.id: u for u in users}
    semaphore = asyncio.Semaphore(DIGEST_SEND_CONCURRENCY)

    async def _send_one(uid: int, eids: list[int]) -> str:
        """Returns 'sent' | 'skipped'."""
        user = user_map.get(uid)
        if not user:
            return "skipped"
        ordered_events = [event_map[eid] for eid in eids if eid in event_map]
        if not ordered_events:
            return "skipped"
        if dry_run:
            return "sent"
        async with semaphore:
            try:
                await send_digest_email(
                    user.email, user.locale, ordered_events, today
                )
                return "sent"
            except Exception:
                log.exception("Failed to send digest to user %d", uid)
                return "skipped"

    # return_exceptions=True is defence-in-depth: _send_one already catches
    # every send error and returns "skipped", but a programming error inside
    # the wrapper itself would otherwise abort the whole batch.
    results = await asyncio.gather(
        *(_send_one(uid, eids) for uid, eids in feed_by_user.items()),
        return_exceptions=True,
    )
    sent = sum(1 for r in results if r == "sent")
    errored = sum(1 for r in results if isinstance(r, Exception))
    skipped = len(results) - sent - errored
    for r in results:
        if isinstance(r, Exception):
            log.error("digest fanout coroutine raised", exc_info=r)

    return {
        "sent": sent,
        "skipped": skipped,
        "errored": errored,
        "total_opted_in": len(users),
        "dry_run": dry_run,
    }
