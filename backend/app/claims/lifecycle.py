"""Claim lifecycle (#413): create / self-cancel / recheck / expiry-sweep,
wiring #412's standalone verification engine into real `Claim` rows. See
CONTEXT.md's Event Claiming glossary and docs/organizer-portal.md.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.claims.fienta_token import generate_claim_token
from app.claims.verification import (
    VerificationResult,
    is_trusted_claimant,
    series_claim_result,
    verify_fienta_publisher_claim,
    verify_institutional_publisher_claim,
    verify_piletilevi_claim,
)
from app.config import settings
from app.constants import (
    CLAIM_ACTIVE_STATUSES,
    CLAIM_AUTOMATED_VERIFICATION_MECHANISMS,
    CLAIM_DISCOVERY_STATUS_CLAIMED,
    CLAIM_DISCOVERY_STATUS_PENDING,
    CLAIM_DISCOVERY_STATUS_UNCLAIMED,
    CLAIM_EMAIL_SEND_CONCURRENCY,
    CLAIM_EXPIRY_DAYS,
    CLAIM_KIND_PUBLISHER,
    CLAIM_KIND_SERIES,
    CLAIM_STATUS_APPROVED,
    CLAIM_STATUS_CANCELLED,
    CLAIM_STATUS_EXPIRED,
    CLAIM_STATUS_PENDING,
    CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW,
    CLAIM_VERIFICATION_OUTCOME_AUTO_GRANT,
    ERROR_CLAIM_ALREADY_EXISTS,
    ERROR_CLAIM_NOT_CLAIMABLE,
    ERROR_CLAIM_NOT_FOUND,
    ERROR_CLAIM_NOT_PENDING,
    ERROR_DAILY_CLAIM_LIMIT,
    ERROR_EVENT_NOT_FOUND,
    LOG_EVENT_EMAIL_SEND_FAILED,
    ORGANIZER_DAILY_CLAIM_CAP,
    RESEND_TIMEOUT_SECONDS,
    SOURCE_SLUG_ESTONIA_CONCERT_HALL,
    SOURCE_SLUG_FIENTA,
    SOURCE_SLUG_KUMU,
    SOURCE_SLUG_PILETILEVI,
    TALLINN_TZ,
)
from app.email.claim_resolution import (
    send_claim_expired_email,
    send_claim_granted_email,
    send_claim_self_cancelled_email,
)
from app.ingestion.http_client import http_get
from app.models.models import Claim, Event, EventSource, Organizer
from app.routers.utils import (
    bulk_resolve_publisher_events,
    event_series_key,
    resolve_venue_name,
    serialize_event_series_key,
)

log = logging.getLogger(__name__)


class ClaimError(Exception):
    """Caller-facing claim-lifecycle failure — status_code/detail map straight
    onto an HTTPException in the router, so these functions stay importable
    (and directly testable) without a FastAPI dependency."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class ClaimTarget:
    kind: str
    publisher_id: int | None
    event_series_key: str | None


async def representative_event_source(
    db: AsyncSession, *, event_id: int | None = None, publisher_id: int | None = None
) -> EventSource | None:
    """One EventSource row to verify against — the event the organizer named
    (claim creation) or, on a recheck, the freshest listing still traced back
    to the same Publisher (a claim row itself carries no event reference)."""
    query = select(EventSource).options(
        selectinload(EventSource.source), selectinload(EventSource.publisher)
    )
    if event_id is not None:
        query = query.where(EventSource.event_id == event_id).order_by(EventSource.id)
    else:
        query = query.where(EventSource.publisher_id == publisher_id).order_by(
            EventSource.id.desc()
        )
    return await db.scalar(query.limit(1))


def resolve_claim_target(event: Event, es: EventSource) -> ClaimTarget:
    if es.publisher_id is not None:
        return ClaimTarget(CLAIM_KIND_PUBLISHER, es.publisher_id, None)
    key = serialize_event_series_key(
        event_series_key(event.title_orig, resolve_venue_name(event))
    )
    return ClaimTarget(CLAIM_KIND_SERIES, None, key)


async def active_claim_for_target(db: AsyncSession, target: ClaimTarget) -> Claim | None:
    """The pending/approved Claim already sitting on `target`, if any (#414) —
    backs both the public event page's claim_status/listed_by and the search/
    suggestions surfaces' cross-surface-retirement exclusion. Eager-loads
    `Claim.organizer` (#419) so callers needing the organizer's display name
    don't pay a second round trip."""
    if target.kind == CLAIM_KIND_PUBLISHER:
        return await db.scalar(
            select(Claim)
            .options(selectinload(Claim.organizer))
            .where(
                Claim.publisher_id == target.publisher_id,
                Claim.status.in_(CLAIM_ACTIVE_STATUSES),
            )
        )
    return await db.scalar(
        select(Claim)
        .options(selectinload(Claim.organizer))
        .where(
            Claim.event_series_key == target.event_series_key,
            Claim.status.in_(CLAIM_ACTIVE_STATUSES),
        )
    )


async def resolve_claim_for_event(db: AsyncSession, event: Event) -> Claim | None:
    """Active pending/approved Claim covering `event`, if any — shared by the
    public event page's claim_status (via claim_status_from_claim) and its
    "Listed by X" organizer-name lookup (#419) so the page pays for one
    EventSource/Claim round trip, not two."""
    es = await representative_event_source(db, event_id=event.id)
    if es is None or es.source is None:
        return None
    target = resolve_claim_target(event, es)
    return await active_claim_for_target(db, target)


async def bulk_dormant_pinned_event_ids(db: AsyncSession, events: list[Event]) -> set[int]:
    """Ids of `events` whose pins should be treated as not applying right
    now — pinned_fields is set AND the covering claim is dormant (#422).
    Batched EventSource + Claim lookup (fixed query count, not one
    resolve_claim_for_event per event) for passes that scan many events at
    once, e.g. refetch_event_details."""
    candidate_ids = [e.id for e in events if e.pinned_fields]
    if not candidate_ids:
        return set()

    es_rows = (
        await db.execute(
            select(EventSource.event_id, EventSource.publisher_id)
            .where(EventSource.event_id.in_(candidate_ids))
            .order_by(EventSource.event_id, EventSource.id)
        )
    ).all()
    es_by_event: dict[int, int | None] = {}
    for event_id, publisher_id in es_rows:
        es_by_event.setdefault(event_id, publisher_id)

    events_by_id = {e.id: e for e in events}
    publisher_ids: set[int] = set()
    series_keys: dict[str, set[int]] = {}
    for event_id, publisher_id in es_by_event.items():
        if publisher_id is not None:
            publisher_ids.add(publisher_id)
        else:
            event = events_by_id[event_id]
            key = serialize_event_series_key(
                event_series_key(event.title_orig, resolve_venue_name(event))
            )
            series_keys.setdefault(key, set()).add(event_id)

    dormant_event_ids: set[int] = set()
    if publisher_ids:
        rows = (
            await db.execute(
                select(Claim.publisher_id).where(
                    Claim.publisher_id.in_(publisher_ids),
                    Claim.status.in_(CLAIM_ACTIVE_STATUSES),
                    Claim.dormant.is_(True),
                )
            )
        ).all()
        dormant_publisher_ids = {r[0] for r in rows}
        dormant_event_ids.update(
            event_id
            for event_id, publisher_id in es_by_event.items()
            if publisher_id in dormant_publisher_ids
        )
    if series_keys:
        series_rows = (
            await db.execute(
                select(Claim.event_series_key).where(
                    Claim.event_series_key.in_(series_keys),
                    Claim.status.in_(CLAIM_ACTIVE_STATUSES),
                    Claim.dormant.is_(True),
                )
            )
        ).all()
        for (key,) in series_rows:
            dormant_event_ids.update(series_keys.get(key, set()))
    return dormant_event_ids


def claim_status_from_claim(claim: Claim | None) -> str:
    """(#414) unclaimed/pending/claimed for `claim`'s public page CTA — an
    event whose resolve_claim_for_event() came back None (never ingested,
    i.e. an organizer's own direct submission, or no active claim on its
    Publisher/Series target) is always unclaimed."""
    if claim is None:
        return CLAIM_DISCOVERY_STATUS_UNCLAIMED
    return (
        CLAIM_DISCOVERY_STATUS_CLAIMED
        if claim.status == CLAIM_STATUS_APPROVED
        else CLAIM_DISCOVERY_STATUS_PENDING
    )


async def claiming_organizer_name(claim: Claim | None) -> str | None:
    """Organizer.name for the public event page's "Listed by X" credit
    (#419) — only for an approved claim (a pending claimant isn't yet a
    verified listing maintainer) and only when the organizer has set a
    display name. Reads `claim.organizer`, eager-loaded by
    active_claim_for_target() — no extra query here."""
    if claim is None or claim.status != CLAIM_STATUS_APPROVED:
        return None
    organizer = claim.organizer
    return organizer.name if organizer is not None and organizer.name else None


async def _run_verification(
    db: AsyncSession,
    client: httpx.AsyncClient,
    *,
    kind: str,
    organizer_id: int,
    es: EventSource,
    event: Event | None,
    token: str,
) -> VerificationResult:
    if kind == CLAIM_KIND_SERIES:
        if await is_trusted_claimant(db, organizer_id):
            return VerificationResult(
                CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW,
                CLAIM_VERIFICATION_OUTCOME_AUTO_GRANT,
            )
        return series_claim_result()

    source_slug = es.source.slug if es.source else None
    try:
        if source_slug == SOURCE_SLUG_FIENTA:
            organizer_external_id = es.publisher.external_id if es.publisher else None
            if organizer_external_id is None or es.external_id is None:
                return series_claim_result()
            base_url = es.source.config.get("base_url", settings.FIENTA_BASE_URL)
            return await verify_fienta_publisher_claim(
                client, base_url, organizer_external_id, es.external_id, token
            )
        if source_slug in (SOURCE_SLUG_KUMU, SOURCE_SLUG_ESTONIA_CONCERT_HALL):
            return await verify_institutional_publisher_claim(client, source_slug, token)
        if source_slug == SOURCE_SLUG_PILETILEVI and event is not None and event.url:
            response = await http_get(client, event.url)
            return await verify_piletilevi_claim(client, response.text, event.url, token)
    except httpx.HTTPError:
        log.warning(
            "claim verification fetch failed, falling back to admin review: "
            "source=%s",
            source_slug,
        )
    # No dispatchable mechanism (e.g. a Publisher with no live listing left to
    # verify against) falls back to admin review, same as an unresolved
    # Piletilevi promoter.
    return series_claim_result()


async def _claims_created_today(db: AsyncSession, organizer_id: int) -> int:
    day_start = datetime.now(TALLINN_TZ).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return (
        await db.scalar(
            select(func.count())
            .select_from(Claim)
            .where(Claim.organizer_id == organizer_id, Claim.created_at >= day_start)
        )
        or 0
    )


async def create_claim(
    db: AsyncSession, client: httpx.AsyncClient, organizer: Organizer, event_id: int
) -> Claim:
    """Create a Publisher or Series claim for `event_id`, auto-detecting
    which kind applies from that event's resolved EventSource, then invoking
    #412's verification engine to decide auto-grant vs. admin-review routing.
    Daily-capped and duplicate/race-rejected at the DB layer (#413) — best-
    effort like ORGANIZER_DAILY_SUBMISSION_CAP: the count-then-insert has no
    row lock, so concurrent requests could exceed the cap by a small margin.
    """
    if await _claims_created_today(db, organizer.id) >= ORGANIZER_DAILY_CLAIM_CAP:
        raise ClaimError(429, ERROR_DAILY_CLAIM_LIMIT)

    event = await db.get(Event, event_id)
    if event is None:
        raise ClaimError(404, ERROR_EVENT_NOT_FOUND)

    es = await representative_event_source(db, event_id=event_id)
    if es is None or es.source is None:
        raise ClaimError(422, ERROR_CLAIM_NOT_CLAIMABLE)

    target = resolve_claim_target(event, es)
    claim = Claim(
        organizer_id=organizer.id,
        kind=target.kind,
        publisher_id=target.publisher_id,
        event_series_key=target.event_series_key,
        proof_token=generate_claim_token(),
        verification_mechanism=CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW,
        status=CLAIM_STATUS_PENDING,
    )
    db.add(claim)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise ClaimError(409, ERROR_CLAIM_ALREADY_EXISTS) from None

    result = await _run_verification(
        db,
        client,
        kind=target.kind,
        organizer_id=organizer.id,
        es=es,
        event=event,
        token=claim.proof_token,
    )
    claim.verification_mechanism = result.mechanism
    claim.verification_domain = result.domain
    auto_granted = result.outcome == CLAIM_VERIFICATION_OUTCOME_AUTO_GRANT
    if auto_granted:
        claim.status = CLAIM_STATUS_APPROVED
        claim.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    if auto_granted:
        try:
            await send_claim_granted_email(
                organizer.email, event.title_orig, "", organizer.locale, http_client=client
            )
        except Exception:
            log.error(
                "Failed to send claim-granted email (claim_id=%s)",
                claim.id,
                exc_info=True,
                extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
            )
    return claim


async def own_claim_or_404(db: AsyncSession, claim_id: int, organizer_id: int) -> Claim:
    """Read-only fetch (#415's pending screen, reloaded or opened fresh) —
    unlike `_own_pending_claim_or_404`, any status is returned so the screen
    can render its resolved (approved/expired/...) state too."""
    claim = await db.scalar(
        select(Claim).where(Claim.id == claim_id, Claim.organizer_id == organizer_id)
    )
    if claim is None:
        raise ClaimError(404, ERROR_CLAIM_NOT_FOUND)
    return claim


async def _own_pending_claim_or_404(db: AsyncSession, claim_id: int, organizer_id: int) -> Claim:
    claim = await own_claim_or_404(db, claim_id, organizer_id)
    if claim.status != CLAIM_STATUS_PENDING:
        raise ClaimError(409, ERROR_CLAIM_NOT_PENDING)
    return claim


async def get_own_claim(db: AsyncSession, organizer: Organizer, claim_id: int) -> Claim:
    """GET-by-id for #415's pending screen."""
    return await own_claim_or_404(db, claim_id, organizer.id)


async def cancel_claim(db: AsyncSession, organizer: Organizer, claim_id: int) -> Claim:
    """Self-cancel a pending claim, freeing its Publisher/Series immediately —
    the row's status alone gates the partial unique indexes, so no other
    cleanup is needed."""
    claim = await _own_pending_claim_or_404(db, claim_id, organizer.id)
    claim.status = CLAIM_STATUS_CANCELLED
    claim.resolved_at = datetime.now(timezone.utc)
    await db.commit()

    # Local import: app.claims.pinning imports representative_event_source
    # from this module, so a module-level import here would deadlock the
    # two modules' load order.
    from app.claims.pinning import representative_event_for_claim

    try:
        event = await representative_event_for_claim(db, claim)
        await send_claim_self_cancelled_email(
            organizer.email, event.title_orig if event else None, organizer.locale
        )
    except Exception:
        log.error(
            "Failed to send claim-self-cancelled email (claim_id=%s)",
            claim_id,
            exc_info=True,
            extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
        )
    return claim


async def recheck_claim(
    db: AsyncSession, client: httpx.AsyncClient, organizer: Organizer, claim_id: int
) -> Claim:
    """Organizer-triggered "check now": re-run verification for a pending
    automated-mechanism claim. Always bumps last_checked_at, whatever the
    outcome — resets the inactivity clock expire_stale_claims sweeps against,
    since the organizer is actively engaged. Admin-review claims (including
    every Series claim not fast-tracked by Trusted-claimant status) have
    nothing to re-verify and are rejected the same as an already-resolved one.
    """
    claim = await _own_pending_claim_or_404(db, claim_id, organizer.id)
    if claim.verification_mechanism not in CLAIM_AUTOMATED_VERIFICATION_MECHANISMS:
        raise ClaimError(409, ERROR_CLAIM_NOT_PENDING)

    es = await representative_event_source(db, publisher_id=claim.publisher_id)
    if es is None or es.source is None:
        raise ClaimError(422, ERROR_CLAIM_NOT_CLAIMABLE)
    event = await db.get(Event, es.event_id)

    result = await _run_verification(
        db,
        client,
        kind=claim.kind,
        organizer_id=organizer.id,
        es=es,
        event=event,
        token=claim.proof_token,
    )
    claim.verification_mechanism = result.mechanism
    claim.verification_domain = result.domain
    claim.last_checked_at = datetime.now(timezone.utc)
    auto_granted = result.outcome == CLAIM_VERIFICATION_OUTCOME_AUTO_GRANT
    if auto_granted:
        claim.status = CLAIM_STATUS_APPROVED
        claim.resolved_at = claim.last_checked_at
    await db.commit()
    if auto_granted:
        try:
            await send_claim_granted_email(
                organizer.email, event.title_orig if event else None, "", organizer.locale,
                http_client=client,
            )
        except Exception:
            log.error(
                "Failed to send claim-granted email (claim_id=%s)",
                claim.id,
                exc_info=True,
                extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
            )
    return claim


async def _send_claim_expiry_emails(db: AsyncSession, expired: list[Claim]) -> None:
    """One expiry email per row in ``expired`` (#421) — bulk-loads organizers
    and Publisher-kind claims' representative event in two fixed queries
    (bulk_resolve_publisher_events, shared with admin_list_claims), rather
    than a per-row SELECT. A Series-kind claim gets no title resolved here
    for the same cost reason admin_list_claims skips it for lists — the
    email falls back to generic wording (app.email.claim_resolution._target_label).
    Called after the sweep's own commit (mirrors send_report_resolution_emails).
    The whole body is exception-guarded: the expiry status transition is
    already durable at this point, so a bulk-load failure here must not
    surface as a failed sweep (which would make expire_stale_claims re-raise
    into _scheduled's failure log while masking that the DB mutation
    actually succeeded) — it only costs this run's notifications, which the
    next sweep cannot retry since these rows are no longer PENDING."""
    if not expired:
        return

    try:
        organizer_ids = {claim.organizer_id for claim in expired}
        organizers = (
            await db.scalars(select(Organizer).where(Organizer.id.in_(organizer_ids)))
        ).all()
        organizers_by_id = {o.id: o for o in organizers}

        publisher_ids = {
            claim.publisher_id
            for claim in expired
            if claim.kind == CLAIM_KIND_PUBLISHER and claim.publisher_id is not None
        }
        event_by_publisher = await bulk_resolve_publisher_events(db, publisher_ids)
    except Exception:
        log.error(
            "Failed to bulk-load claim-expiry email recipients (%d expired claims)",
            len(expired),
            exc_info=True,
            extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
        )
        return

    semaphore = asyncio.Semaphore(CLAIM_EMAIL_SEND_CONCURRENCY)

    async def _send_one(claim: Claim, http_client: httpx.AsyncClient) -> None:
        organizer = organizers_by_id.get(claim.organizer_id)
        if organizer is None:
            return
        event = (
            event_by_publisher.get(claim.publisher_id)
            if claim.publisher_id is not None
            else None
        )
        async with semaphore:
            try:
                await send_claim_expired_email(
                    organizer.email,
                    event.title_orig if event else None,
                    organizer.locale,
                    http_client=http_client,
                )
            except Exception:
                log.error(
                    "Failed to send claim-expired email (claim_id=%s)",
                    claim.id,
                    exc_info=True,
                    extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
                )

    async with httpx.AsyncClient(timeout=RESEND_TIMEOUT_SECONDS) as http_client:
        await asyncio.gather(
            *(_send_one(claim, http_client) for claim in expired),
            return_exceptions=True,
        )


async def expire_stale_claims(db: AsyncSession) -> dict:
    """Sweep job (#413/#421): expire a pending automated-mechanism claim that
    has gone CLAIM_EXPIRY_DAYS without a recheck, then notify each claimant.
    Admin-review claims (Series, and any Publisher claim that fell back to
    it) never expire on their own — excluded by the verification_mechanism
    filter, not just the status one. Commits internally (mirrors
    build_daily_feeds) so the expiry emails below reflect only durably
    expired rows — app/main.py wires this job with commit=False."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=CLAIM_EXPIRY_DAYS)
    result = await db.execute(
        update(Claim)
        .where(
            Claim.status == CLAIM_STATUS_PENDING,
            Claim.verification_mechanism.in_(CLAIM_AUTOMATED_VERIFICATION_MECHANISMS),
            Claim.last_checked_at < cutoff,
        )
        .values(status=CLAIM_STATUS_EXPIRED, resolved_at=func.now())
        .returning(Claim)
    )
    expired = list(result.scalars().all())
    await db.commit()
    await _send_claim_expiry_emails(db, expired)
    return {"expired": len(expired)}
