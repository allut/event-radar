"""Window rules and computed states: pure functions, times frozen around Tallinn midnight."""

from datetime import date, datetime, timezone

from app.constants.core import TALLINN_TZ
from app.constants.promotions import (
    PROMOTION_ERROR_ENDS_AFTER_EVENT,
    PROMOTION_ERROR_STARTS_TOO_EARLY,
    PROMOTION_ERROR_TOO_LONG,
    PROMOTION_ERROR_TOO_SHORT,
    PROMOTION_ERROR_WINDOW_ORDER,
    PROMOTION_STATE_FINISHED,
    PROMOTION_STATE_LIVE,
    PROMOTION_STATE_SCHEDULED,
    PROMOTION_STATUS_ENDED_EARLY,
    PROMOTION_STATUS_PAID,
    PROMOTION_STATUS_UNPAID,
    PROMOTION_STATUS_VOID,
)
from app.promotions.windows import (
    event_last_day,
    promotion_state,
    tallinn_today,
    window_violations,
)

LAST_DAY = date(2026, 12, 31)


def codes(start: date, end: date, today: date, last_day: date = LAST_DAY) -> list[str]:
    return [v.code for v in window_violations(start, end, today, last_day)]


def test_tallinn_today_flips_at_tallinn_midnight_not_utc() -> None:
    before = datetime(2026, 10, 17, 20, 59, 59, tzinfo=timezone.utc)  # 23:59:59 EEST
    after = datetime(2026, 10, 17, 21, 0, 0, tzinfo=timezone.utc)  # 00:00:00 EEST
    assert tallinn_today(before) == date(2026, 10, 17)
    assert tallinn_today(after) == date(2026, 10, 18)


def test_tallinn_today_across_the_autumn_dst_change() -> None:
    # EEST -> EET on 2026-10-25 at 04:00 local: midnight is UTC+3 before, UTC+2 after.
    assert tallinn_today(datetime(2026, 10, 24, 20, 59, tzinfo=timezone.utc)) == date(2026, 10, 24)
    assert tallinn_today(datetime(2026, 10, 24, 21, 0, tzinfo=timezone.utc)) == date(2026, 10, 25)
    assert tallinn_today(datetime(2026, 10, 25, 21, 59, tzinfo=timezone.utc)) == date(2026, 10, 25)
    assert tallinn_today(datetime(2026, 10, 25, 22, 0, tzinfo=timezone.utc)) == date(2026, 10, 26)


def test_tomorrow_is_the_earliest_start_just_before_midnight() -> None:
    today = tallinn_today(datetime(2026, 10, 17, 20, 59, 59, tzinfo=timezone.utc))
    assert codes(date(2026, 10, 18), date(2026, 10, 20), today) == []
    assert codes(date(2026, 10, 17), date(2026, 10, 19), today) == [PROMOTION_ERROR_STARTS_TOO_EARLY]


def test_tomorrow_moves_forward_one_second_after_midnight() -> None:
    today = tallinn_today(datetime(2026, 10, 17, 21, 0, 1, tzinfo=timezone.utc))
    assert codes(date(2026, 10, 18), date(2026, 10, 20), today) == [PROMOTION_ERROR_STARTS_TOO_EARLY]
    assert codes(date(2026, 10, 19), date(2026, 10, 21), today) == []


def test_length_bounds_are_inclusive_days() -> None:
    today = date(2026, 10, 17)
    start = date(2026, 10, 20)
    assert codes(start, date(2026, 10, 21), today) == [PROMOTION_ERROR_TOO_SHORT]  # 2 days
    assert codes(start, date(2026, 10, 22), today) == []  # 3 days
    assert codes(start, date(2026, 11, 2), today) == []  # 14 days
    assert codes(start, date(2026, 11, 3), today) == [PROMOTION_ERROR_TOO_LONG]  # 15 days


def test_end_before_start_is_a_single_order_error() -> None:
    assert codes(date(2026, 10, 25), date(2026, 10, 20), date(2026, 10, 17)) == [
        PROMOTION_ERROR_WINDOW_ORDER
    ]


def test_must_end_on_or_before_the_events_last_day() -> None:
    today = date(2026, 10, 17)
    last = date(2026, 10, 24)
    assert codes(date(2026, 10, 20), date(2026, 10, 24), today, last) == []
    assert codes(date(2026, 10, 20), date(2026, 10, 25), today, last) == [
        PROMOTION_ERROR_ENDS_AFTER_EVENT
    ]


def test_every_violation_is_reported_together() -> None:
    got = codes(date(2026, 10, 17), date(2026, 10, 18), date(2026, 10, 17), date(2026, 10, 17))
    assert got == [
        PROMOTION_ERROR_TOO_SHORT,
        PROMOTION_ERROR_STARTS_TOO_EARLY,
        PROMOTION_ERROR_ENDS_AFTER_EVENT,
    ]


class _Ev:
    def __init__(self, starts_at: datetime, ends_at: datetime | None) -> None:
        self.starts_at = starts_at
        self.ends_at = ends_at


def test_event_last_day_uses_ends_at_else_starts_at_in_tallinn() -> None:
    # 22:30 UTC on the 20th is 01:30 on the 21st in Tallinn.
    late = datetime(2026, 10, 20, 22, 30, tzinfo=timezone.utc)
    assert event_last_day(_Ev(late, None)) == date(2026, 10, 21)  # type: ignore[arg-type]
    ends = datetime(2026, 10, 30, 12, 0, tzinfo=TALLINN_TZ)
    assert event_last_day(_Ev(late, ends)) == date(2026, 10, 30)  # type: ignore[arg-type]


def test_state_is_computed_from_window_and_today() -> None:
    start, end = date(2026, 10, 20), date(2026, 10, 22)
    paid = PROMOTION_STATUS_PAID
    assert promotion_state(paid, start, end, date(2026, 10, 19)) == PROMOTION_STATE_SCHEDULED
    assert promotion_state(paid, start, end, date(2026, 10, 20)) == PROMOTION_STATE_LIVE
    assert promotion_state(paid, start, end, date(2026, 10, 22)) == PROMOTION_STATE_LIVE
    assert promotion_state(paid, start, end, date(2026, 10, 23)) == PROMOTION_STATE_FINISHED
    assert promotion_state(PROMOTION_STATUS_UNPAID, start, end, date(2026, 10, 21)) == PROMOTION_STATE_LIVE
    assert promotion_state(PROMOTION_STATUS_VOID, start, end, date(2026, 10, 21)) == PROMOTION_STATE_FINISHED
    assert (
        promotion_state(PROMOTION_STATUS_ENDED_EARLY, start, end, date(2026, 10, 19))
        == PROMOTION_STATE_FINISHED
    )
