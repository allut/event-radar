"""Data retention cleanup — prunes satellite/audit tables, never event rows."""

from datetime import datetime, timedelta
from typing import cast

from sqlalchemy import and_, ColumnElement, delete, exists, false, func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.core import TALLINN_TZ
from app.constants.ops import (
    DAILY_FEEDS_RETENTION_DAYS,
    INGESTION_RUNS_RETENTION_DAYS,
    LLM_CALLS_RETENTION_DAYS,
    MAGIC_LINK_RETENTION_DAYS,
    RAW_EVENTS_RETENTION_DAYS,
    RAW_INBOUND_EMAILS_RETENTION_DAYS,
    UNVERIFIED_ACCOUNT_RETENTION_DAYS,
)
from app.models.ingestion import IngestionRun, RawEvent, RawInboundEmail
from app.models.claims import Claim
from app.models.events import Event
from app.models.feeds import DailyFeed
from app.models.llm import LlmCall
from app.models.promotions import DailySponsoredSlot
from app.models.organizers import (
    Organizer,
    OrganizerIdentity,
    OrganizerMagicLink,
    Venue,
)
from app.models.users import AuthMagicLink, User


async def _count_or_delete(
    db: AsyncSession, model: type, clause: ColumnElement[bool], *, dry_run: bool
) -> int:
    if dry_run:
        stmt = select(func.count()).select_from(model).where(clause)
        return cast(int, (await db.execute(stmt)).scalar_one())
    result = await db.execute(delete(model).where(clause))
    return cast(CursorResult, result).rowcount


async def cleanup_stale_data(db: AsyncSession, *, dry_run: bool = False) -> dict:
    """Prune aged rows from satellite/audit tables.

    Never deletes ``events`` — only satellite data (audit logs, raw payloads,
    expired user/organizer auth tokens, old feed snapshots, stale cached
    scores). Preserves
    event rows and ``user_event_feedback`` indefinitely so the ranking
    indirect-feedback signal and event history are never lost.

    ``llm_calls`` doubles as the dedup/classification cache (keyed by
    ``content_hash``); pruning it means a content hash re-seen after
    ``LLM_CALLS_RETENTION_DAYS`` costs one fresh LLM call instead of a cache
    hit — an acceptable trade-off against unbounded JSONB growth.

    When ``dry_run=True``, counts matching rows instead of deleting them (no
    writes). The caller commits after a real (non-dry-run) call.
    """
    now = datetime.now(TALLINN_TZ)
    summary: dict = {}

    summary["auth_magic_links"] = await _count_or_delete(
        db,
        AuthMagicLink,
        AuthMagicLink.expires_at < now - timedelta(days=MAGIC_LINK_RETENTION_DAYS),
        dry_run=dry_run,
    )
    summary["organizer_magic_links"] = await _count_or_delete(
        db,
        OrganizerMagicLink,
        OrganizerMagicLink.expires_at < now - timedelta(days=MAGIC_LINK_RETENTION_DAYS),
        dry_run=dry_run,
    )
    summary["llm_calls"] = await _count_or_delete(
        db,
        LlmCall,
        LlmCall.created_at < now - timedelta(days=LLM_CALLS_RETENTION_DAYS),
        dry_run=dry_run,
    )
    summary["raw_events"] = await _count_or_delete(
        db,
        RawEvent,
        RawEvent.fetched_at < now - timedelta(days=RAW_EVENTS_RETENTION_DAYS),
        dry_run=dry_run,
    )
    summary["ingestion_runs"] = await _count_or_delete(
        db,
        IngestionRun,
        IngestionRun.started_at < now - timedelta(days=INGESTION_RUNS_RETENTION_DAYS),
        dry_run=dry_run,
    )
    summary["raw_inbound_emails"] = await _count_or_delete(
        db,
        RawInboundEmail,
        RawInboundEmail.received_at
        < now - timedelta(days=RAW_INBOUND_EMAILS_RETENTION_DAYS),
        dry_run=dry_run,
    )
    summary["daily_feeds"] = await _count_or_delete(
        db,
        DailyFeed,
        DailyFeed.feed_date
        < (now - timedelta(days=DAILY_FEEDS_RETENTION_DAYS)).date(),
        dry_run=dry_run,
    )
    # The Daily 5 Sponsored-slot store (#607) is pruned on the same retention.
    summary["daily_sponsored_slots"] = await _count_or_delete(
        db,
        DailySponsoredSlot,
        DailySponsoredSlot.slot_date
        < (now - timedelta(days=DAILY_FEEDS_RETENTION_DAYS)).date(),
        dry_run=dry_run,
    )

    # Unverified accounts (_get_or_create_user / _get_or_create_organizer
    # insert a row on an unauthenticated request-link POST, before the
    # address is proven reachable — the email
    # verification gate). Prune rows old enough that any link issued for
    # them has long expired (MAGIC_LINK_TTL_MINUTES /
    # ORGANIZER_MAGIC_LINK_TTL_MINUTES are both well under a day), skipping any with an unused-and-still-valid
    # link so a slow click never races the sweep.
    unverified_cutoff = now - timedelta(days=UNVERIFIED_ACCOUNT_RETENTION_DAYS)
    no_pending_user_link = ~exists(
        select(AuthMagicLink.id).where(
            AuthMagicLink.user_id == User.id,
            AuthMagicLink.used_at.is_(None),
            AuthMagicLink.expires_at > now,
        )
    )
    summary["users_unverified"] = await _count_or_delete(
        db,
        User,
        and_(
            User.email_verified == false(),
            User.created_at < unverified_cutoff,
            no_pending_user_link,
        ),
        dry_run=dry_run,
    )

    # Organizer "never proven" = email_verified_at IS NULL (stamped on every
    # sign-in path; the magic-link rows are pruned above so they cannot be the
    # evidence). Defense-in-depth: also spare anything carrying work or trust —
    # a verified flag, a linked identity, a claim, a venue, or a submitted event.
    no_pending_organizer_link = ~exists(
        select(OrganizerMagicLink.id).where(
            OrganizerMagicLink.organizer_id == Organizer.id,
            OrganizerMagicLink.used_at.is_(None),
            OrganizerMagicLink.expires_at > now,
        )
    )
    no_organizer_work = and_(
        ~exists(select(Event.id).where(Event.submitted_by_organizer_id == Organizer.id)),
        ~exists(select(OrganizerIdentity.id).where(OrganizerIdentity.organizer_id == Organizer.id)),
        ~exists(select(Claim.id).where(Claim.organizer_id == Organizer.id)),
        ~exists(select(Venue.id).where(Venue.organizer_id == Organizer.id)),
    )
    summary["organizers_unverified"] = await _count_or_delete(
        db,
        Organizer,
        and_(
            Organizer.created_at < unverified_cutoff,
            Organizer.email_verified_at.is_(None),
            Organizer.verified == false(),
            no_pending_organizer_link,
            no_organizer_work,
        ),
        dry_run=dry_run,
    )

    return summary
