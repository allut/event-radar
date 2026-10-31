"""Promotion requests (#614, #615): an Organizer asks, an admin grants or
declines, and stale requests expire.

The caller owns the transaction: it adds the audit row after a command returns
and commits. Reads are bulk with a fixed query count.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.core import TALLINN_TZ
from app.constants.events import EVENT_STATUS_CANCELLED
from app._generated.shared_constants import (
    ORGANIZER_TERMS_VERSION,
    PROMOTION_ERROR_BUSINESS_ATTESTATION,
    PROMOTION_ERROR_INVALID_REGISTRY_CODE,
    PROMOTION_ERROR_NOT_PROMOTABLE,
    PROMOTION_ERROR_REGISTRY_CHECKSUM,
    PROMOTION_ERROR_REQUEST_DAILY_LIMIT,
    PROMOTION_ERROR_REQUEST_PENDING,
    PROMOTION_ERROR_TERMS_NOT_ACCEPTED,
)
from app.constants.promotions import (
    ORGANIZER_DAILY_PROMOTION_REQUEST_CAP,
    PROMOTION_ERROR_REQUEST_NOT_PENDING,
    PROMOTION_ERROR_REQUEST_OWNER_CHANGED,
    PROMOTION_GRANTED_BY_ADMIN,
    PROMOTION_REGISTRY_CODE_RE,
    PROMOTION_REQUEST_STATUS_DECLINED,
    PROMOTION_REQUEST_STATUS_EXPIRED,
    PROMOTION_REQUEST_STATUS_GRANTED,
    PROMOTION_REQUEST_STATUS_PENDING,
    PROMOTION_REQUEST_STATUS_WITHDRAWN,
)
from app.events.queries import (
    canonical_event_filter,
    event_not_ended_filter,
    public_event_filter,
)
from app.models.events import Event
from app.models.promotions import Promotion, PromotionRequest
from app.promotions.cap import lock_cap
from app.promotions.grant import GrantRequest, PromotionRefused, grant_promotion, validate_grant
from app.promotions.owners import resolve_owner_ids
from app.promotions.registry import is_valid_registry_checksum
from app.promotions.windows import RuleViolation, tallinn_today


@dataclass(frozen=True)
class RequestInput:
    start_date: date
    end_date: date
    advertiser_legal_name: str
    advertiser_registry_code: str
    billing_email: str | None
    note: str | None
    business_attested: bool
    terms_accepted: bool


async def promotable_event_ids(
    db: AsyncSession, events: Sequence[Event], now: datetime
) -> set[int]:
    """Events that are public, canonical and not ended: one query. Ownership
    and open requests are checked by the callers."""
    if not events:
        return set()
    rows = (
        await db.execute(
            select(Event.id).where(
                Event.id.in_([e.id for e in events]),
                public_event_filter(),
                canonical_event_filter(),
                event_not_ended_filter(now),
            )
        )
    ).scalars()
    return set(rows)


def registry_violations(code: str) -> list[RuleViolation]:
    if not PROMOTION_REGISTRY_CODE_RE.fullmatch(code):
        return [RuleViolation(PROMOTION_ERROR_INVALID_REGISTRY_CODE)]
    if not is_valid_registry_checksum(code):
        return [RuleViolation(PROMOTION_ERROR_REGISTRY_CHECKSUM)]
    return []


async def create_request(
    db: AsyncSession,
    organizer_id: int,
    event: Event,
    data: RequestInput,
    now: datetime,
) -> PromotionRequest:
    """Create a pending request, or raise PromotionRefused listing every rule
    broken (window, overlap and cap via `validate_grant`, registry code,
    terms, one pending per event, the daily cap). The caller has already
    checked that the Organizer owns the event."""
    violations: list[RuleViolation] = []
    if not data.terms_accepted:
        violations.append(RuleViolation(PROMOTION_ERROR_TERMS_NOT_ACCEPTED))
    if not data.business_attested:
        violations.append(RuleViolation(PROMOTION_ERROR_BUSINESS_ATTESTATION))
    violations += registry_violations(data.advertiser_registry_code)
    if not await promotable_event_ids(db, [event], now):
        violations.append(RuleViolation(PROMOTION_ERROR_NOT_PROMOTABLE))
    violations += await validate_grant(db, event, data.start_date, data.end_date, now)
    if await db.scalar(
        select(PromotionRequest.id).where(
            PromotionRequest.event_id == event.id,
            PromotionRequest.status == PROMOTION_REQUEST_STATUS_PENDING,
        )
    ):
        violations.append(RuleViolation(PROMOTION_ERROR_REQUEST_PENDING))
    day_start = now.astimezone(TALLINN_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = (
        await db.scalar(
            select(func.count())
            .select_from(PromotionRequest)
            .where(
                PromotionRequest.organizer_id == organizer_id,
                PromotionRequest.created_at >= day_start,
            )
        )
        or 0
    )
    if today_count >= ORGANIZER_DAILY_PROMOTION_REQUEST_CAP:
        violations.append(RuleViolation(PROMOTION_ERROR_REQUEST_DAILY_LIMIT))
    if violations:
        raise PromotionRefused(violations)

    request = PromotionRequest(
        event_id=event.id,
        organizer_id=organizer_id,
        start_date=data.start_date,
        end_date=data.end_date,
        advertiser_legal_name=data.advertiser_legal_name,
        advertiser_registry_code=data.advertiser_registry_code,
        billing_email=data.billing_email,
        note=data.note,
        status=PROMOTION_REQUEST_STATUS_PENDING,
        terms_version=ORGANIZER_TERMS_VERSION,
        terms_accepted_at=now,
        business_attested_at=now,
        created_at=now,
        updated_at=now,
    )
    try:
        async with db.begin_nested():
            db.add(request)
            await db.flush()
    except IntegrityError:
        # A concurrent request took the one pending slot for this event.
        raise PromotionRefused([RuleViolation(PROMOTION_ERROR_REQUEST_PENDING)]) from None
    return request


async def _load_locked(db: AsyncSession, request_id: int) -> PromotionRequest | None:
    return await db.scalar(
        select(PromotionRequest)
        .where(PromotionRequest.id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


class RequestNotFound(Exception):
    """No request with that id (or not the caller's)."""


async def withdraw_request(
    db: AsyncSession, request_id: int, organizer_id: int, now: datetime
) -> PromotionRequest:
    request = await _load_locked(db, request_id)
    if request is None or request.organizer_id != organizer_id:
        raise RequestNotFound(request_id)
    if request.status != PROMOTION_REQUEST_STATUS_PENDING:
        raise PromotionRefused([RuleViolation(PROMOTION_ERROR_REQUEST_NOT_PENDING)])
    request.status = PROMOTION_REQUEST_STATUS_WITHDRAWN
    request.resolved_at = now
    request.updated_at = now
    return request


async def grant_request(
    db: AsyncSession, request_id: int, grant: GrantRequest, now: datetime
) -> tuple[PromotionRequest, Promotion]:
    """Create the Promotion and mark the request granted in the caller's one
    transaction. The dates and fields come from the admin's form (prefilled
    from the request, editable). Refused when the request is not pending or its
    Organizer no longer owns the event. Nothing is emailed."""
    # Cap lock first, then the row lock: the sweep takes them in that order
    # too (lifecycle._load_locked), so the two can never wait on each other.
    await lock_cap(db)
    request = await _load_locked(db, request_id)
    if request is None:
        raise RequestNotFound(request_id)
    if request.status != PROMOTION_REQUEST_STATUS_PENDING:
        raise PromotionRefused([RuleViolation(PROMOTION_ERROR_REQUEST_NOT_PENDING)])
    event = await db.get(Event, request.event_id)
    assert event is not None  # events.id is RESTRICT-referenced
    promotion = await grant_promotion(db, event, grant, now)
    if promotion.organizer_id != request.organizer_id:
        raise PromotionRefused([RuleViolation(PROMOTION_ERROR_REQUEST_OWNER_CHANGED)])
    promotion.source_request_id = request.id
    request.status = PROMOTION_REQUEST_STATUS_GRANTED
    request.resolved_by = PROMOTION_GRANTED_BY_ADMIN
    request.resolved_at = now
    request.updated_at = now
    await db.flush()
    return request, promotion


async def decline_request(
    db: AsyncSession, request_id: int, reason: str, now: datetime
) -> PromotionRequest:
    request = await _load_locked(db, request_id)
    if request is None:
        raise RequestNotFound(request_id)
    if request.status != PROMOTION_REQUEST_STATUS_PENDING:
        raise PromotionRefused([RuleViolation(PROMOTION_ERROR_REQUEST_NOT_PENDING)])
    request.status = PROMOTION_REQUEST_STATUS_DECLINED
    request.decline_reason = reason
    request.resolved_by = PROMOTION_GRANTED_BY_ADMIN
    request.resolved_at = now
    request.updated_at = now
    return request


async def expire_requests(db: AsyncSession, now: datetime) -> int:
    """Expire pending requests whose event is cancelled, whose Organizer lost
    the event (claim revoked), or whose requested start date has arrived. A
    dormant claim, or dates that no longer fit the event, keep it pending. No
    email. Two owner queries plus one SELECT, whatever the row count."""
    today = tallinn_today(now)
    rows = (
        await db.execute(
            select(PromotionRequest, Event)
            .join(Event, Event.id == PromotionRequest.event_id)
            .where(PromotionRequest.status == PROMOTION_REQUEST_STATUS_PENDING)
            .with_for_update(of=PromotionRequest)
            .execution_options(populate_existing=True)
        )
    ).all()
    live = [
        e for r, e in rows if e.status != EVENT_STATUS_CANCELLED and r.start_date > today
    ]
    owners = await resolve_owner_ids(db, live, include_dormant=True) if live else {}
    expired = 0
    for request, event in rows:
        if (
            event.status == EVENT_STATUS_CANCELLED
            or request.start_date <= today
            or owners.get(event.id) != request.organizer_id
        ):
            request.status = PROMOTION_REQUEST_STATUS_EXPIRED
            request.resolved_at = now
            request.updated_at = now
            expired += 1
    return expired

