"""Admin promotion console — cap strip, trust panel, complaints, withdraw-all, list, grant and detail.

The per-Promotion lifecycle commands live in admin_promotion_commands.py."""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.auth.dependencies import get_current_admin
from app._generated.shared_constants import (
    ADMIN_PROMOTIONS_PAGE_SIZE,
    PAGINATION_MAX_OFFSET,
)
from app.constants.admin import (
    ADMIN_ACTION_PROMOTION_COMPLAINT,
    ADMIN_ACTION_PROMOTION_GRANT,
)
from app.constants.ranking import (
    PAGINATION_MIN_LIMIT,
    PAGINATION_MIN_OFFSET,
)
from app.constants.promotions import (
    PROMOTION_LIVE_CAP,
    ADMIN_PROMOTIONS_MAX_PAGE_SIZE,
    ERROR_PROMOTION_ADVERTISER_LEGAL_NAME_REQUIRED,
    ERROR_PROMOTION_INVALID_STATE,
    ERROR_PROMOTION_NOT_FOUND,
    ERROR_PROMOTION_NOTE_REQUIRED,
    PROMOTION_COMPLAINANT_MAX_CHARS,
    PROMOTION_COMPLAINT_SOURCE_OTHER,
    PROMOTION_COMPLAINT_SOURCES,
    PROMOTION_COMPLAINT_TARGET,
    PROMOTION_WITHDRAWN_NOTE,
    PROMOTION_NOTE_MAX_CHARS,
    VALID_PROMOTION_STATES,
)
from app.constants.rate_limits import (
    RATE_LIMIT_ADMIN,
    RATE_LIMIT_BROWSE,
    RATE_LIMIT_SCOPE_ADMIN_READ,
)
from app.db import AsyncSessionLocal
from app.integrations.payments import PaymentGateway
from app.integrations.providers import get_payment_gateway
from app.promotions.cap import cap_strip
from app.promotions.grant import (
    GrantRequest,
    PromotionRefused,
    grant_promotion,
    validate_grant,
)
from app.promotions.views import (
    grant_context,
    daily_stats_table,
    list_promotions,
    promotion_detail,
    load_daily_stats,
    serialize_promotion,
    validation_payload,
)
from app.promotions.trust import trust_panel
from app.promotions.windows import now_tallinn, tallinn_today
from app.promotions.withdraw import WithdrawResult, withdraw_all
from app.models.events import Event
from app.models.organizers import Organizer
from app.models.promotions import Promotion
from app.rate_limit import limiter
from app.routers.utils.promotions import (
    PromotionGrantBody,
    audit_withdrawals,
    notify_promotion_ended,
    promotion_refusal,
    withdraw_guard,
)
from app.routers.utils.admin import event_or_404, log_admin_action, run_admin_job

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")


# ---------------------------------------------------------------------------
# Promotions (#600): JSON API for the cap strip, the list and the grant form.
# ---------------------------------------------------------------------------


@router.get("/promotions/cap-strip", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_BROWSE, scope=RATE_LIMIT_SCOPE_ADMIN_READ)
async def admin_promotion_cap_strip(request: Request) -> dict:
    """The 14-day cap strip: reserved, paid and live Promotions per Tallinn
    day, starting today, each out of the cap."""
    today = tallinn_today(now_tallinn())
    async with AsyncSessionLocal() as db:
        days = await cap_strip(db, today)
    return {
        "today": today.isoformat(),
        "cap": PROMOTION_LIVE_CAP,
        "days": [d.as_dict() for d in days],
    }


@router.get("/promotions/trust", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_BROWSE, scope=RATE_LIMIT_SCOPE_ADMIN_READ)
async def admin_promotion_trust(request: Request) -> dict:
    """The Trust panel (#620): reports on promoted events, Email ad consent
    withdrawals by source, slot dislikes and logged complaints for the rolling
    4 weeks and since launch, next to live Promotions, slots served and current
    consenters. Read only; nothing here flips a flag."""
    async with AsyncSessionLocal() as db:
        return await trust_panel(db, now_tallinn())


class _PromotionComplaintBody(BaseModel):
    note: str = Field(min_length=1, max_length=PROMOTION_NOTE_MAX_CHARS)
    source: str = PROMOTION_COMPLAINT_SOURCE_OTHER
    complainant: str | None = Field(default=None, max_length=PROMOTION_COMPLAINANT_MAX_CHARS)

    @field_validator("source")
    @classmethod
    def _known_source(cls, value: str) -> str:
        if value not in PROMOTION_COMPLAINT_SOURCES:
            raise ValueError(f"source must be one of {PROMOTION_COMPLAINT_SOURCES}")
        return value


@router.post(
    "/promotions/complaints",
    dependencies=[Depends(get_current_admin)],
    status_code=status.HTTP_201_CREATED,
)
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_log_promotion_complaint(
    body: _PromotionComplaintBody, request: Request
) -> dict:
    """Log a complaint about the ads that arrived by email or the contact form.
    Audited as `promotion_complaint` and counted in the Trust panel. `note` is
    required; `complainant` (who, so two complaints from one person count
    once) is optional."""
    note = body.note.strip()
    if not note:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ERROR_PROMOTION_NOTE_REQUIRED,
        )
    complainant = (body.complainant or "").strip() or None

    async def _run() -> dict:
        async with AsyncSessionLocal() as db:
            result = {"note": note, "source": body.source, "complainant": complainant}
            emit_admin_log = log_admin_action(
                db, ADMIN_ACTION_PROMOTION_COMPLAINT, PROMOTION_COMPLAINT_TARGET, result
            )
            await db.commit()
            emit_admin_log()
            return {"logged": True, **result}

    return await run_admin_job("Log promotion complaint", _run())



def _withdraw_summary(result: WithdrawResult) -> dict:
    return {
        "id": result.promotion.id,
        "event_id": result.promotion.event_id,
        "unused_days": result.unused_days,
        "refund_cents": result.refund_cents,
        "refunded_cents": result.promotion.refunded_cents,
    }



@router.post("/promotions/withdraw-all", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_withdraw_all_promotions(
    request: Request, gateway: PaymentGateway = Depends(get_payment_gateway)
) -> dict:
    """Withdraw (#620): end every paid, unfinished Promotion with
    `feature_withdrawn` and record a full refund of its unused days. 409
    `slots_still_enabled` while `PROMOTIONS_SLOTS_ENABLED` is on. A Promotion
    that cannot be ended is listed in `skipped` (a card refund Stripe refused
    has code `refund_provider_failed`); the rest still end."""
    withdraw_guard()

    async def _run() -> dict:
        now = now_tallinn()
        async with AsyncSessionLocal() as db:
            outcome = await withdraw_all(db, now, gateway)
            emits = await audit_withdrawals(db, outcome.withdrawn)
            promotions = [item.promotion for item in outcome.withdrawn]
            organizers = {
                o.id: o
                for o in await db.scalars(
                    select(Organizer).where(Organizer.id.in_({p.organizer_id for p in promotions}))
                )
            }
            events = {
                e.id: e
                for e in await db.scalars(
                    select(Event).where(Event.id.in_({p.event_id for p in promotions}))
                )
            }
            mails = [(p, organizers.get(p.organizer_id), events.get(p.event_id)) for p in promotions]
            await db.commit()
            for emit in emits:
                emit()
            for promotion, organizer, event in mails:
                if organizer is not None and event is not None:
                    await notify_promotion_ended(
                        organizer, event, promotion, PROMOTION_WITHDRAWN_NOTE, False
                    )
            return {
                "withdrawn": [_withdraw_summary(item) for item in outcome.withdrawn],
                "skipped": outcome.skipped,
            }

    return await run_admin_job("Withdraw promotions", _run())


@router.get("/promotions", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_BROWSE, scope=RATE_LIMIT_SCOPE_ADMIN_READ)
async def admin_list_promotions(
    request: Request,
    state: str | None = Query(None),
    limit: int = Query(
        ADMIN_PROMOTIONS_PAGE_SIZE,
        ge=PAGINATION_MIN_LIMIT,
        le=ADMIN_PROMOTIONS_MAX_PAGE_SIZE,
    ),
    offset: int = Query(
        PAGINATION_MIN_OFFSET, ge=PAGINATION_MIN_OFFSET, le=PAGINATION_MAX_OFFSET
    ),
) -> dict:
    """Promotions, newest window first. `state` (scheduled, live, finished) is
    computed from the window and today's Tallinn date, never stored."""
    if state is not None and state not in VALID_PROMOTION_STATES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ERROR_PROMOTION_INVALID_STATE,
        )
    now = now_tallinn()
    today = tallinn_today(now)
    async with AsyncSessionLocal() as db:
        items, total = await list_promotions(db, state=state, limit=limit, offset=offset, now=now)
    return {
        "today": today.isoformat(),
        "promotions": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
    }


@router.get("/promotions/{promotion_id}/daily-stats", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_BROWSE, scope=RATE_LIMIT_SCOPE_ADMIN_READ)
async def admin_promotion_daily_stats(promotion_id: int, request: Request) -> dict:
    """The per-day delivery table for one Promotion: anonymous counts for each
    complete window day (today is left out), zeros where nothing was counted."""
    today = tallinn_today(now_tallinn())
    async with AsyncSessionLocal() as db:
        promotion = await db.get(Promotion, promotion_id)
        if promotion is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_PROMOTION_NOT_FOUND
            )
        stored = (await load_daily_stats(db, [promotion_id]))[promotion_id]
    return {
        "promotion_id": promotion_id,
        "today": today.isoformat(),
        "days": daily_stats_table(promotion, stored, today),
    }


@router.get(
    "/events/{event_id}/promotion-context", dependencies=[Depends(get_current_admin)]
)
@limiter.shared_limit(RATE_LIMIT_BROWSE, scope=RATE_LIMIT_SCOPE_ADMIN_READ)
async def admin_promotion_context(event_id: int, request: Request) -> dict:
    """Grant form context: resolved owner (null = cannot grant), prefill,
    window rules, pricing and the event's existing Promotions."""
    async with AsyncSessionLocal() as db:
        event = await event_or_404(db, event_id)
        return await grant_context(db, event, now_tallinn())


@router.get(
    "/events/{event_id}/promotions/validate", dependencies=[Depends(get_current_admin)]
)
@limiter.shared_limit(RATE_LIMIT_BROWSE, scope=RATE_LIMIT_SCOPE_ADMIN_READ)
async def admin_validate_promotion_dates(
    event_id: int,
    request: Request,
    start_date: date,
    end_date: date,
    is_complimentary: bool = False,
) -> dict:
    """Live date validation for the grant form: every window, overlap and cap
    problem for the candidate window, plus the price. Writes nothing."""
    async with AsyncSessionLocal() as db:
        event = await event_or_404(db, event_id)
        violations = await validate_grant(db, event, start_date, end_date, now_tallinn())
    return validation_payload(start_date, end_date, violations, is_complimentary)


@router.post(
    "/events/{event_id}/promotions",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_admin)],
)
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_grant_promotion(
    event_id: int, body: PromotionGrantBody, request: Request
) -> dict:
    """Grant a Promotion for an owned event. Refused (409 no_owner / overlap /
    cap_exceeded, 422 for window and field rules) with `detail.errors` listing
    every rule broken. The cap check and insert run under one advisory lock,
    and the PROMOTION_GRANT audit row rides the same transaction."""
    grant_request = GrantRequest(
        start_date=body.start_date,
        end_date=body.end_date,
        advertiser_legal_name=body.advertiser_legal_name.strip(),
        advertiser_registry_code=body.advertiser_registry_code.strip(),
        billing_email=str(body.billing_email) if body.billing_email else None,
        is_complimentary=body.is_complimentary,
        complimentary_note=body.complimentary_note,
        invoice_reference=(body.invoice_reference or "").strip() or None,
        restriction_clearance_confirmed=body.restriction_clearance_confirmed,
        restriction_clearance_note=body.restriction_clearance_note,
    )
    if not grant_request.advertiser_legal_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ERROR_PROMOTION_ADVERTISER_LEGAL_NAME_REQUIRED,
        )

    async def _run() -> dict:
        now = now_tallinn()
        async with AsyncSessionLocal() as db:
            event = await event_or_404(db, event_id)
            try:
                promotion = await grant_promotion(db, event, grant_request, now)
            except PromotionRefused as refused:
                await db.rollback()
                raise promotion_refusal(refused) from None
            result = {
                "id": promotion.id,
                "event_id": promotion.event_id,
                "organizer_id": promotion.organizer_id,
                "status": promotion.status,
                "start_date": promotion.start_date.isoformat(),
                "end_date": promotion.end_date.isoformat(),
                "days": promotion.days,
                "net_price_cents": promotion.net_price_cents,
                "vat_rate_percent": str(promotion.vat_rate_percent),
                "is_complimentary": promotion.is_complimentary,
                "complimentary_note": promotion.complimentary_note,
                "invoice_reference": promotion.invoice_reference,
                "advertiser_legal_name": promotion.advertiser_legal_name,
                "advertiser_registry_code": promotion.advertiser_registry_code,
                "restriction_cleared": promotion.restriction_cleared,
                "restriction_clearance_note": promotion.restriction_clearance_note,
            }
            emit_admin_log = log_admin_action(
                db, ADMIN_ACTION_PROMOTION_GRANT, promotion.id, result
            )
            organizer = await db.get(Organizer, promotion.organizer_id)
            payload = serialize_promotion(
                promotion,
                event.title_orig,
                organizer.name if organizer else None,
                tallinn_today(now),
            )
            await db.commit()
            emit_admin_log()
            return payload

    return await run_admin_job("Grant promotion", _run())



# ---------------------------------------------------------------------------
# Promotion lifecycle (#601): detail. The commands are in
# admin_promotion_commands.py.
# ---------------------------------------------------------------------------


@router.get("/promotions/{promotion_id}", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_BROWSE, scope=RATE_LIMIT_SCOPE_ADMIN_READ)
async def admin_promotion_detail(promotion_id: int, request: Request) -> dict:
    """One Promotion with its event, content snapshots (newest first), audit
    trail, available commands and re-point candidates."""
    async with AsyncSessionLocal() as db:
        promotion = await db.get(Promotion, promotion_id)
        if promotion is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_PROMOTION_NOT_FOUND
            )
        return await promotion_detail(db, promotion, now_tallinn())
