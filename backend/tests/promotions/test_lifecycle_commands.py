"""Edit, re-point, end early, void and refund. The clock is frozen around
Tallinn midnight wherever a date boundary decides the outcome."""

from datetime import date

import pytest
from sqlalchemy import select

from app._generated.shared_constants import (
    PROMOTION_ERROR_CAP_EXCEEDED,
    PROMOTION_ERROR_ENDS_AFTER_EVENT,
    PROMOTION_ERROR_INVALID_REGISTRY_CODE,
    PROMOTION_ERROR_OVERLAP,
    PROMOTION_ERROR_STARTS_TOO_EARLY,
    PROMOTION_ERROR_TOO_SHORT,
)
from app.constants.promotions import (
    PROMOTION_ERROR_ADVERTISER_NAME_REQUIRED,
    PROMOTION_ERROR_INVALID_TRANSITION,
    PROMOTION_ERROR_LIVE_EDIT_FIELDS,
    PROMOTION_ERROR_LIVE_END_IN_PAST,
    PROMOTION_ERROR_LIVE_END_MUST_SHORTEN,
    PROMOTION_ERROR_NOT_EDITABLE,
    PROMOTION_ERROR_NO_CHANGES,
    PROMOTION_ERROR_REASON_REQUIRED,
    PROMOTION_ERROR_REFUND_AMOUNT,
    PROMOTION_ERROR_REFUND_EXCEEDS_PAID,
    PROMOTION_ERROR_REFUND_NOTE_REQUIRED,
    PROMOTION_ERROR_REFUND_NOT_PAID,
    PROMOTION_ERROR_REPOINT_NOT_OWNER,
    PROMOTION_ERROR_REPOINT_NOT_SAME_GROUP,
    PROMOTION_ERROR_REPOINT_SAME_EVENT,
    PROMOTION_LIVE_CAP,
    PROMOTION_STATUS_ENDED_EARLY,
    PROMOTION_STATUS_PAID,
    PROMOTION_STATUS_VOID,
)
from app.models.promotions import PromotionSnapshot
from app.promotions.cap import cap_days
from app.promotions.grant import GrantRequest, PromotionRefused, grant_promotion
from app.promotions.lifecycle import (
    end_early,
    edit_promotion,
    mark_paid,
    record_refund,
    repoint_promotion,
    void_promotion,
)
from tests.promotions.conftest import NOW, at_tallinn, d


async def make_promo(db, make, start=10, end=14, *, paid=False, org=None, **event_kw):
    org = org or await make.organizer()
    ev = await make.event(submitted_by=org, **event_kw)
    promo = await grant_promotion(db, ev, GrantRequest(d(start), d(end), "Acme OÜ", "12345678"), NOW)
    if paid:
        await mark_paid(db, promo.id, NOW)
    return ev, promo


async def codes_of(coro) -> list[str]:
    with pytest.raises(PromotionRefused) as exc:
        await coro
    return [v.code for v in exc.value.violations]


async def fill_others(db, make, start: int, end: int, count: int) -> None:
    for _ in range(count):
        await make_promo(db, make, start, end)


async def reserved_on(db, day: date) -> int:
    (cap_day,) = await cap_days(db, day, day, NOW.date())
    return cap_day.reserved


async def snapshot_count(db, promo) -> int:
    rows = await db.scalars(select(PromotionSnapshot).where(PromotionSnapshot.promotion_id == promo.id))
    return len(rows.all())


# --- edit before the start date -------------------------------------------


@pytest.mark.asyncio
async def test_pre_start_edit_changes_dates_and_recomputes_price(db, make) -> None:
    _, promo = await make_promo(db, make, 10, 14)
    assert promo.net_price_cents == 2500
    await edit_promotion(db, promo.id, {"end_date": d(16)}, NOW)
    assert (promo.end_date, promo.days, promo.net_price_cents) == (d(16), 7, 3500)
    await edit_promotion(db, promo.id, {"start_date": d(12)}, NOW)
    assert (promo.start_date, promo.days, promo.net_price_cents) == (d(12), 5, 2500)


@pytest.mark.asyncio
async def test_pre_start_edit_changes_advertiser_and_invoice_details(db, make) -> None:
    _, promo = await make_promo(db, make)
    await edit_promotion(
        db,
        promo.id,
        {
            "advertiser_legal_name": " New OÜ ",
            "advertiser_registry_code": "87654321",
            "billing_email": "pay@example.com",
            "invoice_reference": "ER-M-2090-9",
        },
        NOW,
    )
    assert promo.advertiser_legal_name == "New OÜ"
    assert promo.advertiser_registry_code == "87654321"
    assert (promo.billing_email, promo.invoice_reference, promo.invoice_source) == (
        "pay@example.com",
        "ER-M-2090-9",
        "manual",
    )
    await edit_promotion(db, promo.id, {"billing_email": "", "invoice_reference": None}, NOW)
    assert (promo.billing_email, promo.invoice_reference, promo.invoice_source) == (None, None, None)


@pytest.mark.asyncio
async def test_pre_start_edit_refuses_bad_fields(db, make) -> None:
    _, promo = await make_promo(db, make)
    assert await codes_of(edit_promotion(db, promo.id, {"advertiser_legal_name": " "}, NOW)) == [
        PROMOTION_ERROR_ADVERTISER_NAME_REQUIRED
    ]
    assert await codes_of(edit_promotion(db, promo.id, {"advertiser_registry_code": "12"}, NOW)) == [
        PROMOTION_ERROR_INVALID_REGISTRY_CODE
    ]


@pytest.mark.asyncio
async def test_edit_with_nothing_changed_is_refused(db, make) -> None:
    _, promo = await make_promo(db, make)
    assert await codes_of(edit_promotion(db, promo.id, {"end_date": d(14)}, NOW)) == [
        PROMOTION_ERROR_NO_CHANGES
    ]


@pytest.mark.asyncio
async def test_pre_start_edit_enforces_window_rules(db, make) -> None:
    _, promo = await make_promo(db, make, 10, 14, ends_at=at_tallinn(2090, 1, 16, 22))
    assert await codes_of(edit_promotion(db, promo.id, {"end_date": d(11)}, NOW)) == [
        PROMOTION_ERROR_TOO_SHORT
    ]
    assert await codes_of(edit_promotion(db, promo.id, {"end_date": d(17)}, NOW)) == [
        PROMOTION_ERROR_ENDS_AFTER_EVENT
    ]
    # Start before tomorrow (Tallinn): NOW is 2090-01-01 10:00, tomorrow is the 2nd.
    assert PROMOTION_ERROR_STARTS_TOO_EARLY in await codes_of(
        edit_promotion(db, promo.id, {"start_date": d(1), "end_date": d(5)}, NOW)
    )


@pytest.mark.asyncio
async def test_pre_start_edit_start_lead_is_judged_at_tallinn_midnight(db, make) -> None:
    _, promo = await make_promo(db, make, 10, 14)
    before_midnight = at_tallinn(2090, 1, 8, 23, 59, 59)  # today = 8th, tomorrow = 9th
    await edit_promotion(db, promo.id, {"start_date": d(9)}, before_midnight)
    assert promo.start_date == d(9)
    # One second later it's the 9th: the Promotion starts today, so it's live.
    after_midnight = at_tallinn(2090, 1, 9, 0, 0, 1)
    assert await codes_of(edit_promotion(db, promo.id, {"start_date": d(10)}, after_midnight)) == [
        PROMOTION_ERROR_LIVE_EDIT_FIELDS
    ]


@pytest.mark.asyncio
async def test_pre_start_edit_overlap_ignores_itself_and_catches_neighbours(db, make) -> None:
    ev, promo = await make_promo(db, make, 10, 14)
    # Its own window never counts as an overlap.
    await edit_promotion(db, promo.id, {"end_date": d(13)}, NOW)
    other = await grant_promotion(db, ev, GrantRequest(d(15), d(18), "A", "12345678"), NOW)
    assert await codes_of(edit_promotion(db, promo.id, {"end_date": d(15)}, NOW)) == [
        PROMOTION_ERROR_OVERLAP
    ]
    # Back-to-back is fine.
    await edit_promotion(db, promo.id, {"end_date": d(14)}, NOW)
    assert other.start_date == d(15)


@pytest.mark.asyncio
async def test_pre_start_edit_rechecks_the_cap_excluding_itself(db, make) -> None:
    _, promo = await make_promo(db, make, 10, 13)
    await fill_others(db, make, 14, 16, PROMOTION_LIVE_CAP)
    assert await codes_of(edit_promotion(db, promo.id, {"end_date": d(14)}, NOW)) == [
        PROMOTION_ERROR_CAP_EXCEEDED
    ]
    # Shrinking inside its own window is fine even when other days are full.
    await edit_promotion(db, promo.id, {"start_date": d(11)}, NOW)
    assert promo.start_date == d(11)


@pytest.mark.asyncio
async def test_pre_start_edit_of_a_complimentary_promotion_stays_free(db, make) -> None:
    org = await make.organizer()
    ev = await make.event(submitted_by=org)
    promo = await grant_promotion(
        db,
        ev,
        GrantRequest(d(10), d(14), "A", "12345678", is_complimentary=True, complimentary_note="pilot"),
        NOW,
    )
    await edit_promotion(db, promo.id, {"end_date": d(16)}, NOW)
    assert (promo.days, promo.net_price_cents) == (7, 0)


# --- edit while live and after -------------------------------------------


@pytest.mark.asyncio
async def test_live_edit_may_only_move_the_end_date_earlier(db, make) -> None:
    _, promo = await make_promo(db, make, 10, 16, paid=True)
    live = at_tallinn(2090, 1, 12, 9)
    assert await codes_of(edit_promotion(db, promo.id, {"advertiser_legal_name": "X"}, live)) == [
        PROMOTION_ERROR_LIVE_EDIT_FIELDS
    ]
    assert await codes_of(edit_promotion(db, promo.id, {"start_date": d(11)}, live)) == [
        PROMOTION_ERROR_LIVE_EDIT_FIELDS
    ]
    assert await codes_of(edit_promotion(db, promo.id, {"end_date": d(18)}, live)) == [
        PROMOTION_ERROR_LIVE_END_MUST_SHORTEN
    ]
    await edit_promotion(db, promo.id, {"end_date": d(14)}, live)
    assert (promo.end_date, promo.days) == (d(14), 5)
    assert promo.net_price_cents == 3500  # what was paid stays on the row


@pytest.mark.asyncio
async def test_live_edit_never_touches_a_day_that_has_passed(db, make) -> None:
    _, promo = await make_promo(db, make, 10, 16, paid=True)
    just_before = at_tallinn(2090, 1, 12, 23, 59, 59)
    await edit_promotion(db, promo.id, {"end_date": d(12)}, just_before)  # ends today
    assert promo.end_date == d(12)
    _, other = await make_promo(db, make, 10, 16, paid=True)
    next_day = at_tallinn(2090, 1, 13, 0, 0, 1)
    assert await codes_of(edit_promotion(db, other.id, {"end_date": d(12)}, next_day)) == [
        PROMOTION_ERROR_LIVE_END_IN_PAST
    ]


@pytest.mark.asyncio
async def test_live_shortening_releases_the_cap_days_after_the_new_end(db, make) -> None:
    _, promo = await make_promo(db, make, 10, 16, paid=True)
    assert await reserved_on(db, d(15)) == 1
    await edit_promotion(db, promo.id, {"end_date": d(13)}, at_tallinn(2090, 1, 11))
    assert await reserved_on(db, d(15)) == 0
    assert await reserved_on(db, d(13)) == 1


@pytest.mark.asyncio
async def test_edit_refused_once_finished_or_not_holding(db, make) -> None:
    _, promo = await make_promo(db, make, 10, 14, paid=True)
    after = at_tallinn(2090, 1, 15, 0, 0, 1)
    assert await codes_of(edit_promotion(db, promo.id, {"end_date": d(12)}, after)) == [
        PROMOTION_ERROR_NOT_EDITABLE
    ]
    _, other = await make_promo(db, make, 10, 14)
    await void_promotion(db, other.id, "mistake", NOW)
    assert await codes_of(edit_promotion(db, other.id, {"end_date": d(12)}, NOW)) == [
        PROMOTION_ERROR_NOT_EDITABLE
    ]


@pytest.mark.asyncio
async def test_snapshot_after_each_edit_while_scheduled_or_live(db, make) -> None:
    _, promo = await make_promo(db, make, 10, 16, paid=True)
    assert await snapshot_count(db, promo) == 1  # mark paid
    await edit_promotion(db, promo.id, {"end_date": d(15)}, NOW)  # scheduled
    assert await snapshot_count(db, promo) == 2
    await edit_promotion(db, promo.id, {"end_date": d(13)}, at_tallinn(2090, 1, 11))  # live
    assert await snapshot_count(db, promo) == 3
    snaps = (await db.scalars(select(PromotionSnapshot).where(PromotionSnapshot.promotion_id == promo.id).order_by(PromotionSnapshot.id))).all()
    assert [s.end_date for s in snaps] == [d(16), d(15), d(13)]
    assert [s.trigger for s in snaps] == ["mark_paid", "edit", "edit"]


# --- re-point -----------------------------------------------------------------


async def group_pair(make, org):
    canon = await make.event(submitted_by=org)
    dupe = await make.event(submitted_by=org, dedup_group_id=canon.id)
    canon.dedup_group_id = canon.id
    return canon, dupe


@pytest.mark.asyncio
async def test_repoint_moves_to_a_same_owner_same_group_event(db, make) -> None:
    org = await make.organizer()
    canon, dupe = await group_pair(make, org)
    promo = await grant_promotion(db, dupe, GrantRequest(d(10), d(14), "A", "12345678"), NOW)
    await mark_paid(db, promo.id, NOW)
    await repoint_promotion(db, promo.id, canon.id, at_tallinn(2090, 1, 11))  # live
    assert promo.event_id == canon.id
    assert promo.status == PROMOTION_STATUS_PAID
    last = (await db.scalars(select(PromotionSnapshot).where(PromotionSnapshot.promotion_id == promo.id).order_by(PromotionSnapshot.id.desc()))).first()
    assert last is not None and (last.event_id, last.trigger) == (canon.id, "repoint")


@pytest.mark.asyncio
async def test_repoint_refused_for_another_owner(db, make) -> None:
    org = await make.organizer()
    canon, dupe = await group_pair(make, await make.organizer())
    promo = await grant_promotion(db, await make.event(submitted_by=org, dedup_group_id=canon.id), GrantRequest(d(10), d(14), "A", "12345678"), NOW)
    assert PROMOTION_ERROR_REPOINT_NOT_OWNER in await codes_of(repoint_promotion(db, promo.id, dupe.id, NOW))


@pytest.mark.asyncio
async def test_repoint_refused_outside_the_dedup_group(db, make) -> None:
    org = await make.organizer()
    _, promo = await make_promo(db, make, org=org)
    unrelated = await make.event(submitted_by=org)
    assert await codes_of(repoint_promotion(db, promo.id, unrelated.id, NOW)) == [
        PROMOTION_ERROR_REPOINT_NOT_SAME_GROUP
    ]


@pytest.mark.asyncio
async def test_repoint_refused_for_same_event_and_missing_target(db, make) -> None:
    ev, promo = await make_promo(db, make)
    assert await codes_of(repoint_promotion(db, promo.id, ev.id, NOW)) == [
        PROMOTION_ERROR_REPOINT_SAME_EVENT
    ]
    assert len(await codes_of(repoint_promotion(db, promo.id, 999_999_999, NOW))) == 1


@pytest.mark.asyncio
async def test_repoint_refused_when_target_ends_before_the_window_or_overlaps(db, make) -> None:
    org = await make.organizer()
    canon, dupe = await group_pair(make, org)
    promo = await grant_promotion(db, dupe, GrantRequest(d(10), d(14), "A", "12345678"), NOW)
    canon.ends_at = at_tallinn(2090, 1, 12, 22)
    await db.flush()
    assert await codes_of(repoint_promotion(db, promo.id, canon.id, NOW)) == [
        PROMOTION_ERROR_ENDS_AFTER_EVENT
    ]
    canon.ends_at = at_tallinn(2090, 2, 28, 22)
    await grant_promotion(db, canon, GrantRequest(d(12), d(16), "A", "12345678"), NOW)
    assert await codes_of(repoint_promotion(db, promo.id, canon.id, NOW)) == [PROMOTION_ERROR_OVERLAP]


# --- end early ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_early_needs_paid_and_a_reason_and_releases_the_days(db, make) -> None:
    _, promo = await make_promo(db, make, 10, 16, paid=True)
    assert await reserved_on(db, d(15)) == 1
    assert await codes_of(end_early(db, promo.id, "  ", at_tallinn(2090, 1, 12))) == [
        PROMOTION_ERROR_REASON_REQUIRED
    ]
    ended_at = at_tallinn(2090, 1, 12, 15)
    await end_early(db, promo.id, "Event moved to another venue", ended_at)
    assert promo.status == PROMOTION_STATUS_ENDED_EARLY
    assert (promo.ended_at, promo.end_note) == (ended_at, "Event moved to another venue")
    assert await reserved_on(db, d(15)) == 0
    assert await reserved_on(db, d(16)) == 0


@pytest.mark.asyncio
async def test_end_early_refused_for_unpaid_finished_and_already_ended(db, make) -> None:
    _, unpaid = await make_promo(db, make)
    assert await codes_of(end_early(db, unpaid.id, "why", NOW)) == [PROMOTION_ERROR_INVALID_TRANSITION]
    _, promo = await make_promo(db, make, 10, 14, paid=True)
    assert await codes_of(end_early(db, promo.id, "why", at_tallinn(2090, 1, 15, 0, 0, 1))) == [
        PROMOTION_ERROR_INVALID_TRANSITION
    ]
    await end_early(db, promo.id, "why", at_tallinn(2090, 1, 14, 23, 59, 59))
    assert await codes_of(end_early(db, promo.id, "again", NOW)) == [PROMOTION_ERROR_INVALID_TRANSITION]


# --- void -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_void_needs_unpaid_and_a_reason_and_releases_all_days(db, make) -> None:
    _, promo = await make_promo(db, make, 10, 14)
    assert await reserved_on(db, d(10)) == 1
    assert await codes_of(void_promotion(db, promo.id, "", NOW)) == [PROMOTION_ERROR_REASON_REQUIRED]
    await void_promotion(db, promo.id, "Unpaid after the deadline", NOW)
    assert promo.status == PROMOTION_STATUS_VOID
    assert promo.end_note == "Unpaid after the deadline"
    assert await reserved_on(db, d(10)) == 0
    assert await codes_of(void_promotion(db, promo.id, "again", NOW)) == [PROMOTION_ERROR_INVALID_TRANSITION]
    _, paid = await make_promo(db, make, paid=True)
    assert await codes_of(void_promotion(db, paid.id, "no", NOW)) == [PROMOTION_ERROR_INVALID_TRANSITION]


@pytest.mark.asyncio
async def test_a_voided_window_can_be_granted_again(db, make) -> None:
    ev, promo = await make_promo(db, make, 10, 14)
    await void_promotion(db, promo.id, "mistake", NOW)
    again = await grant_promotion(db, ev, GrantRequest(d(10), d(14), "A", "12345678"), NOW)
    assert again.id != promo.id


# --- refund -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refund_is_cumulative_and_capped_at_the_gross_price(db, make) -> None:
    _, promo = await make_promo(db, make, 10, 14, paid=True)  # 2500 net + 24% = 3100
    await record_refund(db, promo.id, 1000, "Wire back, ref 1", NOW)
    await record_refund(db, promo.id, 2100, "Wire back, ref 2", NOW)
    assert (promo.refunded_cents, promo.refund_note) == (3100, "Wire back, ref 1\nWire back, ref 2")
    assert await codes_of(record_refund(db, promo.id, 1, "more", NOW)) == [
        PROMOTION_ERROR_REFUND_EXCEEDS_PAID
    ]


@pytest.mark.asyncio
async def test_refund_validates_amount_note_and_status(db, make) -> None:
    _, promo = await make_promo(db, make, 10, 14, paid=True)
    assert await codes_of(record_refund(db, promo.id, 0, "n", NOW)) == [PROMOTION_ERROR_REFUND_AMOUNT]
    assert await codes_of(record_refund(db, promo.id, 100, " ", NOW)) == [PROMOTION_ERROR_REFUND_NOTE_REQUIRED]
    _, unpaid = await make_promo(db, make)
    assert await codes_of(record_refund(db, unpaid.id, 100, "n", NOW)) == [PROMOTION_ERROR_REFUND_NOT_PAID]
    org = await make.organizer()
    ev = await make.event(submitted_by=org)
    free = await grant_promotion(
        db, ev, GrantRequest(d(10), d(14), "A", "12345678", is_complimentary=True, complimentary_note="p"), NOW
    )
    assert await codes_of(record_refund(db, free.id, 100, "n", NOW)) == [PROMOTION_ERROR_REFUND_NOT_PAID]


@pytest.mark.asyncio
async def test_refund_allowed_after_ending_early(db, make) -> None:
    _, promo = await make_promo(db, make, 10, 14, paid=True)
    await end_early(db, promo.id, "withdrawn", at_tallinn(2090, 1, 11))
    await record_refund(db, promo.id, 1200, "unused days", at_tallinn(2090, 1, 11))
    assert promo.refunded_cents == 1200
