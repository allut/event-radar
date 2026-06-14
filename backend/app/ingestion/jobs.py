"""Scheduler job functions for the ingestion pipeline."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import select

from app.constants import (
    LLM_BACKLOG_MAX_DRAIN_PASSES,
    LLM_BACKLOG_RETRY_SECONDS,
    LLM_CLASSIFY_BATCH_SIZE,
)
from app.db import AsyncSessionLocal
from app.dedup.llm_tiebreaker import run_dedup_pass_llm
from app.ingestion.registry import ADAPTER_REGISTRY
from app.models.models import Source

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
                await db.rollback()
            log.exception("ingest source=%s failed", slug)
            raise


async def ingest_all_enabled(kind: str | None = None) -> list[dict]:
    """Run ingestion for all enabled sources (optionally filtered by kind)."""
    async with AsyncSessionLocal() as db:
        q = select(Source).where(Source.enabled.is_(True))
        if kind:
            q = q.where(Source.kind == kind)
        sources = (await db.scalars(q)).all()

    results = []
    for source in sources:
        if source.slug not in ADAPTER_REGISTRY:
            log.debug(
                "no adapter for slug=%s kind=%s — skipping", source.slug, source.kind
            )
            continue
        try:
            result = await ingest_source(source.slug)
            results.append(result)
        except Exception as exc:
            results.append({"slug": source.slug, "error": str(exc)})

    return results


async def dedup_pass() -> dict:
    """Run two-stage deduplication (rule pre-filter + LLM tiebreaker).

    Degrades to the rule-only pass when no LLM provider is configured.
    """
    async with AsyncSessionLocal() as db:
        try:
            summary = await run_dedup_pass_llm(db)
            await db.commit()
            log.info("dedup pass complete: %s", summary)
            return summary
        except Exception:
            await db.rollback()
            log.exception("dedup pass failed")
            raise


async def classify_pending_job() -> dict:
    """Classify canonical draft events via LLM (one batch per call)."""
    from app.llm.classifier import classify_pending

    async with AsyncSessionLocal() as db:
        try:
            summary = await classify_pending(db)
            await db.commit()
            log.info("classify_pending complete: %s", summary)
            return summary
        except Exception:
            await db.rollback()
            log.exception("classify_pending failed")
            raise


async def _drain_backlog(
    run_once: Callable[[], Awaitable[dict]],
    has_backlog: Callable[[dict], bool],
    label: str,
) -> dict:
    """Re-run a single-pass LLM job until its backlog clears or the cap is hit.

    ``run_once`` must open/commit/close its own DB session per call (so no
    connection is held across the sleep). ``has_backlog`` inspects the pass
    summary and returns True while more work remains.
    """
    summary: dict = {}
    for attempt in range(LLM_BACKLOG_MAX_DRAIN_PASSES):
        summary = await run_once()
        if not has_backlog(summary):
            return summary
        if attempt + 1 < LLM_BACKLOG_MAX_DRAIN_PASSES:
            log.info(
                "%s backlog remains, retrying in %ds: %s",
                label,
                LLM_BACKLOG_RETRY_SECONDS,
                summary,
            )
            await asyncio.sleep(LLM_BACKLOG_RETRY_SECONDS)
    log.warning(
        "%s drain cap (%d) reached; backlog deferred to next 6h cycle: %s",
        label,
        LLM_BACKLOG_MAX_DRAIN_PASSES,
        summary,
    )
    return summary


async def dedup_pass_drained() -> dict:
    """dedup_pass, re-run on a short interval while pairs remain deferred."""
    return await _drain_backlog(
        dedup_pass,
        lambda s: s.get("deferred_pairs", 0) > 0,
        "dedup",
    )


async def classify_pending_drained() -> dict:
    """classify_pending, re-run while a full batch keeps making progress."""
    return await _drain_backlog(
        classify_pending_job,
        lambda s: s.get("attempted", 0) >= LLM_CLASSIFY_BATCH_SIZE
        and s.get("succeeded", 0) > 0,
        "classify_pending",
    )
