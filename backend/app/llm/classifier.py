"""LLM event classifier.

One LLM call per canonical event (dedup_group_id IS NULL OR == event.id).
Writes an ``EventClassification`` row and advances ``event.status`` to
``classified``.

Fixed taxonomy (12 categories, 10 vibes) prevents ontology drift.
Any LLM-returned value not in the taxonomy is silently dropped.
"""
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    DEFAULT_USER_LOCALE,
    EVENT_STATUS_CLASSIFIED,
    EVENT_STATUS_DRAFT,
    LLM_CLASSIFY_BATCH_SIZE,
    LLM_CLASSIFY_DESC_FALLBACK,
    LLM_CLASSIFY_LANGUAGE_CODE_MAX_LEN,
    LLM_CLASSIFY_PROMPT_TEMPLATE,
    LLM_CLASSIFY_VENUE_FALLBACK,
    LLM_CLASSIFY_WHY_GO_MAX_BULLETS,
    LLM_MAX_PROMPT_CHARS,
    TALLINN_TZ,
    VALID_CATEGORIES,
    VALID_LOCALES,
    VALID_VIBES,
)
from app.llm.router import LLMError, llm_json
from app.models.models import Event, EventClassification

log = logging.getLogger(__name__)


def _build_classify_prompt(event: Event) -> str:
    desc = (event.description_orig or "").strip()
    if len(desc) > LLM_MAX_PROMPT_CHARS:
        desc = desc[:LLM_MAX_PROMPT_CHARS]
    return LLM_CLASSIFY_PROMPT_TEMPLATE.format(
        title=event.title_orig,
        venue=event.venue_name or LLM_CLASSIFY_VENUE_FALLBACK,
        description=desc or LLM_CLASSIFY_DESC_FALLBACK,
    )


def _parse_classification(raw: dict[str, Any]) -> dict[str, Any]:
    """Extract and validate LLM output. Unknown taxonomy values are dropped."""
    cats = [c for c in raw.get("categories", []) if c in VALID_CATEGORIES]
    vibs = [v for v in raw.get("vibes", []) if v in VALID_VIBES]
    raw_why_go = raw.get("why_go", [])
    if isinstance(raw_why_go, dict):
        why_go_localized = {
            loc: [str(b) for b in raw_why_go.get(loc, [])[:LLM_CLASSIFY_WHY_GO_MAX_BULLETS]]
            for loc in VALID_LOCALES
        }
        why_go_bullets = why_go_localized.get(DEFAULT_USER_LOCALE) or []
    elif isinstance(raw_why_go, list):
        why_go_bullets = [str(b) for b in raw_why_go[:LLM_CLASSIFY_WHY_GO_MAX_BULLETS]]
        why_go_localized = None
    else:
        why_go_bullets = []
        why_go_localized = None
    quality = raw.get("quality")
    try:
        quality = max(0.0, min(1.0, float(quality))) if quality is not None else None
    except (TypeError, ValueError):
        quality = None
    language = str(raw.get("language", "")).strip()[:LLM_CLASSIFY_LANGUAGE_CODE_MAX_LEN] or None
    return {
        "categories": cats,
        "vibes": vibs,
        "why_go_bullets": why_go_bullets,
        "why_go_localized": why_go_localized,
        "quality_score": quality,
        "language_detected": language,
    }


async def classify_event(event: Event, db: AsyncSession) -> bool:
    """Classify a single event and persist the result.

    Returns True on success, False if LLM call failed.
    The caller must commit the session.
    """
    prompt = _build_classify_prompt(event)
    try:
        raw, model_used = await llm_json("classify", prompt, db, event_id=event.id)
    except LLMError as exc:
        log.warning("classify failed for event_id=%d: %s", event.id, exc)
        return False

    parsed = _parse_classification(raw)

    existing = await db.scalar(
        select(EventClassification).where(EventClassification.event_id == event.id)
    )
    if existing is not None:
        existing.categories = parsed["categories"]
        existing.vibes = parsed["vibes"]
        existing.why_go_bullets = parsed["why_go_bullets"]
        existing.why_go_localized = parsed["why_go_localized"]
        existing.quality_score = parsed["quality_score"]
        existing.language_detected = parsed["language_detected"]
        existing.model_used = model_used
        existing.classified_at = datetime.now(tz=TALLINN_TZ)
    else:
        db.add(
            EventClassification(
                event_id=event.id,
                categories=parsed["categories"],
                vibes=parsed["vibes"],
                why_go_bullets=parsed["why_go_bullets"],
                why_go_localized=parsed["why_go_localized"],
                quality_score=parsed["quality_score"],
                language_detected=parsed["language_detected"],
                model_used=model_used,
            )
        )

    event.status = EVENT_STATUS_CLASSIFIED
    log.debug(
        "classified event_id=%d cats=%s vibes=%s quality=%s lang=%s",
        event.id,
        parsed["categories"],
        parsed["vibes"],
        parsed["quality_score"],
        parsed["language_detected"],
    )
    return True


async def classify_pending(db: AsyncSession, *, batch_size: int = LLM_CLASSIFY_BATCH_SIZE) -> dict[str, Any]:
    """Classify all canonical draft events, up to ``batch_size`` per call.

    A "canonical" event is one with ``dedup_group_id IS NULL`` or
    ``dedup_group_id == event.id`` (the representative of its group).

    Returns a summary dict with ``attempted``, ``succeeded``, ``failed`` keys.
    The caller must commit the session.
    """
    rows = (
        await db.scalars(
            select(Event)
            .where(
                Event.status == EVENT_STATUS_DRAFT,
                or_(
                    Event.dedup_group_id.is_(None),
                    Event.dedup_group_id == Event.id,
                ),
            )
            .order_by(Event.id)
            .limit(batch_size)
        )
    ).all()
    events = list(rows)

    attempted = len(events)
    succeeded = 0
    failed = 0

    for event in events:
        ok = await classify_event(event, db)
        if ok:
            succeeded += 1
        else:
            failed += 1

    log.info("classify_pending: attempted=%d succeeded=%d failed=%d", attempted, succeeded, failed)
    return {"attempted": attempted, "succeeded": succeeded, "failed": failed}
