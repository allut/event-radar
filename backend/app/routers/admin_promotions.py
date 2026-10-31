"""Admin promotion console — cap strip, trust panel, complaints, grant and the lifecycle commands."""

import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_admin
from app._generated.shared_constants import (
    ADMIN_PROMOTIONS_PAGE_SIZE,
    PAGINATION_MAX_OFFSET,
)
from app.constants.admin import (
    ADMIN_ACTION_PROMOTION_CLEAR_RESTRICTION,
    ADMIN_ACTION_PROMOTION_COMPLAINT,
    ADMIN_ACTION_PROMOTION_EDIT,
    ADMIN_ACTION_PROMOTION_END,
    ADMIN_ACTION_PROMOTION_GRANT,
    ADMIN_ACTION_PROMOTION_MARK_PAID,
    ADMIN_ACTION_PROMOTION_REFUND,
    ADMIN_ACTION_PROMOTION_REPOINT,
    ADMIN_ACTION_PROMOTION_VOID,
)
from app.constants.log_events import LOG_EVENT_EMAIL_SEND_FAILED
from app.constants.ranking import (
    PAGINATION_MIN_LIMIT,
    PAGINATION_MIN_OFFSET,
)
from app.constants.promotions import (
    PROMOTION_LIVE_CAP,
    ADMIN_PROMOTIONS_MAX_PAGE_SIZE,
    ERROR_PROMOTION_ADVERTISER_LEGAL_NAME_REQUIRED,
    ERROR_PROMOTION_FIELD_NOT_NULLABLE,
    ERROR_PROMOTION_INVALID_STATE,
    ERROR_PROMOTION_NOT_FOUND,
    ERROR_PROMOTION_NOTE_REQUIRED,
    ERROR_PROMOTION_SLOTS_STILL_ENABLED,
    PROMOTION_ADVERTISER_NAME_MAX_CHARS,
    PROMOTION_BILLING_EMAIL_MAX_CHARS,
    PROMOTION_COMPLAINANT_MAX_CHARS,
    PROMOTION_COMPLAINT_SOURCE_OTHER,
    PROMOTION_COMPLAINT_SOURCES,
    PROMOTION_COMPLAINT_TARGET,
    PROMOTION_END_REASON_FEATURE_WITHDRAWN,
    PROMOTION_WITHDRAWN_NOTE,
    PROMOTION_WITHDRAWN_REFUND_NOTE,
    PROMOTION_CHECKOUT_ERROR_MESSAGES,
    PROMOTION_ERROR_REFUND_PROVIDER,
    PROMOTION_INVOICE_REFERENCE_MAX_LEN,
    PROMOTION_NOTE_MAX_CHARS,
    PROMOTION_NULLABLE_TEXT_FIELDS,
    PROMOTION_REGISTRY_CODE_MAX_LEN,
    VALID_PROMOTION_STATES,
)
from app.constants.rate_limits import (
    RATE_LIMIT_ADMIN,
    RATE_LIMIT_BROWSE,
    RATE_LIMIT_SCOPE_ADMIN_READ,
)
from app.config import settings
from app.db import AsyncSessionLocal
from app.email.promotion_notice import (
    send_promotion_ended_email,
    send_promotion_void_email,
)
from app.integrations.payments import PaymentGateway, PaymentProviderError
from app.integrations.providers import get_payment_gateway
from app.promotions.cap import cap_strip
from app.promotions.grant import (
    GrantRequest,
    PromotionRefused,
    grant_promotion,
    validate_grant,
)
from app.promotions.lifecycle import (
    clear_restriction,
    PromotionNotFound,
    edit_promotion,
    end_early,
    mark_paid,
    record_refund,
    repoint_promotion,
    void_promotion,
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
from app.promotions.withdraw import WithdrawResult, withdraw_all, withdraw_promotion
from app.models.events import Event
from app.models.organizers import Organizer
from app.models.promotions import Promotion
from app.rate_limit import limiter
from app.routers.utils import PromotionGrantBody, promotion_refusal
from app.routers.utils.admin import event_or_404, log_admin_action, run_admin_job
from app.events.localize import (
    resolve_title,
)

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


def _withdraw_audit(result: WithdrawResult) -> dict:
    return {
        **_promotion_audit_summary(result.promotion),
        "reason": PROMOTION_WITHDRAWN_NOTE,
        "end_reason": PROMOTION_END_REASON_FEATURE_WITHDRAWN,
        "unused_days": result.unused_days,
        "refund_cents": result.refund_cents,
    }


def _withdraw_guard() -> None:
    """Withdraw only runs after the slots flag is off (step two of the
    runbook), so no ad is still being served while Promotions end."""
    if settings.PROMOTIONS_SLOTS_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=ERROR_PROMOTION_SLOTS_STILL_ENABLED
        )


def _withdraw_summary(result: WithdrawResult) -> dict:
    return {
        "id": result.promotion.id,
        "event_id": result.promotion.event_id,
        "unused_days": result.unused_days,
        "refund_cents": result.refund_cents,
        "refunded_cents": result.promotion.refunded_cents,
    }


async def _audit_withdrawals(db: AsyncSession, results: list[WithdrawResult]) -> list[Callable[[], None]]:
    emits: list[Callable[[], None]] = []
    for item in results:
        emits.append(
            log_admin_action(
                db, ADMIN_ACTION_PROMOTION_END, item.promotion.id, _withdraw_audit(item)
            )
        )
        if item.refund_cents > 0:
            emits.append(
                log_admin_action(
                    db,
                    ADMIN_ACTION_PROMOTION_REFUND,
                    item.promotion.id,
                    {**_promotion_audit_summary(item.promotion), "amount_cents": item.refund_cents,
                     "note": PROMOTION_WITHDRAWN_REFUND_NOTE},
                )
            )
    return emits


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
    _withdraw_guard()

    async def _run() -> dict:
        now = now_tallinn()
        async with AsyncSessionLocal() as db:
            outcome = await withdraw_all(db, now, gateway)
            emits = await _audit_withdrawals(db, outcome.withdrawn)
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
                    await _notify_promotion_ended(
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


class _PromotionMarkPaidBody(BaseModel):
    invoice_reference: str | None = Field(default=None, max_length=PROMOTION_INVOICE_REFERENCE_MAX_LEN)


class _PromotionEditBody(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    advertiser_legal_name: str | None = Field(
        default=None, max_length=PROMOTION_ADVERTISER_NAME_MAX_CHARS
    )
    advertiser_registry_code: str | None = Field(default=None, max_length=PROMOTION_REGISTRY_CODE_MAX_LEN)
    billing_email: EmailStr | None = Field(
        default=None, max_length=PROMOTION_BILLING_EMAIL_MAX_CHARS
    )
    invoice_reference: str | None = Field(default=None, max_length=PROMOTION_INVOICE_REFERENCE_MAX_LEN)


class _PromotionRepointBody(BaseModel):
    event_id: int


class _PromotionClearBody(BaseModel):
    note: str = Field(max_length=PROMOTION_NOTE_MAX_CHARS)


class _PromotionReasonBody(BaseModel):
    reason: str = Field(max_length=PROMOTION_NOTE_MAX_CHARS)


class _PromotionRefundBody(BaseModel):
    amount_cents: int
    note: str = Field(max_length=PROMOTION_NOTE_MAX_CHARS)


def _promotion_audit_summary(promotion: Promotion) -> dict:
    return {
        "promotion_id": promotion.id,
        "event_id": promotion.event_id,
        "organizer_id": promotion.organizer_id,
        "status": promotion.status,
        "start_date": promotion.start_date.isoformat(),
        "end_date": promotion.end_date.isoformat(),
        "days": promotion.days,
        "net_price_cents": promotion.net_price_cents,
        "refunded_cents": promotion.refunded_cents,
    }


async def _notify_promotion_ended(
    organizer: Organizer, event: Event, promotion: Promotion, reason: str, voided: bool
) -> None:
    """Email the Organizer the reason, in their locale. Best-effort after the
    commit: a failed send is logged, never undoes the command."""
    send = send_promotion_void_email if voided else send_promotion_ended_email
    try:
        await send(
            organizer.email,
            resolve_title(event, organizer.locale),
            promotion.start_date,
            promotion.end_date,
            reason,
            organizer.locale,
        )
    except Exception:
        log.error(
            "Failed to send promotion %s email (promotion_id=%s)",
            "void" if voided else "ended",
            promotion.id,
            exc_info=True,
            extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
        )


async def _run_promotion_command(
    promotion_id: int,
    action: str,
    command: Callable[[AsyncSession, datetime], Awaitable[Promotion]],
    audit_extra: dict,
    notify_reason: str | None = None,
    voided: bool = False,
) -> dict:
    async def _run() -> dict:
        now = now_tallinn()
        async with AsyncSessionLocal() as db:
            try:
                promotion = await command(db, now)
            except PromotionNotFound:
                await db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_PROMOTION_NOT_FOUND
                ) from None
            except PromotionRefused as refused:
                await db.rollback()
                raise promotion_refusal(refused) from None
            except PaymentProviderError:
                await db.rollback()
                log.error("Stripe refused a Promotion command (%s)", action, exc_info=True)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=PROMOTION_CHECKOUT_ERROR_MESSAGES[PROMOTION_ERROR_REFUND_PROVIDER],
                ) from None
            emit_admin_log = log_admin_action(
                db, action, promotion.id, {**_promotion_audit_summary(promotion), **audit_extra}
            )
            payload = await promotion_detail(db, promotion, now)
            organizer = await db.get(Organizer, promotion.organizer_id)
            event = await db.get(Event, promotion.event_id)
            await db.commit()
            emit_admin_log()
            if notify_reason is not None and organizer is not None and event is not None:
                await _notify_promotion_ended(organizer, event, promotion, notify_reason, voided)
            return payload

    return await run_admin_job(f"Promotion {action}", _run())


# ---------------------------------------------------------------------------
# Promotion lifecycle (#601): detail and commands. Each command runs under the
# cap lock, writes its audit row in the same transaction and returns the
# refreshed detail payload.
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


@router.post("/promotions/{promotion_id}/mark-paid", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_mark_promotion_paid(
    promotion_id: int, body: _PromotionMarkPaidBody, request: Request
) -> dict:
    """`unpaid -> paid`, any time before the start date (Tallinn). Optionally
    records the invoice reference (`ER-M-` series)."""
    return await _run_promotion_command(
        promotion_id,
        ADMIN_ACTION_PROMOTION_MARK_PAID,
        lambda db, now: mark_paid(db, promotion_id, now, body.invoice_reference),
        {"invoice_reference": (body.invoice_reference or "").strip() or None},
    )


@router.patch("/promotions/{promotion_id}", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_edit_promotion(
    promotion_id: int, body: _PromotionEditBody, request: Request
) -> dict:
    """Edit the fields sent. Before the start date: dates (cap rechecked,
    price recomputed), advertiser details and invoice reference. While live:
    only an earlier `end_date`. Send `billing_email` / `invoice_reference` as
    null to clear them."""
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        if value is None and key not in PROMOTION_NULLABLE_TEXT_FIELDS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=ERROR_PROMOTION_FIELD_NOT_NULLABLE.format(key=key),
            )
    logged = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in changes.items()}
    return await _run_promotion_command(
        promotion_id,
        ADMIN_ACTION_PROMOTION_EDIT,
        lambda db, now: edit_promotion(db, promotion_id, changes, now),
        {"changes": logged},
    )


@router.post("/promotions/{promotion_id}/repoint", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_repoint_promotion(
    promotion_id: int, body: _PromotionRepointBody, request: Request
) -> dict:
    """Move the Promotion to another event the same Organizer owns in the same
    dedup group."""
    return await _run_promotion_command(
        promotion_id,
        ADMIN_ACTION_PROMOTION_REPOINT,
        lambda db, now: repoint_promotion(db, promotion_id, body.event_id, now),
        {"to_event_id": body.event_id},
    )


@router.post("/promotions/{promotion_id}/clear-restriction", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_clear_promotion_restriction(
    promotion_id: int, body: _PromotionClearBody, request: Request
) -> dict:
    """Clear the event's current Promotion restriction on a scheduled or live
    Promotion (a required note); the fill gate then lets it resume. 422 when
    the event is not restricted or the note is empty. Covers only that restriction."""
    return await _run_promotion_command(
        promotion_id,
        ADMIN_ACTION_PROMOTION_CLEAR_RESTRICTION,
        lambda db, now: clear_restriction(db, promotion_id, body.note, now),
        {"note": body.note.strip()},
    )


@router.post("/promotions/{promotion_id}/end", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_end_promotion(
    promotion_id: int, body: _PromotionReasonBody, request: Request
) -> dict:
    """`paid -> ended_early` with a required reason, which is emailed to the
    Organizer in their locale. Releases every cap day."""
    reason = body.reason.strip()
    return await _run_promotion_command(
        promotion_id,
        ADMIN_ACTION_PROMOTION_END,
        lambda db, now: end_early(db, promotion_id, reason, now),
        {"reason": reason},
        notify_reason=reason,
    )


@router.post("/promotions/{promotion_id}/withdraw", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_withdraw_promotion(
    promotion_id: int, request: Request, gateway: PaymentGateway = Depends(get_payment_gateway)
) -> dict:
    """Withdraw (#620) one paid Promotion: `ended_early` with
    `feature_withdrawn` and a full refund of its unused days, emailed to the
    Organizer. A card-paid one is refunded through Stripe (502 when Stripe
    refuses; it stays paid). 409 `slots_still_enabled` while the slots flag is
    on. Returns the refreshed detail."""
    _withdraw_guard()

    async def _run() -> dict:
        now = now_tallinn()
        async with AsyncSessionLocal() as db:
            try:
                item = await withdraw_promotion(db, promotion_id, now, gateway)
            except PromotionNotFound:
                await db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_PROMOTION_NOT_FOUND
                ) from None
            except PromotionRefused as refused:
                await db.rollback()
                raise promotion_refusal(refused) from None
            except PaymentProviderError:
                await db.rollback()
                log.error("Stripe refused a Promotion withdraw refund", exc_info=True)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=PROMOTION_CHECKOUT_ERROR_MESSAGES[PROMOTION_ERROR_REFUND_PROVIDER],
                ) from None
            emits = await _audit_withdrawals(db, [item])
            payload = await promotion_detail(db, item.promotion, now)
            organizer = await db.get(Organizer, item.promotion.organizer_id)
            event = await db.get(Event, item.promotion.event_id)
            await db.commit()
            for emit in emits:
                emit()
            if organizer is not None and event is not None:
                await _notify_promotion_ended(
                    organizer, event, item.promotion, PROMOTION_WITHDRAWN_NOTE, False
                )
            return payload

    return await run_admin_job("Withdraw promotion", _run())


@router.post("/promotions/{promotion_id}/void", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_void_promotion(
    promotion_id: int, body: _PromotionReasonBody, request: Request
) -> dict:
    """`unpaid -> void` with a required reason, which is emailed to the
    Organizer in their locale. Releases every cap day."""
    reason = body.reason.strip()
    return await _run_promotion_command(
        promotion_id,
        ADMIN_ACTION_PROMOTION_VOID,
        lambda db, now: void_promotion(db, promotion_id, reason, now),
        {"reason": reason},
        notify_reason=reason,
        voided=True,
    )


@router.post("/promotions/{promotion_id}/refund", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_record_promotion_refund(
    promotion_id: int,
    body: _PromotionRefundBody,
    request: Request,
    gateway: PaymentGateway = Depends(get_payment_gateway),
) -> dict:
    """Refund gross `amount_cents` with a required note. Cumulative, capped at
    what was charged. An off-platform payment is only recorded; a Stripe-paid
    one is issued (credit note and card refund in one Stripe call), 502 when
    Stripe refuses and nothing is recorded. `refund_prefill` on the detail
    holds the suggested amount."""
    return await _run_promotion_command(
        promotion_id,
        ADMIN_ACTION_PROMOTION_REFUND,
        lambda db, now: record_refund(
            db, promotion_id, body.amount_cents, body.note, now, gateway=gateway
        ),
        {"amount_cents": body.amount_cents, "note": body.note.strip()},
    )
