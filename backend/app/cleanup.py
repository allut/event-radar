"""Data retention cleanup — prunes satellite/audit tables, never event rows."""

from datetime import datetime, timedelta
from typing import cast

from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    DAILY_FEEDS_RETENTION_DAYS,
    INGESTION_RUNS_RETENTION_DAYS,
    LLM_CALLS_RETENTION_DAYS,
    MAGIC_LINK_RETENTION_DAYS,
    RAW_EVENTS_RETENTION_DAYS,
    RAW_INBOUND_EMAILS_RETENTION_DAYS,
    TALLINN_TZ,
    USER_EVENT_SCORES_RETENTION_DAYS,
)
from app.models.models import (
    AuthMagicLink,
    DailyFeed,
    Event,
    IngestionRun,
    LlmCall,
    OrganizerMagicLink,
    RawEvent,
    RawInboundEmail,
    UserEventScore,
)
from app.routers.utils import event_ended_filter


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

    # Scores for events that ended more than USER_EVENT_SCORES_RETENTION_DAYS
    # ago — reuses event_ended_filter (NULL-safe complement of
    # event_not_ended_filter, evaluated at the retention cutoff) so "ended" is
    # defined identically to the publish gate and feed builder.
    scores_cutoff = now - timedelta(days=USER_EVENT_SCORES_RETENTION_DAYS)
    ended_event_ids = select(Event.id).where(event_ended_filter(scores_cutoff))
    summary["user_event_scores"] = await _count_or_delete(
        db,
        UserEventScore,
        UserEventScore.event_id.in_(ended_event_ids),
        dry_run=dry_run,
    )

    return summary
