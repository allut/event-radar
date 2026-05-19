"""Daily 5 digest email — HTML build + Resend delivery."""
from __future__ import annotations

import html as html_lib
import http
import logging
from datetime import date, datetime
from typing import Sequence

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import (
    DIGEST_MAX_WHY_GO_BULLETS,
    RESEND_ERROR_SNIPPET_LEN,
    RESEND_SEND_URL,
    RESEND_TIMEOUT_SECONDS,
    TALLINN_TZ,
)
from app.i18n import day_name, month_name, t, ti
from app.models.models import DailyFeed, Event, User
from app.routers.utils import resolve_why_go, select_events_with_classification

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


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_CSS = """
body{margin:0;padding:0;background:#0d0d0d;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;color:#e8e2d5;}
.wrap{max-width:600px;margin:0 auto;padding:32px 20px;}
h1{font-size:13px;letter-spacing:3px;text-transform:uppercase;color:#8b7d6b;margin:0 0 4px 0;}
h2{font-size:22px;font-weight:400;color:#e8e2d5;margin:0 0 32px 0;}
.event{border-top:1px solid #2a2522;padding:20px 0;}
.event-title{font-size:18px;font-weight:600;color:#e8e2d5;margin:0 0 4px 0;text-decoration:none;}
.event-title:hover{color:#c9a96e;}
.event-meta{font-size:12px;color:#8b7d6b;margin:0 0 10px 0;}
.bullets{margin:0;padding:0 0 0 16px;color:#c4bdb5;font-size:14px;line-height:1.7;}
.price{font-size:12px;color:#8b7d6b;margin:4px 0 0 0;}
.footer{margin-top:40px;padding-top:20px;border-top:1px solid #2a2522;font-size:11px;color:#5a4f47;text-align:center;}
.footer a{color:#8b7d6b;}
"""


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
        time_str = _format_event_time(event.starts_at, locale)
        venue_str = html_lib.escape(event.venue_name or "")
        meta = f"{time_str} · {venue_str}" if venue_str else time_str

        if event.price_min is not None:
            price_val = float(event.price_min)
            if price_val == 0:
                price_str = t("digest.price_free", locale)
            else:
                amount = f"{price_val:.2f}".rstrip("0").rstrip(".")
                price_str = ti("digest.price_from", locale, amount=amount)
        else:
            price_str = ""

        safe_title = html_lib.escape(event.title_orig)
        title_link = (
            f'<a href="{frontend_url}/events/{event.id}" class="event-title">'
            f"{safe_title}</a>"
        )
        bullet_html = "".join(f"<li>{html_lib.escape(b)}</li>" for b in bullets)
        price_html = f'<p class="price">{price_str}</p>' if price_str else ""
        event_blocks.append(
            f'<div class="event">'
            f"<p>{title_link}</p>"
            f'<p class="event-meta">{meta}</p>'
            f'<ul class="bullets">{bullet_html}</ul>'
            f"{price_html}"
            f"</div>"
        )

    events_html = "\n".join(event_blocks) if event_blocks else f"<p>{t('digest.no_events', locale)}</p>"
    settings_label = t("digest.unsubscribe", locale)

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>{_CSS}</style></head>
<body><div class="wrap">
<h1>{subject_label}</h1>
<h2>{date_str}</h2>
{events_html}
<div class="footer">
  <a href="{unsubscribe_url}">{settings_label}</a>
  &nbsp;·&nbsp; Event Radar, Tallinn
</div>
</div></body></html>"""


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
        log.warning("RESEND_API_KEY not set — digest NOT sent to %s", to_email)
        return

    html = build_digest_html(events, feed_date, locale, settings.FRONTEND_URL)
    subject = ti("digest.subject_template", locale, date=_format_feed_date(feed_date, locale))

    async with httpx.AsyncClient(timeout=RESEND_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            RESEND_SEND_URL,
            headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
            json={
                "from": settings.RESEND_FROM_ADDRESS,
                "to": [to_email],
                "subject": subject,
                "html": html,
            },
        )

    if resp.status_code not in (http.HTTPStatus.OK, http.HTTPStatus.CREATED):
        log.error(
            "Resend digest error for %s: %s %s",
            to_email,
            resp.status_code,
            resp.text[:RESEND_ERROR_SNIPPET_LEN],
        )
        raise RuntimeError(f"Resend returned {resp.status_code} for digest to {to_email}")
    log.info("Digest sent to %s (%d events)", to_email, len(events))


# ---------------------------------------------------------------------------
# Batch sender — queries DB, sends to all opted-in users
# ---------------------------------------------------------------------------


async def send_daily_digests(db: AsyncSession) -> dict[str, int]:
    """
    Send today's Daily 5 digest to all opted-in users.
    Runs at 07:00 Europe/Tallinn (one hour after build_daily_feeds).
    Returns summary dict for logging.
    """
    today = datetime.now(TALLINN_TZ).date()

    users = (await db.scalars(
        select(User).where(User.email_digest_opt_in.is_(True))
    )).all()

    if not users:
        return {"sent": 0, "skipped": 0, "total_opted_in": 0}

    user_ids = [u.id for u in users]

    feeds = (await db.scalars(
        select(DailyFeed).where(
            DailyFeed.user_id.in_(user_ids),
            DailyFeed.feed_date == today,
        )
    )).all()

    feed_by_user: dict[int, list[int]] = {f.user_id: f.event_ids for f in feeds}

    all_event_ids: set[int] = set()
    for eids in feed_by_user.values():
        all_event_ids.update(eids)

    if not all_event_ids:
        return {"sent": 0, "skipped": len(users), "total_opted_in": len(users)}

    events = (await db.scalars(
        select_events_with_classification().where(Event.id.in_(all_event_ids))
    )).all()
    event_map: dict[int, Event] = {e.id: e for e in events}

    user_map: dict[int, User] = {u.id: u for u in users}
    sent = skipped = 0

    for uid, eids in feed_by_user.items():
        user = user_map.get(uid)
        if not user:
            continue
        ordered_events = [event_map[eid] for eid in eids if eid in event_map]
        if not ordered_events:
            skipped += 1
            continue
        try:
            await send_digest_email(user.email, user.locale, ordered_events, today)
            sent += 1
        except Exception:
            log.exception("Failed to send digest to user %d", uid)
            skipped += 1

    return {"sent": sent, "skipped": skipped, "total_opted_in": len(users)}
