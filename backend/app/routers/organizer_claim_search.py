"""Organizer finding a claimable event (#414, narrowed by #441/ADR 0004):
search and onboarding suggestions. Both exclude events that already carry an
*approved* claim on their Publisher/Series target — a pending-only target
still surfaces, since a rival claimant must be able to start proving ownership
through the product, not just via a direct API call. An event claimed via any
one of these surfaces retires it from the other two once that claim is
approved. The public-page "is this your event?" CTA is the third surface; it
reads GET /events/{id}'s claim_status field instead (built from
app/claims/lifecycle.py::resolve_claim_for_event + claim_status_from_claim,
wired in routers/events.py) rather than this router, since it has no
search/suggestion query to run.

Shares the /organizer/claims prefix with organizer_claims.py and is included
before it in app/main.py so that router's GET /{claim_id} can't shadow
/search and /suggestions.
"""

from datetime import datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import QueryableAttribute, aliased, selectinload
from sqlalchemy.sql.elements import ColumnElement

from app._generated.shared_constants import (
    BROWSE_QUERY_MAX_LEN,
    CLAIM_KIND_PUBLISHER,
    CLAIM_STATUS_APPROVED,
)
from app.auth.dependencies import get_current_organizer
from app.claims.lifecycle import resolve_claim_target
from app.constants.claims import (
    CLAIM_SEARCH_CANDIDATE_MULTIPLIER,
    CLAIM_SEARCH_QUERY_MIN_LENGTH,
    CLAIM_SEARCH_RESULT_LIMIT,
    CLAIM_SUGGESTIONS_LIMIT,
    ERROR_CLAIM_SEARCH_QUERY_TOO_SHORT,
    FREE_EMAIL_PROVIDER_DOMAINS,
)
from app.constants.core import TALLINN_TZ
from app.constants.events import EVENT_SEARCH_TEXT_SQL
from app.constants.rate_limits import RATE_LIMIT_BROWSE
from app.db import get_db
from app.events.localize import resolve_title
from app.events.queries import (
    escape_ilike_pattern,
    event_not_ended_filter,
    public_event_filter,
)
from app.events.venue import resolve_venue_name
from app.ingestion.http_client import host_matches_domain
from app.models.claims import Claim
from app.models.events import Event, EventSource
from app.models.organizers import Organizer
from app.rate_limit import limiter
from app.routers.utils import resolve_locale_param

router = APIRouter(prefix="/organizer/claims", tags=["organizer-claims"])


def claim_search_text() -> ColumnElement[str]:
    """Title haystack the trigram GIN index ix_events_search_text_trgm covers
    (M9). A literal column, not a SQLAlchemy expression: bound JSONB keys
    would render as parameters and the planner couldn't match the index."""
    return literal_column(EVENT_SEARCH_TEXT_SQL)


def claim_url_text() -> QueryableAttribute[str | None]:
    """events.url, backed by ix_events_url_trgm for the suggestions domain
    ILIKE."""
    return Event.url


def _serialize_claim_candidate(event: Event, locale: str) -> dict:
    return {
        "id": event.id,
        "title": resolve_title(event, locale),
        "venue_name": resolve_venue_name(event),
        "starts_at": event.starts_at.isoformat(),
        "image_url": event.image_url,
    }


def _publisher_claimed_sql() -> ColumnElement[bool]:
    """SQL twin of the Publisher branch of ``resolve_claim_target``: the
    event's lowest-id source carries a ``publisher_id`` that an *approved*
    claim holds. Pushed into the candidate query so the LIMIT window is filled
    with claimable rows instead of being trimmed in Python afterwards (which
    returned short pages once many candidates were already claimed). Approved
    only since #441/ADR 0004: a pending-only target still has to surface as
    claimable so a rival claimant can start proving ownership."""
    # Aliased + explicitly correlated to the outer Event: un-aliased, SQLAlchemy
    # correlates the inner EventSource to the EXISTS's own EventSource and the
    # clause never references the candidate row.
    first_source = aliased(EventSource)
    first_source_id = (
        select(func.min(first_source.id))
        .where(first_source.event_id == Event.id)
        .correlate(Event)
        .scalar_subquery()
    )
    return (
        select(literal_column("1"))
        .select_from(EventSource)
        .join(Claim, Claim.publisher_id == EventSource.publisher_id)
        .where(EventSource.id == first_source_id, Claim.status == CLAIM_STATUS_APPROVED)
        .exists()
    )


async def _load_approved_series_keys(db: AsyncSession) -> set[str]:
    """Approved Series-claim keys. A Series key (normalized title+venue) is
    resolved in Python by ``resolve_claim_target`` — it uses the resolved venue
    name, which the trigger-maintained ``events.series_key`` column does not
    (venue-linked events leave the raw venue columns NULL) — so only this small
    key set is filtered in Python; Publisher claims are filtered in SQL
    (``_publisher_claimed_sql``)."""
    rows = (
        await db.execute(
            select(Claim.event_series_key).where(
                Claim.status == CLAIM_STATUS_APPROVED,
                Claim.event_series_key.is_not(None),
            )
        )
    ).all()
    return {row.event_series_key for row in rows if row.event_series_key is not None}


def _is_series_claimed(event: Event, es: EventSource, series_keys: set[str]) -> bool:
    target = resolve_claim_target(event, es)
    return target.kind != CLAIM_KIND_PUBLISHER and target.event_series_key in series_keys


@router.get("/search")
@limiter.limit(RATE_LIMIT_BROWSE)
async def search_claimable_events(
    request: Request,
    q: str = Query(..., min_length=1, max_length=BROWSE_QUERY_MAX_LEN),
    locale: str | None = Query(None),
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Search over published, not-yet-ended events by title, for the
    organizer to pick one to claim (#414) — the chosen id feeds POST
    /organizer/claims directly."""
    query = q.strip()
    if len(query) < CLAIM_SEARCH_QUERY_MIN_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ERROR_CLAIM_SEARCH_QUERY_TOO_SHORT,
        )

    effective_locale = resolve_locale_param(locale, current_organizer.locale)
    now = datetime.now(TALLINN_TZ)
    pattern = escape_ilike_pattern(query)
    candidates = (
        (
            await db.execute(
                select(Event)
                .options(selectinload(Event.sources), selectinload(Event.venue))
                .where(
                    public_event_filter(),
                    event_not_ended_filter(now),
                    claim_search_text().ilike(pattern, escape="\\"),
                    ~_publisher_claimed_sql(),
                )
                .order_by(Event.starts_at)
                .limit(CLAIM_SEARCH_RESULT_LIMIT * CLAIM_SEARCH_CANDIDATE_MULTIPLIER)
            )
        )
        .scalars()
        .all()
    )

    series_keys = await _load_approved_series_keys(db)
    results = []
    for event in candidates:
        if not event.sources:
            continue
        es = min(event.sources, key=lambda s: s.id)
        if _is_series_claimed(event, es, series_keys):
            continue
        results.append(_serialize_claim_candidate(event, effective_locale))
        if len(results) >= CLAIM_SEARCH_RESULT_LIMIT:
            break
    return {"events": results}


@router.get("/suggestions")
@limiter.limit(RATE_LIMIT_BROWSE)
async def suggested_claimable_events(
    request: Request,
    locale: str | None = Query(None),
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Onboarding suggestions (#414): published, not-yet-ended events whose
    ticket URL resolves to the same domain as the organizer account's email —
    skipped entirely for a free/shared-mailbox domain
    (FREE_EMAIL_PROVIDER_DOMAINS), since a gmail.com match says nothing about
    which events are plausibly "theirs". No Google Workspace `hd` check —
    ruled out at spec time (#409): plain email-domain matching is the whole
    mechanism."""
    domain = current_organizer.email.rsplit("@", 1)[-1].lower()
    if domain in FREE_EMAIL_PROVIDER_DOMAINS:
        return {"events": []}

    effective_locale = resolve_locale_param(locale, current_organizer.locale)
    now = datetime.now(TALLINN_TZ)
    pattern = escape_ilike_pattern(domain)
    candidates = (
        (
            await db.execute(
                select(Event)
                .options(selectinload(Event.sources), selectinload(Event.venue))
                .where(
                    public_event_filter(),
                    event_not_ended_filter(now),
                    Event.url.isnot(None),
                    claim_url_text().ilike(pattern, escape="\\"),
                    ~_publisher_claimed_sql(),
                )
                .order_by(Event.starts_at)
                .limit(CLAIM_SUGGESTIONS_LIMIT * CLAIM_SEARCH_CANDIDATE_MULTIPLIER)
            )
        )
        .scalars()
        .all()
    )

    series_keys = await _load_approved_series_keys(db)
    results = []
    for event in candidates:
        if not event.sources or not event.url:
            continue
        # The ILIKE above is a cheap substring pre-filter (narrows the scan);
        # this is the precise check — "notgmail.com" contains "gmail.com" as
        # a substring but isn't the same host.
        host = urlparse(event.url).hostname or ""
        if not host_matches_domain(host, domain):
            continue
        es = min(event.sources, key=lambda s: s.id)
        if _is_series_claimed(event, es, series_keys):
            continue
        results.append(_serialize_claim_candidate(event, effective_locale))
        if len(results) >= CLAIM_SUGGESTIONS_LIMIT:
            break
    return {"events": results}
