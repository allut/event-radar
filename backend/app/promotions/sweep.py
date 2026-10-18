"""Automatic Promotion lifecycle (#602), run by a scheduled sweep.

Void an `unpaid` Promotion once its start date begins; end a `paid` one early
when its event is cancelled (carrying the cancellation cause over as
`end_reason`) or when the claim that gave its Organizer ownership is gone
(`claim_revoked`). A dormant claim or a lost dedup collision never ends one:
those only pause it through the fill gate. Each change writes a system audit
row; the Organizer is emailed after the commit, except for the silent void.

The query count is fixed whatever the number of Promotions: the cap lock, one
SELECT per status, the two owner queries, one Organizer lookup and the flush.
"""

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.admin import (
    ADMIN_ACTION_PROMOTION_SYSTEM_END,
    ADMIN_ACTION_PROMOTION_SYSTEM_VOID,
)
from app.constants.events import EVENT_STATUS_CANCELLED
from app.constants.log_events import LOG_EVENT_ADMIN_ACTION, LOG_EVENT_EMAIL_SEND_FAILED
from app.constants.promotions import (
    PROMOTION_AUTO_END_EMAIL_REASONS,
    PROMOTION_AUTO_END_NOTES,
    PROMOTION_END_REASON_CANCELLATION_FALLBACK,
    PROMOTION_END_REASON_CLAIM_REVOKED,
    PROMOTION_END_REASON_UNPAID_AT_START,
    PROMOTION_STATUS_ENDED_EARLY,
    PROMOTION_STATUS_PAID,
    PROMOTION_STATUS_UNPAID,
    PROMOTION_STATUS_VOID,
)
from app.email.promotion_notice import send_promotion_ended_email
from app.events.localize import resolve_title
from app.models.models import AdminAction, Event, Organizer, Promotion
from app.promotions.cap import lock_cap
from app.promotions.owners import resolve_owner_ids
from app.promotions.windows import now_tallinn, tallinn_today

log = logging.getLogger(__name__)


def _audit(db: AsyncSession, promotion: Promotion, action: str, reason: str) -> None:
    result = {
        "actor": "system",
        "status": promotion.status,
        "end_reason": reason,
        "event_id": promotion.event_id,
    }
    db.add(AdminAction(action=action, target=str(promotion.id), result=result))
    log.info(
        "admin action: %s",
        action,
        extra={
            "event": LOG_EVENT_ADMIN_ACTION,
            "action": action,
            "target": promotion.id,
            "result": result,
        },
    )


def _stop(promotion: Promotion, status: str, reason: str, now: datetime) -> None:
    promotion.status = status
    promotion.ended_at = now
    promotion.end_reason = reason
    promotion.end_note = PROMOTION_AUTO_END_NOTES[reason]
    promotion.updated_at = now


async def sweep_promotions(db: AsyncSession, now: datetime | None = None) -> dict:
    """Apply every automatic transition, commit, then email the Organizers.

    Commits internally (like `expire_stale_claims`) so an email only follows a
    durable change; wire it with `commit=False`."""
    now = now or now_tallinn()
    today = tallinn_today(now)
    await lock_cap(db)

    unpaid = (
        await db.scalars(
            select(Promotion)
            .where(Promotion.status == PROMOTION_STATUS_UNPAID, Promotion.start_date <= today)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).all()
    for promotion in unpaid:
        _stop(promotion, PROMOTION_STATUS_VOID, PROMOTION_END_REASON_UNPAID_AT_START, now)
        _audit(
            db, promotion, ADMIN_ACTION_PROMOTION_SYSTEM_VOID, PROMOTION_END_REASON_UNPAID_AT_START
        )

    rows = (
        await db.execute(
            select(Promotion, Event)
            .join(Event, Event.id == Promotion.event_id)
            .where(Promotion.status == PROMOTION_STATUS_PAID, Promotion.end_date >= today)
            .with_for_update(of=Promotion)
            .execution_options(populate_existing=True)
        )
    ).all()
    active = [event for promotion, event in rows if event.status != EVENT_STATUS_CANCELLED]
    owners = await resolve_owner_ids(db, active, include_dormant=True) if active else {}

    ended: list[tuple[Promotion, Event, str]] = []
    for promotion, event in rows:
        if event.status == EVENT_STATUS_CANCELLED:
            reason = event.cancellation_reason or PROMOTION_END_REASON_CANCELLATION_FALLBACK
            if reason not in PROMOTION_AUTO_END_NOTES:
                reason = PROMOTION_END_REASON_CANCELLATION_FALLBACK
        elif owners.get(event.id) != promotion.organizer_id:
            reason = PROMOTION_END_REASON_CLAIM_REVOKED
        else:
            continue
        _stop(promotion, PROMOTION_STATUS_ENDED_EARLY, reason, now)
        _audit(db, promotion, ADMIN_ACTION_PROMOTION_SYSTEM_END, reason)
        ended.append((promotion, event, reason))

    organizers: dict[int, Organizer] = {}
    to_email = [item for item in ended if item[2] in PROMOTION_AUTO_END_EMAIL_REASONS]
    if to_email:
        organizer_ids = {promotion.organizer_id for promotion, _, _ in to_email}
        organizers = {
            o.id: o
            for o in (await db.scalars(select(Organizer).where(Organizer.id.in_(organizer_ids))))
        }
    await db.commit()

    for promotion, event, reason in to_email:
        organizer = organizers.get(promotion.organizer_id)
        if organizer is None:
            continue
        try:
            await send_promotion_ended_email(
                organizer.email,
                resolve_title(event, organizer.locale),
                promotion.start_date,
                promotion.end_date,
                PROMOTION_AUTO_END_NOTES[reason],
                organizer.locale,
            )
        except Exception:
            log.error(
                "Failed to send promotion ended email (promotion_id=%s)",
                promotion.id,
                exc_info=True,
                extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
            )
    return {"voided": len(unpaid), "ended": len(ended)}
