"""GET /events/{event_id} — full event detail."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.claims.lifecycle import (
    claim_status_from_claim,
    claiming_organizer_name,
    resolve_claim_for_event,
)
from app._generated.shared_constants import (
    DEFAULT_USER_LOCALE,
    PROMOTION_REF_AD,
    PROMOTION_REF_DIGEST_AD,
)
from app.constants.claims import (
    CLAIM_DISCOVERY_STATUS_PENDING,
    CLAIM_DISCOVERY_STATUS_UNCLAIMED,
)
from app.constants.events import ERROR_EVENT_NOT_FOUND
from app.constants.promotions import (
    PROMOTION_STAT_DIGEST_OPENS,
    PROMOTION_STAT_WEB_OPENS,
)
from app.constants.rate_limits import RATE_LIMIT_EVENTS_DETAIL
from app.auth.dependencies import get_optional_user
from app.db import get_db
from app.models.models import Event, User
from app.promotions.counters import record_ref_hit
from app.rate_limit import limiter
from app.routers.utils import (
    load_user_reported_events,
    load_user_signals,
    resolve_locale_param,
    serialize_event,
)
from app.events.queries import public_event_filter

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/{event_id}")
@limiter.limit(RATE_LIMIT_EVENTS_DETAIL)
async def get_event(
    event_id: int,
    request: Request,
    locale_query: str | None = Query(None, alias="locale"),
    ref: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> dict:
    """Return full event detail by ID. No auth required — events are public."""
    # joinedload, not select_events_with_classification()'s selectinload — this
    # is a single-row fetch, so one JOINed query beats the extra round trips
    # selectinload pays to stay O(1) across the bulk-listing callers that
    # share that helper (Big-O audit #5, item 2.10).
    event = await db.scalar(
        select(Event)
        .options(joinedload(Event.classification), joinedload(Event.venue))
        .where(
            Event.id == event_id,
            public_event_filter(),
        )
    )
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_EVENT_NOT_FOUND
        )

    # A slot card link carries ?ref=ad (#606): one anonymous per-day count for
    # the event's live Promotion. Never read by ranking or the persona.
    if ref == PROMOTION_REF_AD:
        await record_ref_hit(db, event.id, PROMOTION_STAT_WEB_OPENS)
    elif ref == PROMOTION_REF_DIGEST_AD:
        await record_ref_hit(db, event.id, PROMOTION_STAT_DIGEST_OPENS)

    # get_optional_user already resolved the caller (None when signed out, or
    # for an expired/invalid/revoked token — a revoked token, post logout-all,
    # must not leak locale + my_signal here) — reuse it for both locale and
    # signal hydration.
    locale = DEFAULT_USER_LOCALE
    sigs: dict[int, str] = {}
    reported: set[int] = set()
    if current_user is not None:
        locale = current_user.locale
        sigs = await load_user_signals(db, current_user.id, [event.id])
        reported = await load_user_reported_events(db, current_user.id, [event.id])

    effective_locale = resolve_locale_param(locale_query, locale)

    serialized = serialize_event(
        event,
        locale=effective_locale,
        feedback_by_event=sigs,
        reported_event_ids=reported,
    )
    # claim_status (#414) and listed_by (#419) are computed only here, not in
    # serialize_event itself — the claim CTA and "Listed by X" credit are
    # public-event-page-only, so the bulk-listing callers of serialize_event
    # (feed/explore/saved) shouldn't each pay for a per-event
    # EventSource+Claim lookup they never render, and must never surface the
    # credit either (ranking-neutrality boundary, #419).
    # A direct submission never resolves an EventSource (#445), so skip the
    # lookup entirely instead of paying for a query whose result is discarded.
    claim = (
        None
        if event.submitted_by_organizer_id is not None
        else await resolve_claim_for_event(db, event)
    )
    # (#451) A pending claim is collapsed into "unclaimed" for this public,
    # unauthenticated payload — the organizer session cookie
    # (Path=/api/organizer) never reaches this endpoint, so there is no way
    # here to tell the claimant apart from a stranger or a rival claimant.
    # The claimant-only pending pill is served by GET
    # /organizer/claims/for-event/{event_id} instead (organizer_claims.py).
    claim_status = claim_status_from_claim(claim, event)
    serialized["claim_status"] = (
        CLAIM_DISCOVERY_STATUS_UNCLAIMED
        if claim_status == CLAIM_DISCOVERY_STATUS_PENDING
        else claim_status
    )
    serialized["listed_by"] = await claiming_organizer_name(claim)
    return serialized
