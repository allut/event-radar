"""Organizer-facing reads of Promotions (#614, #616): the promotable flag and
status badge on event rows, the unified requests-and-Promotions list, the
request form's context and the per-day report. Every read is bulk with a fixed
query count."""

from collections.abc import Sequence
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app._generated.shared_constants import (
    ORGANIZER_TERMS_VERSION,
    PROMOTION_DAY_PRICE_CENTS,
    PROMOTION_MAX_DAYS,
    PROMOTION_VAT_RATE_PERCENT,
)
from app.constants.promotions import (
    PROMOTION_GATE_OUTCOME_PAUSED,
    PROMOTION_GATE_OUTCOME_SHOWN,
    PROMOTION_HOLDING_STATUSES,
    PROMOTION_LIST_AWAITING_CHECKOUT,
    PROMOTION_LIST_AWAITING_PAYMENT,
    PROMOTION_LIST_CANCELLED,
    PROMOTION_LIST_DECLINED,
    PROMOTION_LIST_ENDED_EARLY,
    PROMOTION_LIST_FINISHED,
    PROMOTION_LIST_LIVE,
    PROMOTION_LIST_PAUSED,
    PROMOTION_LIST_REQUESTED,
    PROMOTION_LIST_SCHEDULED,
    PROMOTION_MIN_DAYS,
    PROMOTION_MIN_LEAD_DAYS,
    PROMOTION_REQUEST_STATUS_DECLINED,
    PROMOTION_REQUEST_STATUS_PENDING,
    PROMOTION_RESTRICTION_NONE,
    PROMOTION_STAT_DIGEST_OPENS,
    PROMOTION_STAT_DIGEST_SENT,
    PROMOTION_STAT_EXPLORE_SERVED,
    PROMOTION_STAT_DAILY5_PLACED,
    PROMOTION_STAT_WEB_OPENS,
    PROMOTION_STATE_FINISHED,
    PROMOTION_STATE_LIVE,
    PROMOTION_STATE_SCHEDULED,
    PROMOTION_STATUS_ENDED_EARLY,
    PROMOTION_STATUS_UNPAID,
    PROMOTION_STATUS_VOID,
    PROMOTION_UNAVAILABLE_HORIZON_DAYS,
)
from app.events.localize import resolve_title
from app.models.models import Event, Organizer, Promotion, PromotionRequest
from app.promotions.cap import full_days
from app.promotions.flags import checkout_enabled
from app.promotions.owners import resolve_owner_ids
from app.promotions.requests import promotable_event_ids
from app.promotions.views import daily_stats_table, load_daily_stats, paused_reasons, price_breakdown
from app.promotions.windows import event_last_day, now_tallinn, promotion_state, tallinn_today

# The organizer report leaves out viewer-sentiment (slot dislikes): the ticket
# lists shown/paused, Explore, Daily 5, digest sent and opens.
REPORT_COLUMNS = (
    PROMOTION_STAT_EXPLORE_SERVED,
    PROMOTION_STAT_DAILY5_PLACED,
    PROMOTION_STAT_DIGEST_SENT,
    PROMOTION_STAT_WEB_OPENS,
    PROMOTION_STAT_DIGEST_OPENS,
)


def list_status(promotion: Promotion, today: date, paused_reason: str | None) -> str:
    """The Organizer-facing status word for a Promotion."""
    if promotion.status == PROMOTION_STATUS_VOID:
        return PROMOTION_LIST_CANCELLED
    if promotion.status == PROMOTION_STATUS_ENDED_EARLY:
        return PROMOTION_LIST_ENDED_EARLY
    state = promotion_state(promotion.status, promotion.start_date, promotion.end_date, today)
    if promotion.status == PROMOTION_STATUS_UNPAID:
        # The sweep voids an unpaid Promotion when its start date begins.
        if state != PROMOTION_STATE_SCHEDULED:
            return PROMOTION_LIST_CANCELLED
        # An open card checkout is not an invoice: no invoice wording.
        return (
            PROMOTION_LIST_AWAITING_CHECKOUT
            if promotion.stripe_checkout_session_id is not None
            else PROMOTION_LIST_AWAITING_PAYMENT
        )
    if state == PROMOTION_STATE_FINISHED:
        return PROMOTION_LIST_FINISHED
    if state == PROMOTION_STATE_LIVE:
        return PROMOTION_LIST_PAUSED if paused_reason else PROMOTION_LIST_LIVE
    return PROMOTION_LIST_SCHEDULED


# Statuses that replace the "Promote" action with a badge on the event row.
_BADGE_STATUSES = frozenset(
    {
        PROMOTION_LIST_AWAITING_CHECKOUT,
        PROMOTION_LIST_AWAITING_PAYMENT,
        PROMOTION_LIST_SCHEDULED,
        PROMOTION_LIST_LIVE,
        PROMOTION_LIST_PAUSED,
    }
)


def _can_fit_window(event: Event, today: date) -> bool:
    earliest = today + timedelta(days=PROMOTION_MIN_LEAD_DAYS)
    return event_last_day(event) >= earliest + timedelta(days=PROMOTION_MIN_DAYS - 1)


async def event_promotion_flags(
    db: AsyncSession, organizer_id: int, events: Sequence[Event], now: datetime
) -> dict[int, dict]:
    """Per event id: `promotable` (the Organizer owns it, it is public,
    canonical and not ended, a minimum window still fits and nothing is open on
    it) and `badge` (a status word replacing the action while a request or a
    holding Promotion is open)."""
    if not events:
        return {}
    today = tallinn_today(now)
    ids = [e.id for e in events]
    owners = await resolve_owner_ids(db, events)
    ok = await promotable_event_ids(db, events, now)
    pending = set(
        (
            await db.scalars(
                select(PromotionRequest.event_id).where(
                    PromotionRequest.organizer_id == organizer_id,
                    PromotionRequest.event_id.in_(ids),
                    PromotionRequest.status == PROMOTION_REQUEST_STATUS_PENDING,
                )
            )
        ).all()
    )
    promotions = (
        await db.scalars(
            select(Promotion).where(
                Promotion.organizer_id == organizer_id,
                Promotion.event_id.in_(ids),
                Promotion.status.in_(PROMOTION_HOLDING_STATUSES),
                Promotion.end_date >= today,
            )
        )
    ).all()
    paused = await paused_reasons(db, promotions, now)
    badges: dict[int, str] = {}
    for promotion in promotions:
        status = list_status(promotion, today, paused.get(promotion.id))
        if status in _BADGE_STATUSES:
            badges[promotion.event_id] = status
    for event_id in pending:
        badges.setdefault(event_id, PROMOTION_LIST_REQUESTED)
    return {
        e.id: {
            "promotable": (
                owners.get(e.id) == organizer_id
                and e.id in ok
                and e.id not in badges
                and _can_fit_window(e, today)
            ),
            "badge": badges.get(e.id),
        }
        for e in events
    }


async def promotion_flags_for(
    db: AsyncSession, organizer_id: int, events: Sequence[Event]
) -> dict[int, dict]:
    """The `promotion` key for each event row of an Organizer's event list:
    `{"promotion": {"promotable", "badge"}}`. Empty while the offer flag is
    off, so the rows carry no key at all and the portal shows nothing."""
    if not settings.PROMOTIONS_OFFER_ENABLED:
        return {}
    flags = await event_promotion_flags(db, organizer_id, events, now_tallinn())
    return {event_id: {"promotion": flag} for event_id, flag in flags.items()}


async def promotions_list(
    db: AsyncSession, organizer: Organizer, now: datetime
) -> list[dict]:
    """The Organizer's requests and Promotions in one list, newest first.
    Pending and declined requests show; a granted one is replaced by its
    Promotion, and withdrawn or expired ones drop off. A Promotion shows
    whatever the Organizer's ownership now is."""
    today = tallinn_today(now)
    requests = (
        await db.scalars(
            select(PromotionRequest).where(PromotionRequest.organizer_id == organizer.id)
        )
    ).all()
    requests = [
        r
        for r in requests
        if r.status in (PROMOTION_REQUEST_STATUS_PENDING, PROMOTION_REQUEST_STATUS_DECLINED)
    ]
    promotions = [
        p
        for p in (
            await db.scalars(select(Promotion).where(Promotion.organizer_id == organizer.id))
        ).all()
        # An abandoned card checkout leaves nothing worth listing.
        if not (
            p.stripe_checkout_session_id is not None
            and list_status(p, today, None) == PROMOTION_LIST_CANCELLED
        )
    ]
    event_ids = {r.event_id for r in requests} | {p.event_id for p in promotions}
    events = (
        {e.id: e for e in await db.scalars(select(Event).where(Event.id.in_(event_ids)))}
        if event_ids
        else {}
    )
    paused = await paused_reasons(db, promotions, now)

    items: list[tuple[datetime, int, dict]] = []
    for r in requests:
        items.append(
            (
                r.created_at,
                r.id,
                {
                    "kind": "request",
                    "id": r.id,
                    "event_id": r.event_id,
                    "event_title": resolve_title(events[r.event_id], organizer.locale),
                    "status": PROMOTION_LIST_REQUESTED
                    if r.status == PROMOTION_REQUEST_STATUS_PENDING
                    else PROMOTION_LIST_DECLINED,
                    "paused_reason": None,
                    "decline_reason": r.decline_reason,
                    "note": r.note,
                    "start_date": r.start_date.isoformat(),
                    "end_date": r.end_date.isoformat(),
                    "days": (r.end_date - r.start_date).days + 1,
                    "advertiser_legal_name": r.advertiser_legal_name,
                    "advertiser_registry_code": r.advertiser_registry_code,
                    "billing_email": r.billing_email,
                    "invoice_url": None,
                    "price": price_breakdown(
                        ((r.end_date - r.start_date).days + 1) * PROMOTION_DAY_PRICE_CENTS,
                        PROMOTION_VAT_RATE_PERCENT,
                    ),
                    "can_withdraw": r.status == PROMOTION_REQUEST_STATUS_PENDING,
                    "has_report": False,
                    "created_at": r.created_at.isoformat(),
                },
            )
        )
    for p in promotions:
        items.append(
            (
                p.created_at,
                p.id,
                {
                    "kind": "promotion",
                    "id": p.id,
                    "event_id": p.event_id,
                    "event_title": resolve_title(events[p.event_id], organizer.locale),
                    "status": list_status(p, today, paused.get(p.id)),
                    "paused_reason": paused.get(p.id),
                    "decline_reason": None,
                    "note": None,
                    "start_date": p.start_date.isoformat(),
                    "end_date": p.end_date.isoformat(),
                    "days": p.days,
                    "advertiser_legal_name": p.advertiser_legal_name,
                    "advertiser_registry_code": p.advertiser_registry_code,
                    "billing_email": p.billing_email,
                    "invoice_url": p.invoice_url if p.stripe_checkout_session_id else None,
                    "price": price_breakdown(p.net_price_cents, p.vat_rate_percent),
                    "is_complimentary": p.is_complimentary,
                    "can_withdraw": False,
                    "has_report": True,
                    "created_at": p.created_at.isoformat(),
                },
            )
        )
    # Newest first; kind then id break created_at ties so the order is stable.
    items.sort(key=lambda t: (t[0], t[2]["kind"], t[1]), reverse=True)
    return [item for _, _, item in items]


def serialize_request(request: PromotionRequest, event_title: str) -> dict:
    days = (request.end_date - request.start_date).days + 1
    return {
        "kind": "request",
        "id": request.id,
        "event_id": request.event_id,
        "event_title": event_title,
        "status": PROMOTION_LIST_REQUESTED
        if request.status == PROMOTION_REQUEST_STATUS_PENDING
        else request.status,
        "start_date": request.start_date.isoformat(),
        "end_date": request.end_date.isoformat(),
        "days": days,
        "advertiser_legal_name": request.advertiser_legal_name,
        "advertiser_registry_code": request.advertiser_registry_code,
        "billing_email": request.billing_email,
        "note": request.note,
        "terms_version": request.terms_version,
        "price": price_breakdown(days * PROMOTION_DAY_PRICE_CENTS, PROMOTION_VAT_RATE_PERCENT),
        "can_withdraw": request.status == PROMOTION_REQUEST_STATUS_PENDING,
        "created_at": request.created_at.isoformat() if request.created_at else None,
    }


async def request_context(
    db: AsyncSession, organizer: Organizer, event: Event, now: datetime
) -> dict:
    """What the request form needs for one event the Organizer owns: the window
    rules, the price, the days already sold out (dates only, never counts) and
    whether the event can be promoted now."""
    today = tallinn_today(now)
    earliest = today + timedelta(days=PROMOTION_MIN_LEAD_DAYS)
    last_day = event_last_day(event)
    horizon_end = min(last_day, earliest + timedelta(days=PROMOTION_UNAVAILABLE_HORIZON_DAYS - 1))
    unavailable = (
        await full_days(db, earliest, horizon_end, today) if horizon_end >= earliest else []
    )
    flags = (await event_promotion_flags(db, organizer.id, [event], now))[event.id]
    return {
        "event_id": event.id,
        "event_title": resolve_title(event, organizer.locale),
        "promotable": flags["promotable"],
        "badge": flags["badge"],
        "checkout_available": checkout_enabled(),
        # Card checkout needs the event assessed clear; anything else is reviewed.
        "review_required": event.promotion_restriction != PROMOTION_RESTRICTION_NONE,
        "today": today.isoformat(),
        "earliest_start": earliest.isoformat(),
        "event_last_day": last_day.isoformat(),
        "rules": {"min_days": PROMOTION_MIN_DAYS, "max_days": PROMOTION_MAX_DAYS},
        "pricing": {
            "day_price_cents": PROMOTION_DAY_PRICE_CENTS,
            "vat_rate_percent": str(PROMOTION_VAT_RATE_PERCENT),
        },
        "terms_version": ORGANIZER_TERMS_VERSION,
        "billing_email_default": organizer.email,
        "unavailable_dates": [d.isoformat() for d in unavailable],
    }


async def promotion_report(db: AsyncSession, promotion: Promotion, now: datetime) -> dict:
    """The purchasing Organizer's per-day report: complete days only, anonymous
    totals, one Daily 5 reach figure. Reads the stored rows with one query."""
    today = tallinn_today(now)
    stored = (await load_daily_stats(db, [promotion.id]))[promotion.id]
    days = [
        {
            "day": row["day"],
            "shown": row["gate_outcome"] == PROMOTION_GATE_OUTCOME_SHOWN,
            "paused": row["gate_outcome"] == PROMOTION_GATE_OUTCOME_PAUSED,
            "paused_reason": row["gate_reason"]
            if row["gate_outcome"] == PROMOTION_GATE_OUTCOME_PAUSED
            else None,
            **{col: row[col] for col in REPORT_COLUMNS},
        }
        for row in daily_stats_table(promotion, stored, today)
    ]
    through = min(promotion.end_date, today - timedelta(days=1))
    return {
        "promotion_id": promotion.id,
        "event_id": promotion.event_id,
        "start_date": promotion.start_date.isoformat(),
        "end_date": promotion.end_date.isoformat(),
        "updated": "daily",
        "through": through.isoformat() if through >= promotion.start_date else None,
        "daily5_reach": promotion.daily5_reach,
        "days": days,
    }
