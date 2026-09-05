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

from app.auth.tokens import generate_unsubscribe_token
from app.config import settings
from app.constants import (
    AUTHORIZATION_HEADER,
    BEARER_PREFIX,
    DIGEST_MAX_WHY_GO_BULLETS,
    DIGEST_RESULT_SENT,
    DIGEST_RESULT_SKIPPED,
    DIGEST_SEND_CONCURRENCY,
    FEED_BUILD_USER_BATCH_SIZE,
    LOCALE_ET,
    LOCALE_RU,
    LOG_EVENT_EMAIL_SEND_FAILED,
    RESEND_ERROR_SNIPPET_LEN,
    RESEND_SEND_URL,
    RESEND_TIMEOUT_SECONDS,
    TALLINN_TZ,
)
from app.email.styles import EmailStyles, get_email_styles
from app.email.templates import (
    DIGEST_EMPTY_STATE,
    DIGEST_FOOTER,
    DIGEST_HEADER,
    EMAIL_DOCUMENT,
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
from app.ingestion.http_client import http_post
from app.models.models import DailyFeed, Event, User
from app.routers.utils import (
    mask_email,
    public_event_filter,
    resolve_title,
    resolve_venue_name,
    resolve_why_go,
    select_events_with_classification,
)

log = logging.getLogger(__name__)


def _format_feed_date(d: date, locale: str) -> str:
    dow = d.weekday()  # 0=Mon
    # Grammar differs per locale; the order of day/month/day-number is not key→string.
    if locale == LOCALE_ET:
        return f"{day_name(dow, locale)}, {d.day}. {month_name(d.month, locale)}"
    if locale == LOCALE_RU:
        return f"{day_name(dow, locale)}, {d.day} {month_name(d.month, locale)}"
    return f"{day_name(dow, locale)}, {month_name(d.month, locale)} {d.day}"


def _format_event_time(starts_at: datetime, locale: str) -> str:
    local = starts_at.astimezone(TALLINN_TZ)
    day_str = _format_feed_date(local.date(), locale)
    return f"{day_str}, {local.strftime('%H:%M')}"


def _format_price_pill(event: Event, locale: str) -> str:
    """Human price label: free / free-with-paid-tiers / from-X (+ free options)."""
    if event.price_min is None:
        return ""
    price_val = float(event.price_min)
    price_max_val = float(event.price_max) if event.price_max is not None else None
    if price_val == 0:
        if price_max_val is not None and price_max_val > 0:
            max_amount = f"{price_max_val:.2f}".rstrip("0").rstrip(".")
            return ti("digest.price_free_with_paid", locale, amount=max_amount)
        return t("digest.price_free", locale)
    amount = f"{price_val:.2f}".rstrip("0").rstrip(".")
    price_str = ti("digest.price_from", locale, amount=amount)
    if event.has_free_tier:
        price_str = f"{price_str} · {t('digest.price_free_options', locale)}"
    return price_str


def _build_event_block(
    event: Event, locale: str, frontend_url: str, s: EmailStyles
) -> str:
    """Render one event card (time/venue/price, image or band, title, bullets)."""
    cl = event.classification
    bullets = resolve_why_go(cl, locale)[:DIGEST_MAX_WHY_GO_BULLETS]
    time_str = html_lib.escape(_format_event_time(event.starts_at, locale))
    event_href = f"{frontend_url}/events/{event.id}"

    venue_str = html_lib.escape(resolve_venue_name(event, locale) or "")
    venue_html = (
        EVENT_VENUE.format(s_venue=s.s_venue, venue=venue_str) if venue_str else ""
    )

    price_str = _format_price_pill(event, locale)
    price_html = (
        EVENT_PRICE_PILL.format(s_price_pill=s.s_price_pill, price=price_str)
        if price_str
        else ""
    )

    if event.image_url:
        image_html = EVENT_IMAGE.format(
            event_href=event_href,
            image_url=html_lib.escape(event.image_url, quote=True),
            title=html_lib.escape(resolve_title(event, locale)),
            s_img=s.s_img,
        )
    else:
        category = (cl.categories[0] if cl and cl.categories else "event").replace("_", " ")
        image_html = EVENT_IMAGE_BAND.format(
            event_href=event_href,
            s_band=s.s_band,
            s_band_diamond=s.s_band_diamond,
            s_band_category=s.s_band_category,
            category=html_lib.escape(category.upper()),
        )

    safe_title = html_lib.escape(resolve_title(event, locale))
    title_link = EVENT_TITLE_LINK.format(
        href=event_href, title=safe_title, s_title_link=s.s_title_link
    )
    bullets_html = "".join(
        EVENT_BULLET.format(
            text=html_lib.escape(b),
            s_bullet_row=s.s_bullet_row,
            s_diamond=s.s_diamond,
        )
        for b in bullets
    )
    tickets_row_html = (
        EVENT_TICKETS_ROW.format(
            s_footer_row=s.s_footer_row,
            s_tickets_link=s.s_tickets_link,
            href=html_lib.escape(event.url, quote=True),
            label=t("digest.tickets", locale),
        )
        if event.url
        else ""
    )

    return EVENT_BLOCK.format(
        s_card_wrap=s.s_card_wrap,
        s_card=s.s_card,
        image_html=image_html,
        s_body=s.s_body,
        s_meta=s.s_meta,
        s_time=s.s_time,
        time_str=time_str,
        venue_html=venue_html,
        price_html=price_html,
        title_link=title_link,
        bullets_html=bullets_html,
        tickets_row_html=tickets_row_html,
    )


def build_digest_html(
    events: Sequence[Event],
    feed_date: date,
    locale: str,
    frontend_url: str,
    unsubscribe_url: str | None = None,
    theme_preference: str | None = None,
) -> str:
    s = get_email_styles(theme_preference)
    date_str = _format_feed_date(feed_date, locale)
    subject_label = t("digest.subject_label", locale)
    if unsubscribe_url is None:
        unsubscribe_url = f"{frontend_url}/settings"

    event_blocks = [_build_event_block(e, locale, frontend_url, s) for e in events]
    events_html = (
        "\n".join(event_blocks)
        if event_blocks
        else DIGEST_EMPTY_STATE.format(text=t("digest.no_events", locale))
    )
    settings_label = t("digest.unsubscribe", locale)

    header_html = DIGEST_HEADER.format(
        s_eyebrow=s.s_eyebrow,
        s_h1=s.s_h1,
        subject_label=subject_label,
        date_str=date_str,
        s_date=s.s_date,
        s_feed_btn_wrap=s.s_feed_btn_wrap,
        s_feed_btn=s.s_feed_btn,
        feed_url=frontend_url,
        open_feed_label=t("digest.open_feed", locale),
    )
    footer_html = DIGEST_FOOTER.format(
        unsubscribe_url=unsubscribe_url,
        s_footer_link=s.s_footer_link,
        settings_label=settings_label,
    )

    return EMAIL_DOCUMENT.format(
        css=s.css,
        s_page=s.s_page,
        s_container=s.s_container,
        s_header_pad=s.s_header_pad,
        header_html=header_html,
        s_content_pad=s.s_content_pad,
        content_html=events_html,
        s_footer=s.s_footer,
        footer_html=footer_html,
    )


# ---------------------------------------------------------------------------
# Send one digest email
# ---------------------------------------------------------------------------


async def send_digest_email(
    to_email: str,
    locale: str,
    events: Sequence[Event],
    feed_date: date,
    user_id: int,
    theme_preference: str | None = None,
) -> None:
    if not settings.RESEND_API_KEY:
        log.warning(
            "RESEND_API_KEY not set — digest NOT sent to %s", mask_email(to_email)
        )
        return

    unsubscribe_token = generate_unsubscribe_token(user_id)
    unsubscribe_url = f"{settings.FRONTEND_URL}/unsubscribe?token={unsubscribe_token}"
    header_url = f"{settings.BACKEND_URL}/email/unsubscribe?token={unsubscribe_token}"

    html = build_digest_html(
        events,
        feed_date,
        locale,
        settings.FRONTEND_URL,
        unsubscribe_url,
        theme_preference,
    )
    subject = ti(
        "digest.subject_template", locale, date=_format_feed_date(feed_date, locale)
    )

    async with httpx.AsyncClient(timeout=RESEND_TIMEOUT_SECONDS) as client:
        try:
            await http_post(
                client,
                RESEND_SEND_URL,
                headers={
                    AUTHORIZATION_HEADER: f"{BEARER_PREFIX}{settings.RESEND_API_KEY}"
                },
                json_body={
                    "from": settings.RESEND_FROM_ADDRESS,
                    "to": [to_email],
                    "subject": subject,
                    "html": html,
                    "headers": {
                        "List-Unsubscribe": f"<{header_url}>",
                        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                    },
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


async def _load_digest_data(
    db: AsyncSession, today: date, user_ids: list[int]
) -> tuple[dict[int, list[int]], dict[int, Event] | None]:
    """Today's feeds per user + the events they reference, in two bulk queries.

    event_map is None when no user has any feed events today (caller
    short-circuits to all-skipped).
    """
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
        return feed_by_user, None

    events = (
        await db.scalars(
            select_events_with_classification().where(
                Event.id.in_(all_event_ids),
                public_event_filter(),
            )
        )
    ).all()
    return feed_by_user, {e.id: e for e in events}


async def send_daily_digests(
    db: AsyncSession, *, dry_run: bool = False
) -> dict[str, int]:
    """
    Send today's Daily 5 digest to all opted-in users.
    Runs at 07:00 Europe/Tallinn (one hour after build_daily_feeds).

    Pages the opted-in population at FEED_BUILD_USER_BATCH_SIZE, mirroring
    build_daily_feeds — memory is bounded by a batch size (feeds + their
    referenced events + in-flight send coroutines) instead of by the total
    opted-in count. DIGEST_SEND_CONCURRENCY bounds in-flight HTTP across the
    whole run via one shared semaphore, not per page.

    Returns summary dict for logging.
    """
    today = datetime.now(TALLINN_TZ).date()

    users = (
        await db.scalars(
            select(User).where(
                User.email_digest_opt_in.is_(True),
                User.email_verified.is_(True),
            )
        )
    ).all()

    if not users:
        return {
            DIGEST_RESULT_SENT: 0,
            DIGEST_RESULT_SKIPPED: 0,
            "errored": 0,
            "total_opted_in": 0,
            "dry_run": dry_run,
        }

    semaphore = asyncio.Semaphore(DIGEST_SEND_CONCURRENCY)
    sent = errored = 0
    user_map: dict[int, User] = {u.id: u for u in users}

    async def _send_one(user: User, eids: list[int], event_map: dict[int, Event]) -> str:
        """Returns 'sent' | 'skipped'."""
        ordered_events = [event_map[eid] for eid in eids if eid in event_map]
        if not ordered_events:
            return DIGEST_RESULT_SKIPPED
        if dry_run:
            return DIGEST_RESULT_SENT
        async with semaphore:
            try:
                await send_digest_email(
                    user.email,
                    user.locale,
                    ordered_events,
                    today,
                    user.id,
                    user.theme_preference,
                )
                return DIGEST_RESULT_SENT
            except Exception:
                log.exception(
                    "Failed to send digest to user %d",
                    user.id,
                    extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
                )
                return DIGEST_RESULT_SKIPPED

    for i in range(0, len(users), FEED_BUILD_USER_BATCH_SIZE):
        page_ids = [u.id for u in users[i : i + FEED_BUILD_USER_BATCH_SIZE]]

        feed_by_user, event_map = await _load_digest_data(db, today, page_ids)
        if event_map is None:
            continue

        # return_exceptions=True is defence-in-depth: _send_one already catches
        # every send error and returns "skipped", but a programming error inside
        # the wrapper itself would otherwise abort the whole page's batch.
        results = await asyncio.gather(
            *(
                _send_one(user_map[uid], eids, event_map)
                for uid, eids in feed_by_user.items()
            ),
            return_exceptions=True,
        )
        sent += sum(1 for r in results if r == DIGEST_RESULT_SENT)
        errored += sum(1 for r in results if isinstance(r, Exception))
        for r in results:
            if isinstance(r, Exception):
                log.error(
                    "digest fanout coroutine raised",
                    exc_info=r,
                    extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
                )

    skipped = len(users) - sent - errored

    return {
        DIGEST_RESULT_SENT: sent,
        DIGEST_RESULT_SKIPPED: skipped,
        "errored": errored,
        "total_opted_in": len(users),
        "dry_run": dry_run,
    }
