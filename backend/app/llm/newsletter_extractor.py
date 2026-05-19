"""LLM extractor: inbound newsletter email → raw events."""
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    LLM_TASK_NEWSLETTER,
    NEWSLETTER_BODY_MAX_LEN,
    NEWSLETTER_EXTRACT_PROMPT_TEMPLATE,
    NEWSLETTER_SOURCE_SLUG,
    NEWSLETTER_SUBJECT_MAX_LEN,
)
from app.llm.router import LLMError, llm_json
from app.models.models import RawEvent, RawInboundEmail, Source

log = logging.getLogger(__name__)


async def _get_or_create_newsletter_source(db: AsyncSession) -> Source:
    # Use INSERT ... ON CONFLICT DO NOTHING to avoid race conditions under concurrency.
    stmt = (
        pg_insert(Source)
        .values(slug=NEWSLETTER_SOURCE_SLUG, kind="inbound_email", config={}, enabled=True)
        .on_conflict_do_nothing(index_elements=["slug"])
    )
    await db.execute(stmt)
    await db.flush()
    source = await db.scalar(select(Source).where(Source.slug == NEWSLETTER_SOURCE_SLUG))
    assert source is not None, f"Source {NEWSLETTER_SOURCE_SLUG!r} missing after upsert"
    return source


def _is_valid_event(item: Any) -> bool:
    return isinstance(item, dict) and bool(item.get("title"))


async def extract_events_from_email(
    db: AsyncSession,
    *,
    email_id: int,
    subject: str,
    text_body: str,
) -> int:
    """Extract structured events from email via LLM; persist as RawEvents.

    Returns the number of events extracted.
    """
    prompt = NEWSLETTER_EXTRACT_PROMPT_TEMPLATE.format(
        subject=subject[:NEWSLETTER_SUBJECT_MAX_LEN],
        body=text_body[:NEWSLETTER_BODY_MAX_LEN],
    )

    try:
        raw, _model = await llm_json(LLM_TASK_NEWSLETTER, prompt, db)
    except LLMError as exc:
        log.warning("Newsletter LLM extraction failed for email %d: %s", email_id, exc)
        await _mark_processed(db, email_id)
        return 0

    # llm_json always returns a dict (json_object response_format); prompt asks for {"events": [...]}
    events: list[Any] = raw.get("events", [])
    if not isinstance(events, list):
        log.warning("LLM returned non-list events for email %d", email_id)
        await _mark_processed(db, email_id)
        return 0

    source = await _get_or_create_newsletter_source(db)
    count = 0
    for idx, item in enumerate(events):
        if not _is_valid_event(item):
            continue
        raw_event = RawEvent(
            source_id=source.id,
            external_id=f"email-{email_id}-{idx}",
            payload={"inbound_email_id": email_id, **item},
        )
        db.add(raw_event)
        count += 1

    await _mark_processed(db, email_id)
    await db.flush()
    log.info("Extracted %d event(s) from newsletter email %d", count, email_id)
    return count


async def _mark_processed(db: AsyncSession, email_id: int) -> None:
    email = await db.get(RawInboundEmail, email_id)
    if email:
        email.processed_at = datetime.now(timezone.utc)
