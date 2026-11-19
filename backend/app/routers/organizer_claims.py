"""Organizer event-claiming endpoints (#413) — the first slice of #409 to
actually create/mutate a `claims` row. See app/claims/lifecycle.py for the
business logic these endpoints just wire up to HTTP.
"""

import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.email import send_magic_link
from app.auth.tokens import (
    generate_organizer_claim_link_token,
    generate_organizer_session_token,
    hash_token,
    organizer_magic_ttl_seconds,
    verify_organizer_claim_link_token,
)
from app.claims.lifecycle import (
    ClaimError,
    cancel_claim,
    create_claim,
    get_own_claim,
    own_claim_for_event,
    own_claim_or_404,
    recheck_claim,
)
from app.claims.pinning import bulk_resolve_series_events
from app._generated.shared_constants import (
    CLAIM_ERROR_CODE_JUSTIFICATION_REQUIRED,
    CLAIM_EVENTS_PAGE_SIZE,
    CLAIM_KIND_PUBLISHER,
    CLAIM_STATUS_APPROVED,
    CLAIM_STATUS_DECLINED,
    CLAIM_STATUS_PENDING,
    CLAIM_STATUS_REVOKED,
    ORGANIZER_OWN_CLAIMS_PAGE_SIZE,
    PAGINATION_MAX_OFFSET,
    VALID_LOCALES,
)
from app.constants.admin import ADMIN_ACTION_REVOKE_CLAIM
from app.constants.auth import (
    AUTH_TOKEN_MAX_LEN,
    DETAIL_MAGIC_LINK_SENT,
    ERROR_MAGIC_LINK_CONSUMED,
    ERROR_MAGIC_LINK_EXPIRED,
    ERROR_MAGIC_LINK_INVALID,
    ORGANIZER_SESSION_COOKIE_NAME,
    ORGANIZER_SESSION_COOKIE_PATH,
    ORGANIZER_SESSION_TTL_DAYS,
)
from app.constants.claims import (
    CLAIM_AUTOMATED_VERIFICATION_MECHANISMS,
    CLAIM_EVENTS_MAX_PAGE_SIZE,
    CLAIM_JUSTIFICATION_MAX_CHARS,
    ERROR_CLAIM_EVENTS_NOT_PUBLISHER,
    ORGANIZER_CLAIM_VERIFY_PATH,
    ORGANIZER_OWN_CLAIMS_MAX_PAGE_SIZE,
)
from app.constants.core import SECONDS_PER_DAY
from app.constants.events import ERROR_EVENT_NOT_FOUND
from app.constants.http import HTTP_TIMEOUT_SECONDS
from app.constants.log_events import LOG_EVENT_AUTH_FAILED
from app.constants.organizer import ERROR_ORGANIZER_NOT_FOUND
from app.constants.ranking import PAGINATION_MIN_LIMIT, PAGINATION_MIN_OFFSET
from app.constants.rate_limits import (
    RATE_LIMIT_AUTH_REQUEST_LINK,
    RATE_LIMIT_AUTH_VERIFY,
    RATE_LIMIT_BROWSE,
    RATE_LIMIT_CLAIM,
)
from app.db import get_db
from app.models.audit import AdminAction
from app.models.claims import Claim
from app.models.events import Event
from app.models.organizers import Organizer, OrganizerMagicLink
from app.rate_limit import limiter
from app.auth.dependencies import get_current_organizer
from app.promotions.organizer_view import promotion_flags_for
from app.claims.dns_txt import claim_dns_record_name
from app.routers.utils.serializers import resolve_locale_param, serialize_event
from app.routers.utils.auth import (
    get_or_create_organizer,
    recent_unused_link_exists,
    set_session_cookie,
)
from app.claims.target_resolution import (
    bulk_resolve_publisher_events,
    publisher_claim_event_ids,
)
from app.events.localize import resolve_title
from app.events.queries import (
    public_event_filter,
    select_events_with_classification,
)
from app.auth.utils import mark_organizer_verified, mask_email

log = logging.getLogger(__name__)
router = APIRouter(prefix="/organizer/claims", tags=["organizer-claims"])


class CreateClaimBody(BaseModel):
    event_id: int
    # Required only when the event resolves to a Series claim (#428) — the
    # kind isn't known until create_claim resolves it server-side, so this
    # stays optional here and create_claim itself raises a ClaimError coded
    # CLAIM_ERROR_CODE_JUSTIFICATION_REQUIRED when it's needed and missing.
    justification: str | None = Field(default=None, max_length=CLAIM_JUSTIFICATION_MAX_CHARS)


class ClaimLinkRequestBody(BaseModel):
    email: EmailStr
    event_id: int
    locale: str | None = None


class ClaimLinkVerifyBody(BaseModel):
    token: str = Field(max_length=AUTH_TOKEN_MAX_LEN)


def _api_status(status_value: str) -> str:
    """A still-existing row's CLAIM_STATUS_REVOKED always means declined, not
    revoked — see CLAIM_STATUS_DECLINED's docstring in app/constants/claims.py (#447)."""
    return CLAIM_STATUS_DECLINED if status_value == CLAIM_STATUS_REVOKED else status_value


def _serialize(claim: Claim) -> dict:
    """#415's pending screen picks its variant off `verification_mechanism`
    and never has to know CLAIM_DNS_TXT_RECORD_LABEL itself — the DNS
    instructions are pre-assembled here from `verification_domain` (#412's
    resolved KUMU/ECH/Piletilevi-promoter domain, persisted at verify time)."""
    dns_record_name = claim_dns_record_name(
        claim.verification_mechanism, claim.verification_domain
    )
    return {
        "id": claim.id,
        "kind": claim.kind,
        "publisher_id": claim.publisher_id,
        "event_series_key": claim.event_series_key,
        "status": _api_status(claim.status),
        "dormant": claim.dormant,
        "verification_mechanism": claim.verification_mechanism,
        "verification_domain": claim.verification_domain,
        "dns_record_name": dns_record_name,
        "dns_record_value": claim.proof_token,
        "proof_token": claim.proof_token,
        "justification": claim.justification,
        "can_recheck": (
            claim.status == CLAIM_STATUS_PENDING
            and claim.verification_mechanism in CLAIM_AUTOMATED_VERIFICATION_MECHANISMS
        ),
        "created_at": claim.created_at,
        "last_checked_at": claim.last_checked_at,
        "resolved_at": claim.resolved_at,
    }


def _revoked_tombstone(claim_id: int, admin_action: AdminAction) -> dict:
    """Stand-in for `_serialize()` when a claim's row is gone (admin revoke
    deletes it outright, #442) — built from the AdminAction audit row
    admin_revoke_claim() writes, so ClaimPending's already-built
    CLAIM_STATUS_REVOKED branch (#446) has something to render instead of a
    generic 404."""
    return {
        "id": claim_id,
        "kind": admin_action.result.get("kind"),
        "publisher_id": None,
        "event_series_key": None,
        "status": CLAIM_STATUS_REVOKED,
        "dormant": False,
        "verification_mechanism": None,
        "verification_domain": None,
        "dns_record_name": None,
        "dns_record_value": "",
        "proof_token": "",
        "justification": None,
        "can_recheck": False,
        "created_at": None,
        "last_checked_at": None,
        "resolved_at": admin_action.created_at,
    }


async def _get_own_claim_or_tombstone(
    db: AsyncSession, organizer: Organizer, claim_id: int
) -> dict:
    """`get_own_claim` first; on 404, check whether that id was a claim of
    *this* organizer's that an admin revoked (row deleted) rather than one
    that never existed — see `_revoked_tombstone`."""
    try:
        claim = await get_own_claim(db, organizer, claim_id)
    except ClaimError as exc:
        admin_action = await db.scalar(
            select(AdminAction)
            .where(
                AdminAction.action == ADMIN_ACTION_REVOKE_CLAIM,
                AdminAction.target == str(claim_id),
            )
            .order_by(AdminAction.created_at.desc())
            .limit(1)
        )
        if admin_action is None or admin_action.result.get("organizer_id") != organizer.id:
            raise HTTPException(status_code=exc.status_code, detail=exc.http_detail) from exc
        return _revoked_tombstone(claim_id, admin_action)
    return _serialize(claim)


@router.post("", status_code=status.HTTP_201_CREATED)
@limiter.limit(RATE_LIMIT_CLAIM)
async def create_own_claim(
    body: CreateClaimBody,
    request: Request,
    response: Response,
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        try:
            claim, created = await create_claim(
                db, client, current_organizer, body.event_id, body.justification
            )
        except ClaimError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.http_detail) from exc
    if not created:
        # (#448) Re-claiming your own already-pending target returns that
        # existing claim rather than a new row — 200, not 201, since nothing
        # was created. The frontend navigates to the returned claim's pending
        # page either way.
        response.status_code = status.HTTP_200_OK
    return _serialize(claim)


@router.post("/{claim_id}/cancel")
@limiter.limit(RATE_LIMIT_CLAIM)
async def cancel_own_claim(
    claim_id: int,
    request: Request,
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        claim = await cancel_claim(db, current_organizer, claim_id)
    except ClaimError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.http_detail) from exc
    return _serialize(claim)


@router.post("/{claim_id}/recheck")
@limiter.limit(RATE_LIMIT_CLAIM)
async def recheck_own_claim(
    claim_id: int,
    request: Request,
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        try:
            claim = await recheck_claim(db, client, current_organizer, claim_id)
        except ClaimError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.http_detail) from exc
    return _serialize(claim)


@router.post("/request-link", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_AUTH_REQUEST_LINK)
async def request_claim_link(
    body: ClaimLinkRequestBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Sign-in link for an organizer who wants to claim `event_id` but isn't
    signed in yet — the claim intent (event_id) is encoded into the token
    itself (generate_organizer_claim_link_token), not a query param or
    sessionStorage, so it round-trips even when the link is opened on a
    different device/session. Always returns 200 (anti-enumeration), mirrors
    organizer_auth.py::request_organizer_magic_link."""
    email = body.email.lower()
    requested_locale = body.locale if body.locale in VALID_LOCALES else None
    organizer = await get_or_create_organizer(db, email, requested_locale)
    email_locale = requested_locale or organizer.locale

    if await recent_unused_link_exists(
        db,
        OrganizerMagicLink,
        OrganizerMagicLink.organizer_id,
        organizer.id,
        organizer_magic_ttl_seconds(),
    ):
        return {"detail": DETAIL_MAGIC_LINK_SENT}

    signed_token, token_hash, expires_at = generate_organizer_claim_link_token(
        organizer.id, body.event_id
    )
    db.add(
        OrganizerMagicLink(
            organizer_id=organizer.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
    )
    await db.commit()

    try:
        await send_magic_link(
            email, signed_token, email_locale, verify_path=ORGANIZER_CLAIM_VERIFY_PATH
        )
    except Exception:
        log.exception("Failed to send organizer claim link to %s", mask_email(email))
        # Do not surface email errors to caller — link is in DB, organizer can retry.

    return {"detail": DETAIL_MAGIC_LINK_SENT}


@router.post("/verify-link")
@limiter.limit(RATE_LIMIT_AUTH_VERIFY)
async def verify_claim_link(
    request: Request,
    body: ClaimLinkVerifyBody,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Verify a claim-intent magic link: signs the organizer in (same session
    cookie as organizer_auth.py::verify_organizer_magic_link) and immediately
    creates the claim the link was minted for."""
    token = body.token
    try:
        organizer_id, event_id = verify_organizer_claim_link_token(token)
    except SignatureExpired:
        log.warning(
            "organizer claim-link verify failed: expired",
            extra={"event": LOG_EVENT_AUTH_FAILED},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=ERROR_MAGIC_LINK_EXPIRED
        )
    except (BadSignature, KeyError):
        # KeyError: a validly-signed token with no "eid" claim — e.g. a plain
        # organizer sign-in token (generate_organizer_magic_token), which
        # shares this salt but was never minted with claim intent. Treated
        # the same as a bad signature rather than a 500 (#413 review finding).
        log.warning(
            "organizer claim-link verify failed: bad-signature",
            extra={"event": LOG_EVENT_AUTH_FAILED},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=ERROR_MAGIC_LINK_INVALID
        )

    token_hash = hash_token(token)
    now = datetime.now(timezone.utc)

    # Atomic UPDATE — same TOCTOU-closing pattern as organizer_auth.py::verify_organizer_magic_link.
    result = await db.execute(
        update(OrganizerMagicLink)
        .where(
            OrganizerMagicLink.token_hash == token_hash,
            OrganizerMagicLink.organizer_id == organizer_id,
            OrganizerMagicLink.used_at.is_(None),
            OrganizerMagicLink.expires_at > now,
        )
        .values(used_at=now)
        .returning(OrganizerMagicLink.organizer_id)
    )
    if result.fetchone() is None:
        log.warning(
            "organizer claim-link verify failed: already-used or not-found",
            extra={"event": LOG_EVENT_AUTH_FAILED},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=ERROR_MAGIC_LINK_CONSUMED
        )
    await db.commit()

    organizer = await db.get(Organizer, organizer_id)
    if organizer is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=ERROR_ORGANIZER_NOT_FOUND
        )

    if mark_organizer_verified(organizer):
        await db.commit()

    session_token = generate_organizer_session_token(
        organizer.id, organizer.session_token_version
    )
    set_session_cookie(
        response,
        name=ORGANIZER_SESSION_COOKIE_NAME,
        token=session_token,
        path=ORGANIZER_SESSION_COOKIE_PATH,
        ttl_seconds=ORGANIZER_SESSION_TTL_DAYS * SECONDS_PER_DAY,
    )

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        try:
            claim, _created = await create_claim(db, client, organizer, event_id)
        except ClaimError as exc:
            if exc.code == CLAIM_ERROR_CODE_JUSTIFICATION_REQUIRED:
                # (#428 review finding) This listing resolves to a Series
                # claim, which the signed-out email-capture step never had a
                # chance to collect a justification for — the magic link is
                # already single-use-consumed above, so raising here would
                # strand the organizer with no way to retry. Sign-in has
                # already succeeded (the cookie is already set on `response`
                # above), so return that success without a claim rather than
                # raise — raising here would discard those headers and lose
                # the sign-in too. The frontend sends the organizer to
                # their dashboard, now signed in, to search for the event
                # again and claim it with a justification via
                # ClaimEventPicker.
                return {
                    "organizer": {
                        "id": organizer.id,
                        "email": organizer.email,
                        "locale": organizer.locale,
                    },
                    "claim": None,
                    "needs_justification": True,
                }
            raise HTTPException(status_code=exc.status_code, detail=exc.http_detail) from exc

    return {
        "organizer": {
            "id": organizer.id,
            "email": organizer.email,
            "locale": organizer.locale,
        },
        "claim": _serialize(claim),
    }


def _serialize_own_claim_summary(
    claim: Claim, event: Event | None, locale: str
) -> dict:
    return {
        "id": claim.id,
        "kind": claim.kind,
        "status": _api_status(claim.status),
        "verification_mechanism": claim.verification_mechanism,
        "dormant": claim.dormant,
        "publisher_name": claim.publisher.name if claim.publisher is not None else None,
        "event_id": event.id if event is not None else None,
        "event_title": resolve_title(event, locale) if event is not None else None,
        "created_at": claim.created_at,
        "resolved_at": claim.resolved_at,
    }


@router.get("")
@limiter.limit(RATE_LIMIT_BROWSE)
async def list_own_claims(
    request: Request,
    locale: str | None = Query(None),
    limit: int = Query(
        ORGANIZER_OWN_CLAIMS_PAGE_SIZE,
        ge=PAGINATION_MIN_LIMIT,
        le=ORGANIZER_OWN_CLAIMS_MAX_PAGE_SIZE,
    ),
    offset: int = Query(
        PAGINATION_MIN_OFFSET, ge=PAGINATION_MIN_OFFSET, le=PAGINATION_MAX_OFFSET
    ),
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The Your claims page (#446, paged by spec #551): every claim this
    organizer has ever made (any status), newest first, with the paging
    envelope (total/limit/offset/has_more) on every page. `pending_count`
    backs the dashboard's "You have N claims (M pending)" summary.

    Per page, Publisher claims bulk-resolve in two fixed queries and Series
    claims share one bounded scan (bulk_resolve_series_events), so the
    query count stays fixed whatever the page holds."""
    own = Claim.organizer_id == current_organizer.id
    total, pending_count = (
        await db.execute(
            select(
                func.count(Claim.id),
                func.count(Claim.id).filter(Claim.status == CLAIM_STATUS_PENDING),
            ).where(own)
        )
    ).one()
    total = total or 0
    claims = (
        await db.scalars(
            select(Claim)
            .options(selectinload(Claim.publisher))
            .where(own)
            # id breaks created_at ties so a row never repeats or vanishes
            # between pages.
            .order_by(Claim.created_at.desc(), Claim.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    effective_locale = resolve_locale_param(locale, current_organizer.locale)
    publisher_ids = {c.publisher_id for c in claims if c.publisher_id is not None}
    events_by_publisher = await bulk_resolve_publisher_events(db, publisher_ids)
    series_keys = {
        c.event_series_key
        for c in claims
        if c.kind != CLAIM_KIND_PUBLISHER and c.event_series_key is not None
    }
    events_by_series_key = await bulk_resolve_series_events(db, series_keys)

    results = []
    for claim in claims:
        if claim.kind == CLAIM_KIND_PUBLISHER:
            event = (
                events_by_publisher.get(claim.publisher_id)
                if claim.publisher_id is not None
                else None
            )
        else:
            event = (
                events_by_series_key.get(claim.event_series_key)
                if claim.event_series_key is not None
                else None
            )
        results.append(_serialize_own_claim_summary(claim, event, effective_locale))
    return {
        "claims": results,
        "total": total,
        "pending_count": pending_count or 0,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(claims) < total,
    }


@router.get("/for-event/{event_id}")
@limiter.limit(RATE_LIMIT_BROWSE)
async def get_claim_for_event(
    event_id: int,
    request: Request,
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """(#451) The caller's own active claim on `event_id`'s target, or
    null — backs the public event page's claimant-only pending pill.
    GET /events/{id} can't make this distinction itself (the organizer
    session cookie, Path=/api/organizer, never reaches it), so an
    organizer-authed page makes this separate, organizer-scoped call
    instead. Same published/canonical bar as the public page
    (public_event_filter) so id-probing can't distinguish a draft/cancelled
    event from a nonexistent one."""
    event = await db.scalar(select(Event).where(Event.id == event_id, public_event_filter()))
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_EVENT_NOT_FOUND
        )
    claim = await own_claim_for_event(db, current_organizer, event)
    return {"claim": _serialize(claim) if claim is not None else None}


# {claim_id} must not shadow organizer_claim_search.py's /search and
# /suggestions. Starlette matches path routes in registration order and
# {claim_id} has no int converter in the path itself, so this holds only
# because main.py includes that router first; the test in
# tests/test_route_guards.py guards the order.
@router.get("/{claim_id}")
@limiter.limit(RATE_LIMIT_BROWSE)
async def get_claim(
    claim_id: int,
    request: Request,
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """#415's pending screen: fetch a claim's current state on direct
    navigation/reload (create/verify-link already return it inline for the
    same-request landing case). Falls back to a revoked tombstone (#446)
    when the row itself is gone."""
    return await _get_own_claim_or_tombstone(db, current_organizer, claim_id)


async def _own_publisher_claim_or_404(
    db: AsyncSession, claim_id: int, organizer_id: int
) -> Claim:
    """Publisher-claim-only guard (#436) — a Series claim carries no
    `EventSource.publisher_id` to bulk-match events against, and an
    unapproved claim has no granted coverage yet, so both 404 the same way
    a nonexistent claim id would rather than returning a misleading empty
    page."""
    try:
        claim = await own_claim_or_404(db, claim_id, organizer_id)
    except ClaimError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.http_detail) from exc
    if (
        claim.kind != CLAIM_KIND_PUBLISHER
        or claim.publisher_id is None
        or claim.status != CLAIM_STATUS_APPROVED
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_CLAIM_EVENTS_NOT_PUBLISHER
        )
    return claim


@router.get("/{claim_id}/events")
@limiter.limit(RATE_LIMIT_BROWSE)
async def list_claim_events(
    claim_id: int,
    request: Request,
    limit: int = Query(
        CLAIM_EVENTS_PAGE_SIZE, ge=PAGINATION_MIN_LIMIT, le=CLAIM_EVENTS_MAX_PAGE_SIZE
    ),
    offset: int = Query(
        PAGINATION_MIN_OFFSET, ge=PAGINATION_MIN_OFFSET, le=PAGINATION_MAX_OFFSET
    ),
    locale: str | None = Query(None),
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Every event this approved Publisher claim currently covers (#436) —
    not just the one representative_event_for_claim() picks for the
    single-event editor. Bulk-loaded off one EventSource.publisher_id match
    (fixed query count regardless of row count), with the paging envelope
    (total/limit/offset/has_more) on every page for the numbered pager
    (spec #551), sized for organizer-portal use via CLAIM_EVENTS_PAGE_SIZE."""
    claim = await _own_publisher_claim_or_404(db, claim_id, current_organizer.id)
    effective_locale = resolve_locale_param(locale, current_organizer.locale)

    covered = Event.id.in_(publisher_claim_event_ids(claim.publisher_id))

    total = (await db.scalar(select(func.count(Event.id)).where(covered))) or 0
    stmt = (
        select_events_with_classification()
        .where(covered)
        # id breaks starts_at ties so a row never repeats or vanishes
        # between pages.
        .order_by(Event.starts_at.desc(), Event.id.desc())
        .limit(limit)
        .offset(offset)
    )
    events = (await db.scalars(stmt)).all()
    flags = await promotion_flags_for(db, current_organizer.id, events)

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(events) < total,
        "events": [
            {
                **serialize_event(e, locale=effective_locale),
                "status": e.status,
                **flags.get(e.id, {}),
            }
            for e in events
        ],
    }
