"""Scheduler job functions for the ingestion pipeline."""
import logging

from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.dedup.rules import run_dedup_pass
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
            log.info("ingest source=%s raw=%d new=%d", slug, run.raw_count or 0, run.new_count or 0)
            return {"slug": slug, "raw_count": run.raw_count, "new_count": run.new_count}
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
            log.debug("no adapter for slug=%s kind=%s — skipping", source.slug, source.kind)
            continue
        try:
            result = await ingest_source(source.slug)
            results.append(result)
        except Exception as exc:
            results.append({"slug": source.slug, "error": str(exc)})

    return results


async def dedup_pass() -> dict:
    """Run rule-based deduplication over all non-cancelled events."""
    async with AsyncSessionLocal() as db:
        try:
            summary = await run_dedup_pass(db)
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
