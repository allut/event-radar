"""Claim lifecycle (#413): create / self-cancel / recheck / expiry-sweep,
wiring #412's standalone verification engine into real `Claim` rows. See
CONTEXT.md's Event Claiming glossary and docs/organizer-portal.md.
"""

import asyncio
import logging
from http import HTTPStatus
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import and_, func, or_, select, true, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.claims.fienta_token import generate_claim_token
from app.claims.target_resolution import (
    ClaimTarget,
    ClaimTargetError,
    bulk_resolve_publisher_events,
    resolve_claim_target_live,
)
from app.claims.verification import (
    VerificationResult,
    series_claim_result,
    verify_fienta_publisher_claim,
    verify_institutional_publisher_claim,
    verify_piletilevi_claim,
)
from app.config import settings
from app.constants import (
    CLAIM_ACTIVE_STATUSES,
    CLAIM_ADMIN_REVIEW_EXPIRY_DAYS,
    CLAIM_AUTOMATED_VERIFICATION_MECHANISMS,
    CLAIM_DISCOVERY_STATUS_CLAIMED,
    CLAIM_DISCOVERY_STATUS_NOT_CLAIMABLE,
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
    CLAIM_STATUS_REVOKED,
    CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW,
    CLAIM_VERIFICATION_OUTCOME_AUTO_GRANT,
    ERROR_CLAIM_JUSTIFICATION_REQUIRED,
    ERROR_CLAIM_NOT_CLAIMABLE,
    ERROR_CLAIM_NOT_FOUND,
    ERROR_CLAIM_NOT_PENDING,
    ERROR_CLAIM_OWN_SUBMISSION,
    ERROR_CLAIM_TARGET_ALREADY_APPROVED,
    ERROR_DAILY_CLAIM_LIMIT,
    ERROR_EVENT_NOT_FOUND,
    EVENT_STATUS_PUBLISHED,
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
    send_claim_declined_email,
    send_claim_expired_email,
    send_claim_granted_email,
    send_claim_self_cancelled_email,
)
from app.ingestion.http_client import http_get_stored_url
from app.models.models import Claim, Event, EventSource, Organizer
from app.events.localize import resolve_title
from app.events.venue import resolve_venue_name
from app.events.queries import event_series_key, serialize_event_series_key

log = logging.getLogger(__name__)


class ClaimError(Exception):
    """Caller-facing claim-lifecycle failure — status_code/detail map straight
    onto an HTTPException in the router, so these functions stay importable
    (and directly testable) without a FastAPI dependency."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


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
    """Cheap, HTTP-free target lookup for an *existing* claim (used by
    resolve_claim_for_event's public-page lookup and
    organizer_claims._is_already_claimed's bulk cross-retirement check) —
    trusts `es.publisher_id` as already-stamped, which is safe here because
    any active claim was only ever created via `resolve_claim_target_live()`
    (`app.claims.target_resolution`, #427), which stamps the row before a
    Claim can be created against it. Do not reuse this for deciding a *new*
    claim's target — see `resolve_claim_target_live` for that."""
    if es.publisher_id is not None:
        return ClaimTarget(CLAIM_KIND_PUBLISHER, es.publisher_id, None)
    key = serialize_event_series_key(
        event_series_key(event.title_orig, resolve_venue_name(event))
    )
    return ClaimTarget(CLAIM_KIND_SERIES, None, key)


def _target_where(target: ClaimTarget) -> tuple:
    """The Publisher-vs-Series column match for `target`, shared by every
    Claim query scoped to a single target (active_claim_for_target,
    approved_claim_exists, auto_decline_other_pending_claims) so the
    kind-branch lives in exactly one place."""
    if target.kind == CLAIM_KIND_PUBLISHER:
        return (Claim.publisher_id == target.publisher_id,)
    return (Claim.event_series_key == target.event_series_key,)


async def active_claim_for_target(db: AsyncSession, target: ClaimTarget) -> Claim | None:
    """The Claim to represent `target`'s pending/approved state, if any
    (#414) — backs both the public event page's claim_status/listed_by and
    the search/suggestions surfaces' cross-surface-retirement exclusion.
    Since #431 (slice 1 of #425) a target can carry several coexisting
    pending claims, so this needs a deterministic pick, not "whichever row
    the index scan happens to return first": an approved claim always wins
    (there's at most one, and it's the target's real resolved state) over
    any number of pending ones, and among pending-only claims the newest one
    wins (the most recently asserted claimant). Eager-loads `Claim.organizer`
    (#419) so callers needing the organizer's display name don't pay a
    second round trip."""
    return await db.scalar(
        select(Claim)
        .options(selectinload(Claim.organizer))
        .where(*_target_where(target), Claim.status.in_(CLAIM_ACTIVE_STATUSES))
        .order_by((Claim.status == CLAIM_STATUS_APPROVED).desc(), Claim.id.desc())
        .limit(1)
    )


async def _claim_target_for_event(db: AsyncSession, event: Event) -> ClaimTarget | None:
    """Cheap, HTTP-free claim target for `event`, or None when it has no
    representative EventSource — the one place resolve_claim_for_event and
    own_claim_for_event resolve it."""
    es = await representative_event_source(db, event_id=event.id)
    if es is None or es.source is None:
        return None
    return resolve_claim_target(event, es)


async def resolve_claim_for_event(db: AsyncSession, event: Event) -> Claim | None:
    """Active pending/approved Claim covering `event`, if any — shared by the
    public event page's claim_status (via claim_status_from_claim) and its
    "Listed by X" organizer-name lookup (#419) so the page pays for one
    EventSource/Claim round trip, not two."""
    target = await _claim_target_for_event(db, event)
    if target is None:
        return None
    return await active_claim_for_target(db, target)


async def own_claim_for_event(
    db: AsyncSession, organizer: Organizer, event: Event
) -> Claim | None:
    """(#451) Caller-scoped counterpart to resolve_claim_for_event — the
    organizer-authed public-page pending pill needs to know whether the
    *caller* is the claimant, not merely that some pending claim exists on
    the target, and the organizer session cookie (Path=/api/organizer)
    never reaches GET /events/{id} to make that distinction there. Looks the
    caller's own active claim up on the target directly rather than
    filtering active_claim_for_target's single newest claim afterwards:
    since #431 a target can carry several coexisting pending claims, so a
    rival's newer pending claim would otherwise hide the caller's (#456).
    A caller can hold at most one active claim per target, so the lookup is
    deterministic."""
    target = await _claim_target_for_event(db, event)
    if target is None:
        return None
    return await db.scalar(
        select(Claim)
        .where(
            *_target_where(target),
            Claim.organizer_id == organizer.id,
            Claim.status.in_(CLAIM_ACTIVE_STATUSES),
        )
        .order_by(Claim.id.desc())
        .limit(1)
    )


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
                    Claim.dormant == true(),
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
                    Claim.dormant == true(),
                )
            )
        ).all()
        for (key,) in series_rows:
            dormant_event_ids.update(series_keys.get(key, set()))
    return dormant_event_ids


def claim_status_from_claim(claim: Claim | None, event: Event) -> str:
    """(#414, narrowed by #445) unclaimed/pending/claimed/not_claimable for
    `claim`'s public page CTA. A direct organizer submission
    (`submitted_by_organizer_id` set) has no ingested EventSource to ever
    claim against, so it's not_claimable regardless of `claim` — distinct
    from unclaimed, which resolve_claim_for_event() also returns None for
    when the event is claimable but nobody has yet.

    A `pending` result is caller-blind — it says nothing about whether the
    caller is the claimant — so routers/events.py (#451) collapses it into
    `unclaimed` before this reaches the public, unauthenticated payload.
    Callers needing the claimant-only distinction use own_claim_for_event()
    instead."""
    if event.submitted_by_organizer_id is not None:
        return CLAIM_DISCOVERY_STATUS_NOT_CLAIMABLE
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
    client: httpx.AsyncClient,
    *,
    kind: str,
    organizer_email: str,
    es: EventSource,
    event: Event | None,
    token: str,
    event_page_html: str | None = None,
) -> VerificationResult:
    if kind == CLAIM_KIND_SERIES:
        # (#428) No auto-grant path for a Series claim, ever — the
        # Trusted-claimant fast-track that used to sit here is deleted, not
        # gated off.
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
            # (#439) Reuse target resolution's already-fetched event.url HTML
            # on the create_claim path instead of a second live fetch of the
            # same page — event_page_html is None on recheck_claim (which
            # never calls resolve_claim_target_live) and for a Publisher
            # already stamped before this claim was created, so this still
            # falls back to fetching it here in either case.
            html = event_page_html
            if html is None:
                try:
                    response = await http_get_stored_url(client, event.url)
                except ValueError:
                    # SSRF guard refused the stored URL (not an allowlisted
                    # https host) — same fallback as a failed fetch below.
                    log.warning(
                        "claim verification: event url not fetchable, falling "
                        "back to admin review: source=%s",
                        source_slug,
                    )
                    return series_claim_result()
                html = response.text
            return await verify_piletilevi_claim(
                client, html, event.url, token, organizer_email
            )
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


async def approved_claim_exists(db: AsyncSession, target: ClaimTarget) -> bool:
    """(#431) Approved-only counterpart of `active_claim_for_target` — the
    narrowed unique index (migration 0048) no longer rejects a new pending
    claim against a target that already has other *pending* claims, only
    against one with an existing *approved* claim, so that case needs an
    explicit pre-insert check instead of relying on IntegrityError. Not
    module-private: also called from admin.py's manual grant endpoint, which
    needs the same pre-flip guard as the organizer-facing auto-grant path."""
    return (
        await db.scalar(
            select(Claim.id)
            .where(*_target_where(target), Claim.status == CLAIM_STATUS_APPROVED)
            .limit(1)
        )
    ) is not None


async def _own_pending_claim_for_target(
    db: AsyncSession, organizer_id: int, target: ClaimTarget
) -> Claim | None:
    """(#448) The caller's own still-pending claim on `target`, if any —
    checked in create_claim before inserting a new one, so an organizer
    re-claiming a target they already have a pending claim on gets that
    existing claim back instead of a confusing duplicate (its own proof
    token, its own daily-cap slot, and a spurious decline email for itself
    once the winning claim auto-grants). Best-effort like the daily-cap
    check above it: a plain SELECT with no row lock, and migration 0048's
    unique index only constrains approved rows, not pending ones — two
    concurrent requests (double-click, two tabs) can both see None here and
    both insert. Closing that fully would need a new partial unique index;
    out of scope for the single-click case this fixes."""
    return await db.scalar(
        select(Claim)
        .where(
            *_target_where(target),
            Claim.organizer_id == organizer_id,
            Claim.status == CLAIM_STATUS_PENDING,
        )
        .limit(1)
    )


async def _organizer_has_pending_claim(db: AsyncSession, organizer_id: int) -> bool:
    """(#450) Cheap existence check backing create_claim's early cap exit —
    an organizer at the daily cap with zero pending claims anywhere can never
    hit the own-pending short-circuit, so it's safe (and cheaper, skipping
    resolve_claim_target_live's live HTTP call) to reject them up front."""
    return (
        await db.scalar(
            select(Claim.id)
            .where(Claim.organizer_id == organizer_id, Claim.status == CLAIM_STATUS_PENDING)
            .limit(1)
        )
    ) is not None


async def auto_decline_other_pending_claims(
    db: AsyncSession,
    client: httpx.AsyncClient,
    target: ClaimTarget,
    winning_claim_id: int,
    winning_organizer_id: int,
) -> None:
    """(#431) Proof preempts assertion: once a claim on `target` is granted —
    either the organizer-facing auto-grant path or an admin's manual grant
    (admin.py's admin_grant_claim) — every other still-pending claim on that
    same target auto-declines, mirroring admin_decline_claim's status
    transition and reusing its decline email, just with no admin note (falls
    back to the email's generic decline copy). The shared target's
    representative_event_for_claim() (resolved once for all declined claims)
    supplies the email's event title — not the winning claim's event — since
    a Publisher target's freshest traced-back listing can differ from whichever specific event the winner
    happened to claim through. Not module-private: also called from
    admin.py's manual grant endpoint.

    Excludes `winning_organizer_id`'s own other pending rows (#448) — those
    should no longer exist since create_claim now returns an organizer's
    existing pending claim on a target instead of inserting a sibling, but
    this stays a defensive filter against any duplicate created before that
    fix shipped, so a winner's own historical duplicate isn't declined and
    doesn't trigger a "your claim was declined" email for a claim they just
    won."""
    # Local import: app.claims.pinning imports representative_event_source
    # from this module, so a module-level import here would deadlock the
    # two modules' load order (see cancel_claim, same reason).
    from app.claims.pinning import representative_event_for_claim

    others = (
        await db.scalars(
            select(Claim)
            .options(selectinload(Claim.organizer))
            .where(
                *_target_where(target),
                Claim.status == CLAIM_STATUS_PENDING,
                Claim.id != winning_claim_id,
                Claim.organizer_id != winning_organizer_id,
            )
        )
    ).all()
    if not others:
        return

    now = datetime.now(TALLINN_TZ)
    for other in others:
        other.status = CLAIM_STATUS_REVOKED
        other.resolved_at = now
    await db.commit()

    semaphore = asyncio.Semaphore(CLAIM_EMAIL_SEND_CONCURRENCY)

    # Every claim in `others` shares `target`, so they all resolve to the same
    # representative event — look it up once, sequentially. Doing it inside
    # the gathered coroutines ran concurrent queries on one AsyncSession
    # (SQLAlchemy raises), which the except below swallowed, silently
    # dropping the decline emails (Big-O audit M5).
    try:
        event = await representative_event_for_claim(db, others[0])
    except Exception:
        log.error(
            "Failed to resolve event for auto-decline claim-declined emails "
            "(claim_id=%s)",
            others[0].id,
            exc_info=True,
        )
        event = None

    async def _send_one(claim: Claim) -> None:
        organizer = claim.organizer
        if organizer is None:
            return
        async with semaphore:
            try:
                await send_claim_declined_email(
                    organizer.email,
                    resolve_title(event, organizer.locale) if event else None,
                    "",
                    organizer.locale,
                    http_client=client,
                )
            except Exception:
                log.error(
                    "Failed to send auto-decline claim-declined email (claim_id=%s)",
                    claim.id,
                    exc_info=True,
                    extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
                )

    await asyncio.gather(*(_send_one(c) for c in others), return_exceptions=True)


async def create_claim(
    db: AsyncSession,
    client: httpx.AsyncClient,
    organizer: Organizer,
    event_id: int,
    justification: str | None = None,
) -> tuple[Claim, bool]:
    """Create a Publisher or Series claim for `event_id`, auto-detecting
    which kind applies from that event's resolved EventSource, then invoking
    #412's verification engine to decide auto-grant vs. admin-review routing.
    A Series claim (#428) requires a non-blank `justification` — the kind
    isn't known until `resolve_claim_target_live` resolves it, so this is
    checked after that resolution and before any row is inserted, not up
    front. Daily-capped and duplicate/race-rejected at the DB layer (#413) —
    best-effort like ORGANIZER_DAILY_SUBMISSION_CAP: the count-then-insert
    has no row lock, so concurrent requests could exceed the cap by a small
    margin.

    Returns (claim, created) — (#448) an organizer who already has a pending
    claim on the resolved target gets that existing claim back with
    created=False instead of a duplicate row; callers map that onto a 200
    instead of a 201.

    (#450) The cap check runs in two places: a cheap early exit here rejects
    a capped organizer with no pending claims at all (the common case) before
    any work happens, and the real gate sits just before the Claim(...)
    insert below, after the own-pending short-circuit — so a capped
    organizer re-claiming a target they already have pending still gets that
    existing claim back (nothing is inserted, so nothing should count
    against the cap) instead of a 429.
    """
    at_cap = await _claims_created_today(db, organizer.id) >= ORGANIZER_DAILY_CLAIM_CAP
    if at_cap and not await _organizer_has_pending_claim(db, organizer.id):
        raise ClaimError(HTTPStatus.TOO_MANY_REQUESTS, ERROR_DAILY_CLAIM_LIMIT)

    event = await db.get(Event, event_id)
    if (
        event is None
        or event.status != EVENT_STATUS_PUBLISHED
        or event.is_explicit
        or event.is_non_event
        or not (event.dedup_group_id is None or event.dedup_group_id == event.id)
    ):
        # Same published+canonical (+ not explicit/non-event) bar as
        # public_event_filter()/canonical_event_filter() (events/queries.py) — a
        # draft, cancelled, or non-canonical-duplicate event is rejected the
        # same way a nonexistent one is, so id probing can't distinguish them.
        raise ClaimError(HTTPStatus.NOT_FOUND, ERROR_EVENT_NOT_FOUND)

    if event.submitted_by_organizer_id is not None:
        # Explicit guard (#429) — a direct organizer submission has no
        # ingested EventSource to claim against. The "your own" message
        # (#445) is only true for the submitter itself; any other caller
        # gets the same generic not-claimable message as the EventSource-less
        # branch below, so the response can't be used to fingerprint who
        # submitted the event.
        if event.submitted_by_organizer_id == organizer.id:
            raise ClaimError(HTTPStatus.UNPROCESSABLE_ENTITY, ERROR_CLAIM_OWN_SUBMISSION)
        raise ClaimError(HTTPStatus.UNPROCESSABLE_ENTITY, ERROR_CLAIM_NOT_CLAIMABLE)

    es = await representative_event_source(db, event_id=event_id)
    if es is None or es.source is None:
        raise ClaimError(HTTPStatus.UNPROCESSABLE_ENTITY, ERROR_CLAIM_NOT_CLAIMABLE)

    try:
        target = await resolve_claim_target_live(db, client, event, es)
    except ClaimTargetError:
        raise ClaimError(HTTPStatus.UNPROCESSABLE_ENTITY, ERROR_CLAIM_NOT_CLAIMABLE) from None

    if await approved_claim_exists(db, target):
        # (#431) Unchanged from pre-0048 behavior for the approved case — no
        # contest/override flow for an already-granted claim, support-facing
        # message. Only the pending-vs-pending case below is new.
        raise ClaimError(HTTPStatus.CONFLICT, ERROR_CLAIM_TARGET_ALREADY_APPROVED)

    existing_own_pending = await _own_pending_claim_for_target(db, organizer.id, target)
    if existing_own_pending is not None:
        return existing_own_pending, False

    if at_cap:
        # Re-checked here (not just the early exit above) because a capped
        # organizer who does have pending claims elsewhere reaches this
        # point without having been rejected yet — this is the real gate for
        # that case, running only now that we know a row is actually about
        # to be inserted.
        raise ClaimError(HTTPStatus.TOO_MANY_REQUESTS, ERROR_DAILY_CLAIM_LIMIT)

    justification_clean = justification.strip() if justification else None
    if target.kind == CLAIM_KIND_SERIES and not justification_clean:
        raise ClaimError(HTTPStatus.UNPROCESSABLE_ENTITY, ERROR_CLAIM_JUSTIFICATION_REQUIRED)

    claim = Claim(
        organizer_id=organizer.id,
        kind=target.kind,
        publisher_id=target.publisher_id,
        event_series_key=target.event_series_key,
        proof_token=generate_claim_token(),
        verification_mechanism=CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW,
        status=CLAIM_STATUS_PENDING,
        justification=justification_clean if target.kind == CLAIM_KIND_SERIES else None,
    )
    db.add(claim)
    # No IntegrityError guard needed here (#431): this insert always lands as
    # CLAIM_STATUS_PENDING, and the narrowed unique indexes (migration 0048)
    # only constrain approved rows, so a duplicate-pending insert can't
    # violate them — the approved-vs-approved race is instead caught at the
    # commit below, after this claim's own verification result is known.
    await db.flush()

    result = await _run_verification(
        client,
        kind=target.kind,
        organizer_email=organizer.email,
        es=es,
        event=event,
        token=claim.proof_token,
        event_page_html=target.event_page_html,
    )
    claim.verification_mechanism = result.mechanism
    claim.verification_domain = result.domain
    claim.verification_contact = result.contact
    auto_granted = result.outcome == CLAIM_VERIFICATION_OUTCOME_AUTO_GRANT
    if auto_granted:
        claim.status = CLAIM_STATUS_APPROVED
        claim.resolved_at = datetime.now(TALLINN_TZ)
    try:
        await db.commit()
    except IntegrityError:
        # (#431) Race: another claim on the same target was approved between
        # the pre-insert check above and this claim's own auto-grant landing.
        await db.rollback()
        raise ClaimError(HTTPStatus.CONFLICT, ERROR_CLAIM_TARGET_ALREADY_APPROVED) from None
    if auto_granted:
        try:
            await send_claim_granted_email(
                organizer.email,
                resolve_title(event, organizer.locale),
                "",
                organizer.locale,
                http_client=client,
            )
        except Exception:
            log.error(
                "Failed to send claim-granted email (claim_id=%s)",
                claim.id,
                exc_info=True,
                extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
            )
        await auto_decline_other_pending_claims(db, client, target, claim.id, organizer.id)
    return claim, True


async def own_claim_or_404(db: AsyncSession, claim_id: int, organizer_id: int) -> Claim:
    """Read-only fetch (#415's pending screen, reloaded or opened fresh) —
    unlike `_own_pending_claim_or_404`, any status is returned so the screen
    can render its resolved (approved/expired/...) state too."""
    claim = await db.scalar(
        select(Claim).where(Claim.id == claim_id, Claim.organizer_id == organizer_id)
    )
    if claim is None:
        raise ClaimError(HTTPStatus.NOT_FOUND, ERROR_CLAIM_NOT_FOUND)
    return claim


async def _own_pending_claim_or_404(db: AsyncSession, claim_id: int, organizer_id: int) -> Claim:
    claim = await own_claim_or_404(db, claim_id, organizer_id)
    if claim.status != CLAIM_STATUS_PENDING:
        raise ClaimError(HTTPStatus.CONFLICT, ERROR_CLAIM_NOT_PENDING)
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
    claim.resolved_at = datetime.now(TALLINN_TZ)
    await db.commit()

    # Local import: app.claims.pinning imports representative_event_source
    # from this module, so a module-level import here would deadlock the
    # two modules' load order.
    from app.claims.pinning import representative_event_for_claim

    try:
        event = await representative_event_for_claim(db, claim)
        await send_claim_self_cancelled_email(
            organizer.email,
            resolve_title(event, organizer.locale) if event else None,
            organizer.locale,
        )
    except Exception:
        log.error(
            "Failed to send claim-self-cancelled email (claim_id=%s)",
            claim_id,
            exc_info=True,
            extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
        )
    return claim


async def transition_pending_claim(
    db: AsyncSession, claim: Claim, new_status: str, resolved_at: datetime
) -> bool:
    """Atomically move ``claim`` out of 'pending'. The ``WHERE status =
    'pending'`` guard makes the transition race-free: of two concurrent
    resolvers (admin double-submit, grant vs decline, admin vs organizer
    recheck) exactly one wins and gets True; the loser gets False and must
    not send its email or run auto-decline (OWASP audit L-11). May raise
    IntegrityError for an approve that loses the one-approved-per-target
    unique index — callers already map that to a conflict."""
    won = await db.execute(
        update(Claim)
        .where(Claim.id == claim.id, Claim.status == CLAIM_STATUS_PENDING)
        .values(status=new_status, resolved_at=resolved_at)
        .returning(Claim.id)
        .execution_options(synchronize_session=False)
    )
    if won.scalar_one_or_none() is None:
        return False
    claim.status = new_status
    claim.resolved_at = resolved_at
    return True


async def recheck_claim(
    db: AsyncSession, client: httpx.AsyncClient, organizer: Organizer, claim_id: int
) -> Claim:
    """Organizer-triggered "check now": re-run verification for a pending
    automated-mechanism claim. Always bumps last_checked_at, whatever the
    outcome — resets the inactivity clock expire_stale_claims sweeps against,
    since the organizer is actively engaged. Admin-review claims (every
    Series claim, and any Publisher claim that fell back to it) have nothing
    to re-verify and are rejected the same as an already-resolved one — so
    every claim reaching this function is Publisher-kind, and its target was
    already decided once, at creation, by `resolve_claim_target_live` (#427):
    this function re-verifies against that same `claim.publisher_id`, it
    never re-decides the target.
    """
    claim = await _own_pending_claim_or_404(db, claim_id, organizer.id)
    if claim.verification_mechanism not in CLAIM_AUTOMATED_VERIFICATION_MECHANISMS:
        raise ClaimError(HTTPStatus.CONFLICT, ERROR_CLAIM_NOT_PENDING)

    es = await representative_event_source(db, publisher_id=claim.publisher_id)
    if es is None or es.source is None:
        raise ClaimError(HTTPStatus.UNPROCESSABLE_ENTITY, ERROR_CLAIM_NOT_CLAIMABLE)
    event = await db.get(Event, es.event_id)

    result = await _run_verification(
        client,
        kind=claim.kind,
        organizer_email=organizer.email,
        es=es,
        event=event,
        token=claim.proof_token,
    )
    claim.verification_mechanism = result.mechanism
    claim.verification_domain = result.domain
    claim.verification_contact = result.contact
    claim.last_checked_at = datetime.now(TALLINN_TZ)
    auto_granted = result.outcome == CLAIM_VERIFICATION_OUTCOME_AUTO_GRANT
    try:
        if auto_granted and not await transition_pending_claim(
            db, claim, CLAIM_STATUS_APPROVED, claim.last_checked_at
        ):
            # Resolved (declined/cancelled/expired) while verification ran.
            await db.rollback()
            raise ClaimError(HTTPStatus.CONFLICT, ERROR_CLAIM_NOT_PENDING)
        await db.commit()
    except IntegrityError:
        # (#431) Another claim on the same Publisher was approved since this
        # one was created — same race as create_claim's commit guard.
        await db.rollback()
        raise ClaimError(HTTPStatus.CONFLICT, ERROR_CLAIM_TARGET_ALREADY_APPROVED) from None
    if auto_granted:
        try:
            await send_claim_granted_email(
                organizer.email,
                resolve_title(event, organizer.locale) if event else None,
                "",
                organizer.locale,
                http_client=client,
            )
        except Exception:
            log.error(
                "Failed to send claim-granted email (claim_id=%s)",
                claim.id,
                exc_info=True,
                extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
            )
        target = ClaimTarget(claim.kind, claim.publisher_id, claim.event_series_key)
        await auto_decline_other_pending_claims(
            db, client, target, claim.id, claim.organizer_id
        )
    return claim


async def _send_claim_expiry_emails(db: AsyncSession, expired: list[Claim]) -> None:
    """One expiry email per row in ``expired`` (#421) — bulk-loads organizers
    and Publisher-kind claims' representative event in two fixed queries
    (bulk_resolve_publisher_events, shared with admin_list_claims), rather
    than a per-row SELECT. A Series-kind claim gets no title resolved here
    for the same cost reason admin_list_claims skips it for lists — the
    email falls back to generic wording (app.email.claim_resolution._target_label).
    Each row's ``days`` figure is picked from its own verification_mechanism
    (#430) — CLAIM_EXPIRY_DAYS for an automated one, CLAIM_ADMIN_REVIEW_EXPIRY_DAYS
    otherwise — so the email states the window that actually applied to it,
    not always the shorter automated one.
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
        days = (
            CLAIM_EXPIRY_DAYS
            if claim.verification_mechanism in CLAIM_AUTOMATED_VERIFICATION_MECHANISMS
            else CLAIM_ADMIN_REVIEW_EXPIRY_DAYS
        )
        async with semaphore:
            try:
                await send_claim_expired_email(
                    organizer.email,
                    resolve_title(event, organizer.locale) if event else None,
                    organizer.locale,
                    http_client=http_client,
                    days=days,
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
    """Sweep job (#413/#421/#430): expire a pending claim that has gone too
    long without resolution, then notify each claimant. Two windows, one
    pass: an automated-mechanism claim (Fienta token, DNS-TXT, Piletilevi
    promoter — CLAIM_AUTOMATED_VERIFICATION_MECHANISMS) expires after
    CLAIM_EXPIRY_DAYS without a recheck; everything else (admin_review,
    piletilevi_mailbox — neither has a recheck path, see that constant's
    comment) expires after the longer CLAIM_ADMIN_REVIEW_EXPIRY_DAYS instead
    of never, closing the permanent-lock hole #425 flagged. Commits
    internally (mirrors build_daily_feeds) so the expiry emails below
    reflect only durably expired rows — app/main.py wires this job with
    commit=False."""
    # UTC on purpose: TTL arithmetic (see CLAUDE.md Conventions) — a Tallinn-aware
    # `now - timedelta(days=N)` would shift by an hour across a DST change.
    now = datetime.now(timezone.utc)
    automated_cutoff = now - timedelta(days=CLAIM_EXPIRY_DAYS)
    admin_review_cutoff = now - timedelta(days=CLAIM_ADMIN_REVIEW_EXPIRY_DAYS)
    result = await db.execute(
        update(Claim)
        .where(
            Claim.status == CLAIM_STATUS_PENDING,
            or_(
                and_(
                    Claim.verification_mechanism.in_(
                        CLAIM_AUTOMATED_VERIFICATION_MECHANISMS
                    ),
                    Claim.last_checked_at < automated_cutoff,
                ),
                and_(
                    Claim.verification_mechanism.notin_(
                        CLAIM_AUTOMATED_VERIFICATION_MECHANISMS
                    ),
                    Claim.last_checked_at < admin_review_cutoff,
                ),
            ),
        )
        .values(status=CLAIM_STATUS_EXPIRED, resolved_at=func.now())
        .returning(Claim)
    )
    expired = list(result.scalars().all())
    await db.commit()
    await _send_claim_expiry_emails(db, expired)
    return {"expired": len(expired)}
