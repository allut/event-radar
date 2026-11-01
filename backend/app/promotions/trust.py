"""Trust panel reads (#620): the tripwires an operator reviews to decide
whether ads hurt trust, for the rolling 4 weeks and since launch, next to the
denominators. One query per figure set, whatever the row count. Nothing here
flips a flag; the thresholds are guidance in docs/backend-ops.md."""

from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import Date, and_, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.admin import ADMIN_ACTION_PROMOTION_COMPLAINT
from app.constants.core import TALLINN_TZ
from app.constants.events import EVENT_CANCELLATION_REASON_REPORT_TAKEDOWN
from app.constants.email import CONSENT_SOURCE_EMAIL_LINK_UNDO, VALID_CONSENT_SOURCES
from app.constants.promotions import (
    PROMOTION_STATUS_ENDED_EARLY,
    PROMOTION_STATUS_PAID,
    PROMOTION_TRUST_PERIOD_LAUNCH,
    PROMOTION_TRUST_PERIOD_ROLLING,
    PROMOTION_TRUST_RECENT_COMPLAINTS,
    PROMOTION_TRUST_WINDOW_DAYS,
)
from app.constants.reports import REPORT_STATUS_RESOLVED
from app.models.events import EventReport
from app.models.audit import AdminAction
from app.models.promotions import EmailAdConsentLog, Promotion, PromotionDailyStat
from app.models.users import User
from app.promotions.windows import tallinn_today


def _window_start(today: date) -> date:
    return today - timedelta(days=PROMOTION_TRUST_WINDOW_DAYS - 1)


def _count_in(since: datetime, column: Any) -> Any:
    """COUNT of rows whose `column` is on or after `since`."""
    return func.count().filter(column >= since)


async def _reports(db: AsyncSession, since: datetime) -> dict[str, dict[str, int]]:
    """Reports filed on an event while a paid Promotion covered it (Tallinn
    days of its window, up to the early end), plus Promotions the report
    takedown ended. Both periods in one statement."""
    report_day = cast(func.timezone(TALLINN_TZ.key, EventReport.created_at), Date)
    on_promoted = (
        and_(
            Promotion.status.in_((PROMOTION_STATUS_PAID, PROMOTION_STATUS_ENDED_EARLY)),
            report_day >= Promotion.start_date,
            report_day <= Promotion.end_date,
            or_(Promotion.ended_at.is_(None), EventReport.created_at <= Promotion.ended_at),
        )
    )
    reports = (
        await db.execute(
            select(
                func.count(),
                _count_in(since, EventReport.created_at),
                func.count().filter(EventReport.status == REPORT_STATUS_RESOLVED),
                func.count().filter(
                    EventReport.status == REPORT_STATUS_RESOLVED,
                    EventReport.created_at >= since,
                ),
            )
            .select_from(EventReport)
            .join(Promotion, Promotion.event_id == EventReport.event_id)
            .where(on_promoted)
        )
    ).one()
    takedowns = (
        await db.execute(
            select(func.count(), _count_in(since, Promotion.ended_at)).where(
                Promotion.end_reason == EVENT_CANCELLATION_REASON_REPORT_TAKEDOWN
            )
        )
    ).one()
    return {
        PROMOTION_TRUST_PERIOD_LAUNCH: {
            "reports_on_promoted": reports[0],
            "reports_resolved": reports[2],
            "promotions_taken_down": takedowns[0],
        },
        PROMOTION_TRUST_PERIOD_ROLLING: {
            "reports_on_promoted": reports[1],
            "reports_resolved": reports[3],
            "promotions_taken_down": takedowns[1],
        },
    }


async def _consent(db: AsyncSession, since: datetime) -> dict[str, dict[str, Any]]:
    """Email ad consent log, grouped by direction and source. Withdrawals are
    listed for every source (zero when none); new consents exclude the undo
    of a withdrawal, which is not a fresh consent."""
    rows = (
        await db.execute(
            select(
                EmailAdConsentLog.granted,
                EmailAdConsentLog.source,
                func.count(),
                _count_in(since, EmailAdConsentLog.created_at),
            ).group_by(EmailAdConsentLog.granted, EmailAdConsentLog.source)
        )
    ).all()
    out: dict[str, dict[str, Any]] = {}
    for column, period in ((2, PROMOTION_TRUST_PERIOD_LAUNCH), (3, PROMOTION_TRUST_PERIOD_ROLLING)):
        by_source = dict.fromkeys(sorted(VALID_CONSENT_SOURCES), 0)
        granted = 0
        for row in rows:
            count = row[column]
            if not row[0]:
                by_source[row[1]] = by_source.get(row[1], 0) + count
            elif row[1] != CONSENT_SOURCE_EMAIL_LINK_UNDO:
                granted += count
        out[period] = {
            "consents_granted": granted,
            "consent_withdrawals": {
                "total": sum(by_source.values()),
                "by_source": by_source,
            },
        }
    return out


async def _delivery(db: AsyncSession, window_start: date) -> dict[str, dict[str, Any]]:
    """Daily-stats sums: slots served (Explore + Daily 5 + digest), the
    slot's web opens and the slot dislikes."""
    columns = (
        PromotionDailyStat.explore_served,
        PromotionDailyStat.daily5_placed,
        PromotionDailyStat.digest_sent,
        PromotionDailyStat.web_opens,
        PromotionDailyStat.slot_dislikes,
    )
    row = (
        await db.execute(
            select(
                *(func.coalesce(func.sum(c), 0) for c in columns),
                *(
                    func.coalesce(
                        func.sum(case((PromotionDailyStat.day >= window_start, c), else_=0)), 0
                    )
                    for c in columns
                ),
            )
        )
    ).one()
    keys = ("explore_served", "daily5_placed", "digest_sent", "web_opens", "slot_dislikes")
    out: dict[str, dict[str, Any]] = {}
    for offset, period in ((0, PROMOTION_TRUST_PERIOD_LAUNCH), (len(keys), PROMOTION_TRUST_PERIOD_ROLLING)):
        values = {k: int(row[offset + i]) for i, k in enumerate(keys)}
        out[period] = {
            "slots_served": values["explore_served"] + values["daily5_placed"] + values["digest_sent"],
            "slots_served_by_surface": {
                "explore": values["explore_served"],
                "daily5": values["daily5_placed"],
                "digest": values["digest_sent"],
            },
            "web_opens": values["web_opens"],
            "slot_dislikes": values["slot_dislikes"],
        }
    return out


async def _complaints(
    db: AsyncSession, since: datetime
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Logged complaints: counts for both periods in one query, and the
    newest few with their notes in a second."""
    is_complaint = AdminAction.action == ADMIN_ACTION_PROMOTION_COMPLAINT
    total, rolling = (
        await db.execute(
            select(func.count(), _count_in(since, AdminAction.created_at)).where(is_complaint)
        )
    ).one()
    recent = (
        await db.scalars(
            select(AdminAction)
            .where(is_complaint)
            .order_by(AdminAction.created_at.desc(), AdminAction.id.desc())
            .limit(PROMOTION_TRUST_RECENT_COMPLAINTS)
        )
    ).all()
    return (
        {PROMOTION_TRUST_PERIOD_LAUNCH: total, PROMOTION_TRUST_PERIOD_ROLLING: rolling},
        [
            {
                "id": a.id,
                "created_at": a.created_at.isoformat(),
                "source": a.result.get("source"),
                "complainant": a.result.get("complainant"),
                "note": a.result.get("note"),
            }
            for a in recent
        ],
    )


async def trust_panel(db: AsyncSession, now: datetime) -> dict[str, Any]:
    """The Trust panel payload: `current` denominators plus one block per
    period. Six statements in all, independent of the data size."""
    today = tallinn_today(now)
    window_start = _window_start(today)
    since = datetime.combine(window_start, time.min, TALLINN_TZ)
    reports = await _reports(db, since)
    consent = await _consent(db, since)
    delivery = await _delivery(db, window_start)
    complaint_counts, recent = await _complaints(db, since)
    live, consenters = (
        await db.execute(
            select(
                select(func.count())
                .select_from(Promotion)
                .where(
                    Promotion.status == PROMOTION_STATUS_PAID,
                    Promotion.start_date <= today,
                    Promotion.end_date >= today,
                )
                .scalar_subquery(),
                select(func.count()).select_from(User).where(User.email_ad_consent.is_(True)).scalar_subquery(),
            )
        )
    ).one()
    return {
        "as_of": now.isoformat(),
        "window_days": PROMOTION_TRUST_WINDOW_DAYS,
        "window_start": window_start.isoformat(),
        "current": {"live_promotions": live, "consenters": consenters},
        "periods": {
            period: {
                **reports[period],
                **consent[period],
                **delivery[period],
                "complaints": complaint_counts[period],
            }
            for period in (PROMOTION_TRUST_PERIOD_ROLLING, PROMOTION_TRUST_PERIOD_LAUNCH)
        },
        "recent_complaints": recent,
    }
