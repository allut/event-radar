"""Daily 5 digest email — HTML build + Resend delivery."""

from __future__ import annotations

import asyncio
import html as html_lib
import logging
from collections.abc import Sequence
from contextlib import nullcontext
from datetime import date, datetime
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import generate_ads_off_token, generate_unsubscribe_token
from app.config import settings
from app.constants.core import (
    ADS_OFF_PATH,
    EVENTS_PATH,
    HOME_PATH,
    LOCALE_ET,
    SETTINGS_PATH,
    TALLINN_TZ,
    UNSUBSCRIBE_PATH,
)
from app.constants.email import (
    DIGEST_CATEGORY_FALLBACK,
    DIGEST_MAX_WHY_GO_BULLETS,
    DIGEST_RESULT_SENT,
    DIGEST_RESULT_SKIPPED,
    DIGEST_SEND_CONCURRENCY,
    HEADER_LIST_UNSUBSCRIBE,
    HEADER_LIST_UNSUBSCRIBE_POST,
    LIST_UNSUBSCRIBE_ONE_CLICK,
    RESEND_ERROR_SNIPPET_LEN,
    RESEND_SEND_URL,
)
from app.constants.http import AUTHORIZATION_HEADER, BEARER_PREFIX
from app.constants.log_events import LOG_EVENT_EMAIL_SEND_FAILED
from app._generated.shared_constants import LOCALE_RU, PROMOTION_REF_DIGEST_AD
from app.constants.promotions import PROMOTION_STAT_DIGEST_SENT
from app.constants.ranking import DAILY_5_COUNT, FEED_BUILD_USER_BATCH_SIZE
from app.email.links import frontend_url
from app.email.resend import resend_http_client
from app.email.brand import brand_mark_attachments, brand_mark_html
from app.email.styles import EmailStyles, get_email_styles
from app.ingestion.http_client import host_is_allowed, own_cloudinary_url, safe_render_url
from app.email.templates import (
    DIGEST_EMPTY_STATE,
    DIGEST_FOOTER,
    DIGEST_HEADER,
    DIGEST_SPONSORED_BLOCK,
    DIGEST_PRICE_SEPARATOR,
    DIGEST_TIME_FORMAT,
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
from app.promotions import counters
from app.promotions.digest_slot import DigestSlot, load_digest_slots
from app.events.localize import resolve_title, resolve_why_go
from app.events.queries import public_event_filter, select_events_with_classification
from app.events.venue import resolve_venue_name
from app.auth.utils import mask_email

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
    return f"{day_str}, {local.strftime(DIGEST_TIME_FORMAT)}"


def _format_amount(value: float) -> str:
    """Price amount without trailing zeros (``12.50`` -> ``12.5``, ``5.00`` -> ``5``)."""
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _format_price_pill(event: Event, locale: str) -> str:
    """Human price label: free / free-with-paid-tiers / from-X (+ free options)."""
    if event.price_min is None:
        return ""
    price_val = float(event.price_min)
    price_max_val = float(event.price_max) if event.price_max is not None else None
    if price_val == 0:
        if price_max_val is not None and price_max_val > 0:
            return ti(
                "digest.price_free_with_paid",
                locale,
                amount=_format_amount(price_max_val),
            )
        return t("digest.price_free", locale)
    price_str = ti("digest.price_from", locale, amount=_format_amount(price_val))
    if event.has_free_tier:
        price_str = (
            f"{price_str}{DIGEST_PRICE_SEPARATOR}"
            f"{t('digest.price_free_options', locale)}"
        )
    return price_str


def _embeddable_image_url(image_url: str | None) -> str | None:
    """The URL to embed as the card's <img>, or None for the branded band.

    Only our own Cloudinary uploads and the scraped sources' hosts qualify. A
    claimant can pin any https image_url, and an <img> on a host they run
    would log every recipient's IP and open time (security audit, 2026-10)."""
    if own := own_cloudinary_url(image_url):
        return own
    safe = safe_render_url(image_url)
    if safe is not None and host_is_allowed(urlsplit(safe).hostname):
        return safe
    return None


def _build_event_block(
    event: Event,
    locale: str,
    frontend_base: str,
    s: EmailStyles,
    ref: str | None = None,
) -> str:
    """Render one event card (time/venue/price, image or band, title, bullets).
    ``ref`` is appended to the card's event links (the Sponsored slot's marker)."""
    cl = event.classification
    bullets = resolve_why_go(cl, locale)[:DIGEST_MAX_WHY_GO_BULLETS]
    time_str = html_lib.escape(_format_event_time(event.starts_at, locale))
    event_href = frontend_url(f"{EVENTS_PATH}/{event.id}", locale, frontend_base)
    if ref is not None:
        event_href = f"{event_href}?ref={ref}"

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

    image_url = _embeddable_image_url(event.image_url)
    if image_url:
        image_html = EVENT_IMAGE.format(
            event_href=event_href,
            image_url=html_lib.escape(image_url, quote=True),
            title=html_lib.escape(resolve_title(event, locale)),
            s_img=s.s_img,
        )
    else:
        category = (cl.categories[0] if cl and cl.categories else DIGEST_CATEGORY_FALLBACK).replace("_", " ")
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


# (event_id, locale) -> rendered card. A card is identical for every user who
# shares a locale, so send_daily_digests keeps one of these for its whole run
# instead of re-rendering each event once per recipient (Big-O audit #9).
EventBlockCache = dict[tuple[int, str], str]


def build_digest_html(
    events: Sequence[Event],
    feed_date: date,
    locale: str,
    frontend_base: str,
    unsubscribe_url: str | None = None,
    block_cache: EventBlockCache | None = None,
    sponsored: DigestSlot | None = None,
    ads_off_url: str | None = None,
) -> str:
    s = get_email_styles()
    date_str = _format_feed_date(feed_date, locale)
    subject_label = t("digest.subject_label", locale)
    if unsubscribe_url is None:
        unsubscribe_url = frontend_url(SETTINGS_PATH, locale, frontend_base)

    event_blocks: list[str] = []
    for e in events:
        cache_key = (e.id, locale)
        if block_cache is not None and cache_key in block_cache:
            event_blocks.append(block_cache[cache_key])
            continue
        block = _build_event_block(e, locale, frontend_base, s)
        if block_cache is not None:
            block_cache[cache_key] = block
        event_blocks.append(block)
    events_html = (
        "\n".join(event_blocks)
        if event_blocks
        else DIGEST_EMPTY_STATE.format(
            s_body_text=s.s_body_text, text=t("digest.no_events", locale)
        )
    )
    if sponsored is not None and event_blocks and ads_off_url is not None:
        events_html += DIGEST_SPONSORED_BLOCK.format(
            s_sponsor_wrap=s.s_sponsor_wrap,
            s_sponsor=s.s_sponsor,
            s_sponsor_head=s.s_sponsor_head,
            s_sponsor_label=s.s_sponsor_label,
            label=html_lib.escape(t("digest.ad_label", locale)),
            s_sponsor_org=s.s_sponsor_org,
            advertiser=html_lib.escape(
                ti("digest.ad_advertiser", locale, org=sponsored.advertiser)
            ),
            s_sponsor_body=s.s_sponsor_body,
            event_block=_build_event_block(
                sponsored.event, locale, frontend_base, s, PROMOTION_REF_DIGEST_AD
            ),
            s_sponsor_foot=s.s_sponsor_foot,
            s_sponsor_note=s.s_sponsor_note,
            explanation=html_lib.escape(
                ti("digest.ad_explain", locale, org=sponsored.advertiser)
            ),
            stop_url=html_lib.escape(ads_off_url, quote=True),
            s_sponsor_stop=s.s_sponsor_stop,
            stop_label=html_lib.escape(t("digest.ad_stop", locale)),
        )
    settings_label = t("digest.unsubscribe", locale)

    header_html = DIGEST_HEADER.format(
        brand_mark_html=brand_mark_html(s),
        s_eyebrow=s.s_eyebrow,
        s_h1=s.s_h1,
        subject_label=subject_label,
        date_str=date_str,
        s_date=s.s_date,
        s_feed_btn_wrap=s.s_feed_btn_wrap,
        s_feed_btn=s.s_feed_btn,
        feed_url=frontend_url(HOME_PATH, locale, frontend_base),
        open_feed_label=t("digest.open_feed", locale),
    )
    footer_html = DIGEST_FOOTER.format(
        unsubscribe_url=unsubscribe_url,
        s_footer_link=s.s_footer_link,
        settings_label=settings_label,
    )

    return EMAIL_DOCUMENT.format(
        css=s.css,
        color_scheme=s.color_scheme,
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
    *,
    http_client: httpx.AsyncClient | None = None,
    block_cache: EventBlockCache | None = None,
    sponsored: DigestSlot | None = None,
) -> None:
    if not settings.RESEND_API_KEY:
        log.warning(
            "RESEND_API_KEY not set — digest NOT sent to %s", mask_email(to_email)
        )
        return

    unsubscribe_token = generate_unsubscribe_token(user_id)
    unsubscribe_url = f"{frontend_url(UNSUBSCRIBE_PATH, locale)}?token={unsubscribe_token}"
    header_url = f"{settings.BACKEND_URL}/email/unsubscribe?token={unsubscribe_token}"

    ads_off_url = (
        f"{frontend_url(ADS_OFF_PATH, locale)}?token={generate_ads_off_token(user_id)}"
        if sponsored is not None
        else None
    )
    html = build_digest_html(
        events,
        feed_date,
        locale,
        settings.FRONTEND_URL,
        unsubscribe_url,
        block_cache,
        sponsored,
        ads_off_url,
    )
    subject = ti(
        "digest.subject_template", locale, date=_format_feed_date(feed_date, locale)
    )

    async def _send(client: httpx.AsyncClient) -> None:
        try:
            await http_post(
                client,
                RESEND_SEND_URL,
                headers={
                    AUTHORIZATION_HEADER: f"{BEARER_PREFIX}{settings.RESEND_API_KEY}"
                },
                json_body={
                    "from": settings.RESEND_FROM_ADDRESS,
                    "reply_to": settings.CONTACT_TO_ADDRESS,
                    "to": [to_email],
                    "subject": subject,
                    "html": html,
                    "attachments": brand_mark_attachments(html),
                    "headers": {
                        HEADER_LIST_UNSUBSCRIBE: f"<{header_url}>",
                        HEADER_LIST_UNSUBSCRIBE_POST: LIST_UNSUBSCRIBE_ONE_CLICK,
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

    if http_client is not None:
        await _send(http_client)
    else:
        async with resend_http_client() as client:
            await _send(client)
    if sponsored is not None:
        counters.bump(sponsored.promotion_id, feed_date, PROMOTION_STAT_DIGEST_SENT)
    log.info("Digest sent to %s (%d events)", mask_email(to_email), len(events))


# ---------------------------------------------------------------------------
# Batch sender — queries DB, sends to all opted-in users
# ---------------------------------------------------------------------------


async def _load_digest_data(
    db: AsyncSession,
    today: date,
    user_ids: list[int],
    event_cache: dict[int, Event] | None = None,
) -> tuple[dict[int, list[int]], dict[int, Event] | None]:
    """Today's feeds per user + the events they reference, in two bulk queries.

    ``event_cache`` is the run-scoped id -> Event memo: events an earlier page
    already loaded are not re-queried (every user's feed draws on the same
    small candidate pool, so later pages mostly hit it).

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

    if event_cache is None:
        event_cache = {}
    missing_ids = all_event_ids - event_cache.keys()
    if missing_ids:
        events = (
            await db.scalars(
                select_events_with_classification().where(
                    Event.id.in_(missing_ids),
                    public_event_filter(),
                )
            )
        ).all()
        event_cache.update({e.id: e for e in events})
    return feed_by_user, {
        eid: event_cache[eid] for eid in all_event_ids if eid in event_cache
    }


async def _load_page_slots(
    db: AsyncSession,
    user_map: dict[int, User],
    feed_by_user: dict[int, list[int]],
    event_map: dict[int, Event],
) -> dict[int, DigestSlot]:
    """The page's Sponsored slots: only users with Email ad consent and a full
    set of picks (#611). Nothing is queried while the slots flag is off."""
    if not settings.PROMOTIONS_SLOTS_ENABLED:
        return {}
    eligible = [
        uid
        for uid, eids in feed_by_user.items()
        if uid in user_map
        and user_map[uid].email_ad_consent
        and sum(1 for eid in eids if eid in event_map) >= DAILY_5_COUNT
    ]
    return await load_digest_slots(db, eligible, datetime.now(TALLINN_TZ))


async def send_daily_digests(
    db: AsyncSession, *, dry_run: bool = False
) -> dict[str, int]:
    """
    Send today's Daily 5 digest to all opted-in users.
    Runs daily at DIGEST_SEND_HOUR (after build_daily_feeds).

    Pages the opted-in population at FEED_BUILD_USER_BATCH_SIZE, mirroring
    build_daily_feeds — memory is bounded by a batch size (feeds + their
    referenced events + in-flight send coroutines) instead of by the total
    opted-in count. Only user ids are held for the full run; full User rows
    are hydrated one page at a time (Big-O audit #5, item 1.5 — the feeds and
    events were already paged, but the `users`/`user_map` collections weren't).
    DIGEST_SEND_CONCURRENCY bounds in-flight HTTP across the whole run via one
    shared semaphore, not per page.

    Returns summary dict for logging.
    """
    today = datetime.now(TALLINN_TZ).date()

    user_ids = list(
        (
            await db.scalars(
                select(User.id).where(
                    User.email_digest_opt_in == true(),
                    User.email_verified == true(),
                )
            )
        ).all()
    )

    if not user_ids:
        return {
            DIGEST_RESULT_SENT: 0,
            DIGEST_RESULT_SKIPPED: 0,
            "errored": 0,
            "total_opted_in": 0,
            "dry_run": dry_run,
        }

    semaphore = asyncio.Semaphore(DIGEST_SEND_CONCURRENCY)
    sent = errored = 0
    block_cache: EventBlockCache = {}
    event_cache: dict[int, Event] = {}

    async def _send_one(
        user: User,
        eids: list[int],
        event_map: dict[int, Event],
        http_client: httpx.AsyncClient | None,
        sponsored: DigestSlot | None,
    ) -> str:
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
                    http_client=http_client,
                    block_cache=block_cache,
                    sponsored=sponsored,
                )
                return DIGEST_RESULT_SENT
            except Exception:
                log.exception(
                    "Failed to send digest to user %d",
                    user.id,
                    extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
                )
                return DIGEST_RESULT_SKIPPED

    # One shared client for the whole run (Big-O audit M7) — dry runs never
    # send, so they skip opening a connection pool entirely.
    client_ctx = resend_http_client() if not dry_run else nullcontext(None)
    async with client_ctx as http_client:
        for i in range(0, len(user_ids), FEED_BUILD_USER_BATCH_SIZE):
            page_ids = user_ids[i : i + FEED_BUILD_USER_BATCH_SIZE]

            page_users = (
                await db.scalars(select(User).where(User.id.in_(page_ids)))
            ).all()
            user_map: dict[int, User] = {u.id: u for u in page_users}

            feed_by_user, event_map = await _load_digest_data(
                db, today, page_ids, event_cache
            )
            if event_map is None:
                continue

            slots = await _load_page_slots(db, user_map, feed_by_user, event_map)

            # return_exceptions=True is defence-in-depth: _send_one already catches
            # every send error and returns "skipped", but a programming error inside
            # the wrapper itself would otherwise abort the whole page's batch.
            results = await asyncio.gather(
                *(
                    _send_one(user_map[uid], eids, event_map, http_client, slots.get(uid))
                    for uid, eids in feed_by_user.items()
                    if uid in user_map
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

    total_opted_in = len(user_ids)
    skipped = total_opted_in - sent - errored

    return {
        DIGEST_RESULT_SENT: sent,
        DIGEST_RESULT_SKIPPED: skipped,
        "errored": errored,
        "total_opted_in": total_opted_in,
        "dry_run": dry_run,
    }
