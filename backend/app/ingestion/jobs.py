"""Scheduler job functions for the ingestion pipeline."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.dedup import AGGREGATE_LAST_VALUE_FIELDS
from app.constants.ingestion import INGEST_SOURCE_CONCURRENCY
from app.constants.jobs import (
    JOB_ID_BACKFILL_PUBLISHER_IDS,
    JOB_ID_CLASSIFY_PENDING,
    JOB_ID_GEOCODE_PENDING,
    JOB_ID_PUBLISH_PENDING,
    JOB_ID_REFETCH_EVENT_DETAILS,
    JOB_LABEL_DEDUP_DRAIN,
    JOB_LABEL_DEDUP_PASS,
)
from app.constants.llm import (
    LLM_BACKLOG_MAX_DRAIN_PASSES,
    LLM_BACKLOG_RETRY_SECONDS,
    LLM_CLASSIFY_BATCH_SIZE,
)
from app.constants.log_events import LOG_EVENT_LLM_DEGRADED
from app.db import AsyncSessionLocal
from app.dedup.llm_tiebreaker import run_dedup_pass_llm
from app.ingestion.registry import ADAPTER_REGISTRY
from app.models.models import Source
from app.db import run_in_session

log = logging.getLogger(__name__)


async def ingest_source(slug: str) -> dict:
    """Run ingestion for a single source by slug. Returns a summary dict.

    Follows the SourceAdapter.run() contract: on error, commit (not rollback) so
    the IngestionRun record with its error field is persisted for debugging.
    """
    async with AsyncSessionLocal() as db:
        source = await db.scalar(select(Source).where(Source.slug == slug))
        if source is None:
            raise ValueError(f"Unknown source slug: {slug!r}")
        if not source.enabled:
            return {"slug": slug, "skipped": True, "reason": "disabled"}

        adapter_cls = ADAPTER_REGISTRY.get(slug)
        if adapter_cls is None:
            raise ValueError(f"No adapter registered for slug: {slug!r}")

        adapter = adapter_cls(source)
        try:
            run = await adapter.run(db)
            await db.commit()
            log.info(
                "ingest source=%s raw=%d new=%d",
                slug,
                run.raw_count or 0,
                run.new_count or 0,
            )
            return {
                "slug": slug,
                "raw_count": run.raw_count,
                "new_count": run.new_count,
            }
        except Exception:
            # Per adapter.run() contract: commit to persist the IngestionRun error record.
            # Data writes inside run() use savepoints so they are already rolled back;
            # only the run record (and source.last_status) is preserved here.
            try:
                await db.commit()
            except Exception:
                log.exception("ingest source=%s: committing the run record failed", slug)
                await db.rollback()
            log.exception("ingest source=%s failed", slug)
            raise


async def ingest_all_enabled(kind: str | None = None) -> list[dict]:
    """Run ingestion for all enabled sources (optionally filtered by kind)."""
    async with AsyncSessionLocal() as db:
        q = select(Source).where(Source.enabled == true())
        if kind:
            q = q.where(Source.kind == kind)
        sources = (await db.scalars(q)).all()

    slugs = []
    for source in sources:
        if source.slug not in ADAPTER_REGISTRY:
            log.debug(
                "no adapter for slug=%s kind=%s — skipping", source.slug, source.kind
            )
            continue
        slugs.append(source.slug)

    # Sources scrape different hosts, so they run side by side, bounded.
    semaphore = asyncio.Semaphore(INGEST_SOURCE_CONCURRENCY)

    async def _one(slug: str) -> dict:
        async with semaphore:
            try:
                return await ingest_source(slug)
            except Exception as exc:
                return {"slug": slug, "error": str(exc)}

    return list(await asyncio.gather(*(_one(slug) for slug in slugs)))


async def _run_db_job(
    label: str, func: Callable[..., Awaitable[dict]]
) -> dict:
    """Run ``func(db)`` via the shared ``run_in_session`` runner
    (routers/utils.py), always committing, and log the summary.

    Rollback-and-reraise-on-failure is handled by run_in_session; this adds
    only the per-label success/failure logging. Shared shape for every
    scheduler job below except ``ingest_source``, whose contract is
    commit-on-error (the IngestionRun error record must persist).
    """
    try:
        summary = await run_in_session(func, commit=True)
    except Exception:
        log.exception("%s failed", label)
        raise
    log.info("%s complete: %s", label, summary)
    return summary


async def dedup_pass(*, retry_seconds: int = LLM_BACKLOG_RETRY_SECONDS) -> dict:
    """Run two-stage deduplication (rule pre-filter + LLM tiebreaker).

    Degrades to the rule-only pass when no LLM provider is configured.

    ``retry_seconds`` is forwarded to ``run_dedup_pass_llm``'s internal
    backlog-drain sub-passes (see its docstring) — pass ``0`` for a
    synchronous caller that wants a single unpaced burst, e.g.
    ``dedup_pass_drain_now``.
    """

    async def _run(db: AsyncSession) -> dict:
        return await run_dedup_pass_llm(db, retry_seconds=retry_seconds)

    return await _run_db_job(JOB_LABEL_DEDUP_PASS, _run)


async def classify_pending_job() -> dict:
    """Classify canonical draft events via LLM (one batch per call)."""
    from app.llm.classifier import classify_pending

    return await _run_db_job(JOB_ID_CLASSIFY_PENDING, classify_pending)


async def publish_pending_job() -> dict:
    """Promote qualifying classified events to published (one bulk UPDATE per call)."""
    from app.publish import publish_pending

    return await _run_db_job(JOB_ID_PUBLISH_PENDING, publish_pending)


async def geocode_pending_job() -> dict:
    """Geocode events with a venue_address but no lat/lng (one batch per call)."""
    from app.ingestion.geocode import geocode_pending

    return await _run_db_job(JOB_ID_GEOCODE_PENDING, geocode_pending)


async def backfill_publisher_ids_job() -> dict:
    """Stamp publisher_id onto claimable event_sources rows missing it
    (one bounded batch pass per call; no-op once nothing is unstamped)."""
    from app.ingestion.publisher_backfill import backfill_publisher_ids

    return await _run_db_job(JOB_ID_BACKFILL_PUBLISHER_IDS, backfill_publisher_ids)


async def refetch_event_details_job() -> dict:
    """Re-fetch detail pages for all future events and reconcile stored fields."""
    from app.ingestion.refetch import refetch_event_details

    return await _run_db_job(JOB_ID_REFETCH_EVENT_DETAILS, refetch_event_details)


def _dedup_has_backlog(summary: dict) -> bool:
    return summary.get("deferred_pairs", 0) > 0


def _dedup_backlog_shrinking() -> Callable[[dict], bool]:
    """``_dedup_has_backlog``, plus: the last pass deferred fewer pairs than
    the one before. An unpaced drain stops once a pass makes no headway (the
    LLM is down, say) instead of reloading the window up to the cap."""
    previous: list[int] = []

    def has_backlog(summary: dict) -> bool:
        deferred = summary.get("deferred_pairs", 0)
        shrinking = not previous or deferred < previous[-1]
        previous.append(deferred)
        return deferred > 0 and shrinking

    return has_backlog


def _classify_has_backlog(summary: dict) -> bool:
    return (
        summary.get("attempted", 0) >= LLM_CLASSIFY_BATCH_SIZE
        and summary.get("succeeded", 0) > 0
    )



def _aggregate_summaries(summaries: list[dict]) -> dict:
    """Combine numeric fields (excluding bools) across pass summaries.

    Covers both summary shapes: classify (attempted/succeeded/failed, all
    summed) and dedup (fresh_calls/llm_confirmed/deferred_pairs/updated summed;
    total/candidate_pairs/grouped/groups take the last pass's value).
    """
    totals: dict = {}
    for summary in summaries:
        for key, value in summary.items():
            if isinstance(value, bool) or not isinstance(value, int | float):
                continue
            if key in AGGREGATE_LAST_VALUE_FIELDS:
                totals[key] = value
            else:
                totals[key] = totals.get(key, 0) + value
    totals["passes"] = len(summaries)
    return totals


async def _drain_backlog(
    run_once: Callable[[], Awaitable[dict]],
    has_backlog: Callable[[dict], bool],
    label: str,
    *,
    retry_seconds: int = LLM_BACKLOG_RETRY_SECONDS,
    aggregate: bool = False,
) -> dict:
    """Re-run a single-pass LLM job until its backlog clears or the cap is hit.

    ``run_once`` must open/commit/close its own DB session per call (so no
    connection is held across the sleep). ``has_backlog`` inspects the pass
    summary and returns True while more work remains.

    ``retry_seconds=0`` skips the sleep between passes (immediate drain,
    suitable for a synchronous HTTP request). ``aggregate=True`` returns
    summed counts across all passes plus a ``"passes"`` count instead of the
    last pass's summary.
    """
    summary: dict = {}
    summaries: list[dict] = []
    for attempt in range(LLM_BACKLOG_MAX_DRAIN_PASSES):
        summary = await run_once()
        summaries.append(summary)
        if not has_backlog(summary):
            break
        if attempt + 1 < LLM_BACKLOG_MAX_DRAIN_PASSES:
            if retry_seconds:
                log.info(
                    "%s backlog remains, retrying in %ds: %s",
                    label,
                    retry_seconds,
                    summary,
                )
                await asyncio.sleep(retry_seconds)
            else:
                log.info("%s backlog remains, retrying immediately: %s", label, summary)
    else:
        log.warning(
            "%s drain cap (%d) reached; backlog deferred to next 6h cycle: %s",
            label,
            LLM_BACKLOG_MAX_DRAIN_PASSES,
            summary,
            extra={"event": LOG_EVENT_LLM_DEGRADED},
        )
    return _aggregate_summaries(summaries) if aggregate else summary


async def dedup_pass_drained() -> dict:
    """dedup_pass, re-run on a short interval while pairs remain deferred."""
    return await _drain_backlog(dedup_pass, _dedup_has_backlog, JOB_LABEL_DEDUP_DRAIN)


async def classify_pending_drained() -> dict:
    """classify_pending, re-run while a full batch keeps making progress."""
    return await _drain_backlog(
        classify_pending_job, _classify_has_backlog, JOB_ID_CLASSIFY_PENDING
    )


async def dedup_pass_drain_now() -> dict:
    """dedup_pass, drained synchronously with no inter-pass sleep.

    For manual/admin entry points where the caller is blocking on the HTTP
    response — the scheduler's 15-min retry interval would stall the request.
    ``retry_seconds=0`` is passed both to this external wrapper (no sleep
    between external re-scans, unchanged) and into ``dedup_pass`` itself (no
    sleep between its now-internal backlog-drain sub-passes either) — this
    entry point has always accepted a full unpaced burst, but it stops as
    soon as a pass leaves as many pairs deferred as the one before.
    """
    return await _drain_backlog(
        lambda: dedup_pass(retry_seconds=0),
        _dedup_backlog_shrinking(),
        JOB_LABEL_DEDUP_DRAIN,
        retry_seconds=0,
        aggregate=True,
    )


async def classify_pending_drain_now() -> dict:
    """classify_pending_job, drained synchronously with no inter-pass sleep.

    For manual/admin entry points where the caller is blocking on the HTTP
    response — the scheduler's 15-min retry interval would stall the request.
    """
    return await _drain_backlog(
        classify_pending_job,
        _classify_has_backlog,
        JOB_ID_CLASSIFY_PENDING,
        retry_seconds=0,
        aggregate=True,
    )
