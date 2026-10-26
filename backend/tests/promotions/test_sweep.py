"""Automatic lifecycle (#602): void at the start date, end on cancellation or
claim revocation. The clock is frozen around Tallinn midnight."""

from contextlib import asynccontextmanager

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy import select

from app.constants.admin import (
    ADMIN_ACTION_PROMOTION_SYSTEM_END,
    ADMIN_ACTION_PROMOTION_SYSTEM_VOID,
)
from app.constants.claims import CLAIM_STATUS_REVOKED
from app.constants.promotions import (
    PROMOTION_STATUS_ENDED_EARLY,
    PROMOTION_STATUS_PAID,
    PROMOTION_STATUS_UNPAID,
    PROMOTION_STATUS_VOID,
)
from app.models.models import AdminAction
from app.promotions import sweep as sweep_module
from app.promotions.grant import GrantRequest, grant_promotion
from app.promotions.lifecycle import mark_paid
from app.promotions.sweep import sweep_promotions
from tests.promotions.conftest import NOW, at_tallinn, d
from tests.promotions.test_lifecycle_commands import make_promo

BEFORE_MIDNIGHT = at_tallinn(2090, 1, 9, 23, 59, 59)
MIDNIGHT = at_tallinn(2090, 1, 10, 0, 0, 0)
LIVE = at_tallinn(2090, 1, 11, 12)


async def audit_rows(db, promotion_id):
    return (
        await db.scalars(select(AdminAction).where(AdminAction.target == str(promotion_id)))
    ).all()


@pytest.mark.asyncio
async def test_unpaid_stays_until_midnight_then_voids_silently(db, make, sent) -> None:
    _, promo = await make_promo(db, make, 10, 14)
    await sweep_promotions(db, BEFORE_MIDNIGHT)
    assert promo.status == PROMOTION_STATUS_UNPAID
    result = await sweep_promotions(db, MIDNIGHT)
    assert promo.status == PROMOTION_STATUS_VOID
    assert promo.ended_at == MIDNIGHT
    assert result["voided"] == 1
    rows = await audit_rows(db, promo.id)
    assert [r.action for r in rows] == [ADMIN_ACTION_PROMOTION_SYSTEM_VOID]
    assert rows[0].result["actor"] == "system"
    assert sent == []


@pytest.mark.asyncio
async def test_void_sweep_leaves_paid_alone(db, make, sent) -> None:
    _, paid = await make_promo(db, make, 10, 14, paid=True)
    await sweep_promotions(db, MIDNIGHT)
    assert paid.status == PROMOTION_STATUS_PAID


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason", ["organizer_retract", "admin_retract", "report_takedown", "source_gone"]
)
async def test_cancellation_ends_paid_with_carried_reason(db, make, sent, reason) -> None:
    org = await make.organizer()
    ev, promo = await make_promo(db, make, 10, 14, paid=True, org=org)
    ev.status = "cancelled"
    ev.cancellation_reason = reason
    await db.flush()
    await sweep_promotions(db, LIVE)
    assert promo.status == PROMOTION_STATUS_ENDED_EARLY
    assert promo.end_reason == reason
    assert promo.ended_at == LIVE
    assert [r.action for r in await audit_rows(db, promo.id)] == [
        ADMIN_ACTION_PROMOTION_SYSTEM_END
    ]
    assert [to for to, _ in sent] == [org.email]


@pytest.mark.asyncio
async def test_revoked_claim_ends_with_claim_revoked(db, make, sent) -> None:
    org = await make.organizer()
    ev = await make.event()
    claim = await make.publisher_claim(ev, org)
    _, promo = await make_promo_for(db, ev, org)
    claim.status = CLAIM_STATUS_REVOKED
    await db.flush()
    await sweep_promotions(db, LIVE)
    assert promo.status == PROMOTION_STATUS_ENDED_EARLY
    assert promo.end_reason == "claim_revoked"
    assert [to for to, _ in sent] == [org.email]


@pytest.mark.asyncio
async def test_dormant_claim_keeps_promotion_paid(db, make, sent) -> None:
    org = await make.organizer()
    ev = await make.event()
    claim = await make.publisher_claim(ev, org)
    _, promo = await make_promo_for(db, ev, org)
    claim.dormant = True
    await db.flush()
    await sweep_promotions(db, LIVE)
    assert promo.status == PROMOTION_STATUS_PAID
    assert sent == []


@pytest.mark.asyncio
async def test_lost_dedup_collision_keeps_promotion_paid(db, make, sent) -> None:
    ev, promo = await make_promo(db, make, 10, 14, paid=True)
    winner = await make.event()
    ev.dedup_group_id = winner.id
    await db.flush()
    await sweep_promotions(db, LIVE)
    assert promo.status == PROMOTION_STATUS_PAID


@pytest.mark.asyncio
async def test_sweep_query_count_is_fixed(db, make, sent) -> None:
    async def seed(n: int) -> None:
        for _ in range(n):
            ev, promo = await make_promo(db, make, 10, 14, paid=True)
            ev.status = "cancelled"
            ev.cancellation_reason = "admin_retract"
            await make_promo(db, make, 20, 24, org=await make.organizer())
        await db.flush()

    statements: list[str] = []

    def count(conn, cursor, statement, *a):
        statements.append(statement)

    async def measured(now) -> int:
        conn = db.sync_session.connection()
        sa_event.listen(conn, "before_cursor_execute", count)
        try:
            statements.clear()
            await sweep_promotions(db, now)
            return len(statements)
        finally:
            sa_event.remove(conn, "before_cursor_execute", count)

    await seed(1)
    one = await measured(at_tallinn(2090, 1, 21, 12))
    await seed(4)
    many = await measured(at_tallinn(2090, 1, 21, 12))
    assert one == many


@pytest.mark.asyncio
async def test_ended_emails_share_one_client(db, make, monkeypatch) -> None:
    """Every ended-early email in one sweep goes out on one shared Resend client."""
    clients: list[object] = []

    @asynccontextmanager
    async def one_client():
        client = object()
        clients.append(client)
        yield client

    calls: list[tuple[str, object]] = []

    async def fake(to_email, event_title, start, end, reason, locale, http_client=None):
        calls.append((to_email, http_client))

    monkeypatch.setattr(sweep_module, "resend_http_client", one_client)
    monkeypatch.setattr(sweep_module, "send_promotion_ended_email", fake)
    orgs = [await make.organizer() for _ in range(3)]
    for org in orgs:
        ev, _ = await make_promo(db, make, 10, 14, paid=True, org=org)
        ev.status = "cancelled"
        ev.cancellation_reason = "admin_retract"
    await db.flush()
    await sweep_promotions(db, LIVE)
    assert len(clients) == 1
    assert sorted(to for to, _ in calls) == sorted(o.email for o in orgs)
    assert all(client is clients[0] for _, client in calls)


async def make_promo_for(db, ev, org):
    promo = await grant_promotion(db, ev, GrantRequest(d(10), d(14), "Acme OÜ", "12345678"), NOW)
    await mark_paid(db, promo.id, NOW)
    return ev, promo
