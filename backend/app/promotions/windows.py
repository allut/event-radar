"""Promotion window rules and computed states. Pure: no DB, no clock reads."""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.constants.core import TALLINN_TZ
from app._generated.shared_constants import PROMOTION_MAX_DAYS
from app.constants.promotions import (
    PROMOTION_ERROR_ENDS_AFTER_EVENT,
    PROMOTION_ERROR_MESSAGES,
    PROMOTION_ERROR_STARTS_TOO_EARLY,
    PROMOTION_ERROR_TOO_LONG,
    PROMOTION_ERROR_TOO_SHORT,
    PROMOTION_ERROR_WINDOW_ORDER,
    PROMOTION_HOLDING_STATUSES,
    PROMOTION_MIN_DAYS,
    PROMOTION_MIN_LEAD_DAYS,
    PROMOTION_STATE_FINISHED,
    PROMOTION_STATE_LIVE,
    PROMOTION_STATE_SCHEDULED,
)
from app.models.models import Event


@dataclass(frozen=True)
class RuleViolation:
    """One refused rule. `dates` lists the offending days when that helps the
    form (the cap days that are full, the overlapped window's bounds)."""

    code: str
    dates: list[date] = field(default_factory=list)

    @property
    def message(self) -> str:
        return PROMOTION_ERROR_MESSAGES[self.code]

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "dates": [d.isoformat() for d in self.dates],
        }


def now_tallinn() -> datetime:
    return datetime.now(TALLINN_TZ)


def tallinn_today(now: datetime) -> date:
    """The Tallinn calendar date of an aware instant."""
    return now.astimezone(TALLINN_TZ).date()


def event_last_day(event: Event) -> date:
    """The event's last Tallinn day: `ends_at`, or `starts_at` with no end."""
    return (event.ends_at or event.starts_at).astimezone(TALLINN_TZ).date()


def window_days(start: date, end: date) -> int:
    return (end - start).days + 1


def window_dates(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range(window_days(start, end))]


def window_violations(
    start: date, end: date, today: date, last_day: date
) -> list[RuleViolation]:
    """Every window rule the dates break, in a stable order (empty = valid)."""
    if end < start:
        return [RuleViolation(PROMOTION_ERROR_WINDOW_ORDER)]
    found: list[RuleViolation] = []
    days = window_days(start, end)
    if days < PROMOTION_MIN_DAYS:
        found.append(RuleViolation(PROMOTION_ERROR_TOO_SHORT))
    if days > PROMOTION_MAX_DAYS:
        found.append(RuleViolation(PROMOTION_ERROR_TOO_LONG))
    if start < today + timedelta(days=PROMOTION_MIN_LEAD_DAYS):
        found.append(RuleViolation(PROMOTION_ERROR_STARTS_TOO_EARLY))
    if end > last_day:
        found.append(RuleViolation(PROMOTION_ERROR_ENDS_AFTER_EVENT))
    return found


def promotion_state(status: str, start: date, end: date, today: date) -> str:
    """Scheduled, live or finished, computed from the window and today's
    Tallinn date. A stored `void` or `ended_early` is always finished."""
    if status not in PROMOTION_HOLDING_STATUSES or today > end:
        return PROMOTION_STATE_FINISHED
    if today < start:
        return PROMOTION_STATE_SCHEDULED
    return PROMOTION_STATE_LIVE
