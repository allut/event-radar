"""Read side of Promotions: list, serialization and the grant form's context."""

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.admin import PROMOTION_ADMIN_ACTIONS
from app.constants.promotions import (
    PROMOTION_STATUS_ENDED_EARLY,
    PROMOTION_STATUS_PAID,
    PROMOTION_STATUS_UNPAID,
    PROMOTION_STAT_REPORT_COLUMNS,
    PROMOTION_CAP_STRIP_DAYS,
    PROMOTION_DAY_PRICE_CENTS,
    PROMOTION_HOLDING_STATUSES,
    PROMOTION_LIVE_CAP,
    PROMOTION_MAX_DAYS,
    PROMOTION_MIN_DAYS,
    PROMOTION_MIN_LEAD_DAYS,
    PROMOTION_STATE_FINISHED,
    PROMOTION_STATE_LIVE,
    PROMOTION_STATE_SCHEDULED,
    PROMOTION_VAT_RATE_PERCENT,
)
from app.models.models import AdminAction, Event, Organizer, Promotion, PromotionDailyStat
from app.promotions.grant import net_price_cents, vat_cents
from app.promotions.owners import resolve_owner_ids
from app.promotions.restriction import is_restricted
from app.promotions.snapshots import list_snapshots, serialize_snapshot
from app.promotions.windows import (
    event_last_day,
    promotion_state,
    tallinn_today,
    window_dates,
)


def state_filter(state: str, today: date) -> ColumnElement[bool]:
    holding = Promotion.status.in_(PROMOTION_HOLDING_STATUSES)
    if state == PROMOTION_STATE_SCHEDULED:
        return and_(holding, Promotion.start_date > today)
    if state == PROMOTION_STATE_LIVE:
        return and_(holding, Promotion.start_date <= today, Promotion.end_date >= today)
    if state == PROMOTION_STATE_FINISHED:
        return or_(~holding, Promotion.end_date < today)
    raise ValueError(state)


def price_breakdown(net_cents: int, vat_rate_percent: Decimal) -> dict:
    vat = vat_cents(net_cents, vat_rate_percent)
    return {"net_cents": net_cents, "vat_cents": vat, "gross_cents": net_cents + vat}


def serialize_promotion(
    promotion: Promotion, event_title: str, organizer_name: str | None, today: date
) -> dict:
    price = price_breakdown(promotion.net_price_cents, promotion.vat_rate_percent)
    return {
        "id": promotion.id,
        "event_id": promotion.event_id,
        "event_title": event_title,
        "organizer_id": promotion.organizer_id,
        "organizer_name": organizer_name,
        "status": promotion.status,
        "state": promotion_state(
            promotion.status, promotion.start_date, promotion.end_date, today
        ),
        "start_date": promotion.start_date.isoformat(),
        "end_date": promotion.end_date.isoformat(),
        "days": promotion.days,
        "net_price_cents": promotion.net_price_cents,
        "vat_rate_percent": str(promotion.vat_rate_percent),
        "vat_cents": price["vat_cents"],
        "gross_price_cents": price["gross_cents"],
        "is_complimentary": promotion.is_complimentary,
        "complimentary_note": promotion.complimentary_note,
        "invoice_reference": promotion.invoice_reference,
        "invoice_source": promotion.invoice_source,
        "advertiser_legal_name": promotion.advertiser_legal_name,
        "advertiser_registry_code": promotion.advertiser_registry_code,
        "billing_email": promotion.billing_email,
        "granted_by": promotion.granted_by,
        "paid_at": promotion.paid_at.isoformat() if promotion.paid_at else None,
        "ended_at": promotion.ended_at.isoformat() if promotion.ended_at else None,
        "end_reason": promotion.end_reason,
        "daily5_reach": promotion.daily5_reach,
        "end_note": promotion.end_note,
        "refunded_cents": promotion.refunded_cents,
        "refund_note": promotion.refund_note,
        "restriction_clearance": (
            {
                "restriction": promotion.restriction_cleared,
                "by": promotion.restriction_clearance_by,
                "note": promotion.restriction_clearance_note,
                "cleared_at": promotion.restriction_cleared_at.isoformat()
                if promotion.restriction_cleared_at
                else None,
            }
            if promotion.restriction_cleared is not None
            else None
        ),
        "created_at": promotion.created_at.isoformat() if promotion.created_at else None,
    }


async def list_promotions(
    db: AsyncSession, *, state: str | None, limit: int, offset: int, today: date
) -> tuple[list[dict], int]:
    """One page of Promotions (newest window first) and the total for the
    filter. Event title and Organizer name come from the same join."""
    where = [state_filter(state, today)] if state else []
    total = (
        await db.scalar(select(func.count()).select_from(Promotion).where(*where))
    ) or 0
    rows = (
        await db.execute(
            select(Promotion, Event.title_orig, Organizer.name)
            .join(Event, Event.id == Promotion.event_id)
            .join(Organizer, Organizer.id == Promotion.organizer_id)
            .where(*where)
            .order_by(Promotion.start_date.desc(), Promotion.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [serialize_promotion(p, title, name, today) for p, title, name in rows], total


async def grant_context(db: AsyncSession, event: Event, now: datetime) -> dict:
    """What the grant form needs for one event: the resolved owner (or null),
    prefilled advertiser fields, the window bounds and pricing, and the
    event's existing Promotions."""
    today = tallinn_today(now)
    owner_id = (await resolve_owner_ids(db, [event])).get(event.id)
    owner = await db.get(Organizer, owner_id) if owner_id is not None else None
    existing = (
        await db.scalars(
            select(Promotion)
            .where(Promotion.event_id == event.id)
            .order_by(Promotion.start_date.desc(), Promotion.id.desc())
        )
    ).all()
    return {
        "event_id": event.id,
        "event_title": event.title_orig,
        "promotion_restriction": event.promotion_restriction,
        "owner": (
            {"organizer_id": owner.id, "name": owner.name, "email": owner.email}
            if owner is not None
            else None
        ),
        "prefill": {
            "advertiser_legal_name": owner.name if owner is not None else None,
            "billing_email": owner.email if owner is not None else None,
        },
        "today": today.isoformat(),
        "earliest_start": (today + timedelta(days=PROMOTION_MIN_LEAD_DAYS)).isoformat(),
        "event_last_day": event_last_day(event).isoformat(),
        "rules": {
            "min_days": PROMOTION_MIN_DAYS,
            "max_days": PROMOTION_MAX_DAYS,
            "cap": PROMOTION_LIVE_CAP,
            "cap_strip_days": PROMOTION_CAP_STRIP_DAYS,
        },
        "pricing": {
            "day_price_cents": PROMOTION_DAY_PRICE_CENTS,
            "vat_rate_percent": str(PROMOTION_VAT_RATE_PERCENT),
        },
        "promotions": [
            serialize_promotion(p, event.title_orig, owner.name if owner else None, today)
            for p in existing
        ],
    }


def validation_payload(
    start: date, end: date, violations: list, is_complimentary: bool
) -> dict:
    days = (end - start).days + 1 if end >= start else 0
    net = net_price_cents(days, is_complimentary)
    return {
        "valid": not violations,
        "errors": [v.as_dict() for v in violations],
        "days": days,
        "price": price_breakdown(net, PROMOTION_VAT_RATE_PERCENT),
    }


def available_actions(promotion: Promotion, today: date) -> dict:
    """Which lifecycle commands the console may offer now. `edit_scope` is
    `full` before the start date, `end_date` while live and null otherwise."""
    holding = promotion.status in PROMOTION_HOLDING_STATUSES and today <= promotion.end_date
    price = price_breakdown(promotion.net_price_cents, promotion.vat_rate_percent)
    refundable = (
        not promotion.is_complimentary
        and promotion.status in (PROMOTION_STATUS_PAID, PROMOTION_STATUS_ENDED_EARLY)
        and promotion.refunded_cents < price["gross_cents"]
    )
    return {
        "mark_paid": promotion.status == PROMOTION_STATUS_UNPAID and today < promotion.start_date,
        "edit": holding,
        "edit_scope": (("full" if today < promotion.start_date else "end_date") if holding else None),
        "repoint": holding,
        "end": promotion.status == PROMOTION_STATUS_PAID and today <= promotion.end_date,
        "void": promotion.status == PROMOTION_STATUS_UNPAID,
        "refund": refundable,
        "refundable_cents": max(price["gross_cents"] - promotion.refunded_cents, 0) if refundable else 0,
    }


async def repoint_candidates(db: AsyncSession, promotion: Promotion, source: Event) -> list[dict]:
    """Events the Promotion could move to: same dedup group, same owner."""
    group = source.dedup_group_id if source.dedup_group_id is not None else source.id
    events = (
        await db.scalars(
            select(Event)
            .where(or_(Event.dedup_group_id == group, Event.id == group), Event.id != source.id)
            .order_by(Event.id)
        )
    ).all()
    owners = await resolve_owner_ids(db, events)
    return [
        {"event_id": e.id, "title": e.title_orig, "last_day": event_last_day(e).isoformat()}
        for e in events
        if owners.get(e.id) == promotion.organizer_id
    ]


async def promotion_detail(db: AsyncSession, promotion: Promotion, now: datetime) -> dict:
    """Everything the Promotion detail page shows: the row, its event, what it
    displayed (content snapshots, newest first), the audit trail, the
    commands available now and the events it could be re-pointed to."""
    today = tallinn_today(now)
    event = await db.get(Event, promotion.event_id)
    assert event is not None
    organizer = await db.get(Organizer, promotion.organizer_id)
    audit = (
        await db.scalars(
            select(AdminAction)
            .where(
                AdminAction.target == str(promotion.id),
                AdminAction.action.in_(PROMOTION_ADMIN_ACTIONS),
            )
            .order_by(AdminAction.id.desc())
        )
    ).all()
    payload = serialize_promotion(
        promotion, event.title_orig, organizer.name if organizer else None, today
    )
    payload["event"] = {
        "id": event.id,
        "title": event.title_orig,
        "starts_at": event.starts_at.isoformat(),
        "ends_at": event.ends_at.isoformat() if event.ends_at else None,
        "last_day": event_last_day(event).isoformat(),
        "venue_name": event.venue_name,
        "promotion_restriction": event.promotion_restriction,
    }
    payload["actions"] = available_actions(promotion, today)
    payload["actions"]["clear_restriction"] = (
        promotion.status in PROMOTION_HOLDING_STATUSES
        and today <= promotion.end_date
        and is_restricted(event.promotion_restriction)
        and promotion.restriction_cleared != event.promotion_restriction
    )
    payload["repoint_candidates"] = await repoint_candidates(db, promotion, event)
    payload["snapshots"] = [serialize_snapshot(sn) for sn in await list_snapshots(db, promotion.id)]
    payload["audit"] = [
        {"action": a.action, "result": a.result, "created_at": a.created_at.isoformat()}
        for a in audit
    ]
    return payload


async def load_daily_stats(
    db: AsyncSession, promotion_ids: list[int]
) -> dict[int, dict[date, PromotionDailyStat]]:
    """Stored per-day rows for any number of Promotions: one query."""
    if not promotion_ids:
        return {}
    rows = (
        await db.scalars(
            select(PromotionDailyStat).where(PromotionDailyStat.promotion_id.in_(promotion_ids))
        )
    ).all()
    grouped: dict[int, dict[date, PromotionDailyStat]] = {pid: {} for pid in promotion_ids}
    for row in rows:
        grouped[row.promotion_id][row.day] = row
    return grouped


def daily_stats_table(
    promotion: Promotion, stored: dict[date, PromotionDailyStat], today: date
) -> list[dict]:
    """One row per complete window day (before today), zeros where nothing was
    counted. Today is left out: its counts are still moving."""
    last = min(promotion.end_date, today - timedelta(days=1))
    if last < promotion.start_date:
        return []
    table: list[dict] = []
    for day in window_dates(promotion.start_date, last):
        row = stored.get(day)
        table.append(
            {
                "day": day.isoformat(),
                "gate_outcome": row.gate_outcome if row else None,
                "gate_reason": row.gate_reason if row else None,
                **{col: getattr(row, col) if row else 0 for col in PROMOTION_STAT_REPORT_COLUMNS},
            }
        )
    return table
