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
    CURRENCY_CODE_MAX_LEN,
    DEFAULT_USER_LOCALE,
    EVENT_STATUS_CLASSIFIED,
    EVENT_STATUS_DRAFT,
    IMPORTANT_INFO_MAX_CHARS,
    LLM_CLASSIFY_BATCH_SIZE,
    LLM_CLASSIFY_DESC_FALLBACK,
    LLM_CLASSIFY_EXPLICIT_DEFAULT,
    LLM_CLASSIFY_IMPORTANT_INFO_FALLBACK,
    LLM_CLASSIFY_IN_TARGET_CITY_DEFAULT,
    LLM_CLASSIFY_LANGUAGE_CODE_MAX_LEN,
    LLM_CLASSIFY_PRICE_HINT_FALLBACK,
    LLM_CLASSIFY_PROMPT_TEMPLATE,
    LLM_CLASSIFY_VENUE_FALLBACK,
    LLM_CLASSIFY_WHY_GO_MAX_BULLETS,
    LLM_MAX_PROMPT_CHARS,
    PRICE_HINT_MAX_CHARS,
    TALLINN_TZ,
    VALID_CATEGORIES,
    VALID_LOCALES,
    VALID_VIBES,
)
from app.ingestion.base import eur_price_bounds_from_text, normalize_currency, strip_fee_amounts
from app.llm.router import LLMError, llm_json
from app.models.models import Event, EventClassification

log = logging.getLogger(__name__)


def _build_classify_prompt(event: Event) -> str:
    desc = (event.description_orig or "").strip()
    if len(desc) > LLM_MAX_PROMPT_CHARS:
        desc = desc[:LLM_MAX_PROMPT_CHARS]
    price_hint = (event.price_hint or "").strip()[:PRICE_HINT_MAX_CHARS]
    important_info = strip_fee_amounts(event.important_info)
    important_info = (important_info or "").strip()[:IMPORTANT_INFO_MAX_CHARS]
    return LLM_CLASSIFY_PROMPT_TEMPLATE.format(
        title=event.title_orig,
        venue=event.venue_name or LLM_CLASSIFY_VENUE_FALLBACK,
        description=desc or LLM_CLASSIFY_DESC_FALLBACK,
        important_info=important_info or LLM_CLASSIFY_IMPORTANT_INFO_FALLBACK,
        price_hint=price_hint or LLM_CLASSIFY_PRICE_HINT_FALLBACK,
    )


def _parse_classification(raw: dict[str, Any]) -> dict[str, Any]:
    """Extract and validate LLM output. Unknown taxonomy values are dropped."""
    raw_cats = raw.get("categories", [])
    raw_vibs = raw.get("vibes", [])
    cats = (
        [c for c in raw_cats if isinstance(c, str) and c in VALID_CATEGORIES]
        if isinstance(raw_cats, list)
        else []
    )
    vibs = (
        [v for v in raw_vibs if isinstance(v, str) and v in VALID_VIBES]
        if isinstance(raw_vibs, list)
        else []
    )
    raw_why_go = raw.get("why_go", [])
    if isinstance(raw_why_go, dict):
        why_go_localized = {
            loc: [
                str(b)
                for b in raw_why_go.get(loc, [])[:LLM_CLASSIFY_WHY_GO_MAX_BULLETS]
            ]
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
    language = (
        str(raw.get("language", "")).strip()[:LLM_CLASSIFY_LANGUAGE_CODE_MAX_LEN]
        or None
    )

    price_min = _parse_price(raw.get("price_min"))
    price_max = _parse_price(raw.get("price_max"))
    has_price = price_min is not None or price_max is not None
    currency = normalize_currency(raw.get("currency"), has_price)
    if currency is not None and len(currency) > CURRENCY_CODE_MAX_LEN:
        currency = None

    explicit = bool(raw.get("explicit", LLM_CLASSIFY_EXPLICIT_DEFAULT))
    in_target_city = bool(
        raw.get("in_target_city", LLM_CLASSIFY_IN_TARGET_CITY_DEFAULT)
    )

    return {
        "categories": cats,
        "vibes": vibs,
        "why_go_bullets": why_go_bullets,
        "why_go_localized": why_go_localized,
        "quality_score": quality,
        "language_detected": language,
        "price_min": price_min,
        "price_max": price_max,
        "currency": currency,
        "explicit": explicit,
        "in_target_city": in_target_city,
    }


def _parse_price(value: Any) -> float | None:
    """Parse an LLM-returned price field. Negative values are treated as unstated."""
    try:
        price = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return price if price is not None and price >= 0 else None


async def classify_event(
    event: Event,
    db: AsyncSession,
    existing_classification: EventClassification | None = None,
    prefetched: bool = False,
) -> bool:
    """Classify a single event and persist the result.

    Returns True on success, False if LLM call failed.
    The caller must commit the session.

    ``prefetched=True`` means the caller has already looked up any existing
    classification (passed via ``existing_classification``). When True, no
    per-event ``SELECT EventClassification`` is issued — the N+1 in the batch
    path collapses to one bulk prefetch.

    Events already flagged ``is_explicit`` (Layer 1 keyword prefilter) skip the
    LLM call entirely — token saving — but still advance to ``classified`` so a
    flagged dedup-group representative doesn't strand the rest of its cluster in
    ``draft``. ``is_explicit`` stays True regardless (read paths exclude it).
    """
    if event.is_explicit:
        event.status = EVENT_STATUS_CLASSIFIED
        return True

    prompt = _build_classify_prompt(event)
    try:
        raw, model_used = await llm_json("classify", prompt, db, event_id=event.id)
    except LLMError as exc:
        log.warning("classify failed for event_id=%d: %s", event.id, exc)
        return False

    try:
        parsed = _parse_classification(raw)
    except Exception as exc:  # malformed LLM output shape
        log.warning("classify parse failed for event_id=%d: %s", event.id, exc)
        return False

    if prefetched:
        existing = existing_classification
    else:
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

    # Trust ingest-parsed prices over LLM guesswork: only write LLM-derived prices
    # when ingest set none. Fienta parses price deterministically from the listing
    # price_from_string at ingest (price_min set, price_hint None), so the LLM —
    # which sees "not stated" for those events and may still infer a number — must
    # not overwrite them. price_min gates the whole tier: a source either establishes
    # price at ingest (skip LLM price entirely, keeping Fienta's open-ended price_max
    # None) or defers price wholly to the LLM here (price_min None → write). Trade-off:
    # once price_min is set (by ingest or a prior classify), a later reclassify will
    # not refresh price — acceptable, since ingest prices are deterministic and
    # LLM-set prices rarely change between runs (no provenance flag, no migration).
    if event.price_min is None:
        # Deterministic net: widen (never shrink) the LLM's envelope to cover any
        # literal €/EUR amount in price_hint it under-reported (e.g. skipped a
        # family/group tier). Cannot conflict with prices read from the
        # description, since those aren't reflected in price_hint. Gated to a
        # None/EUR currency (case-insensitively — normalize_currency() passes the
        # LLM's raw string through unchanged, it does not uppercase) so a
        # correctly-detected non-EUR price (e.g. a foreign-currency event) isn't
        # polluted by an incidental €/EUR-looking match elsewhere in price_hint.
        currency_val = parsed["currency"]
        if currency_val is None or currency_val.upper() == "EUR":
            hint_min, hint_max = eur_price_bounds_from_text(
                strip_fee_amounts(event.price_hint)
            )
            if hint_min is not None:
                parsed["price_min"] = (
                    hint_min
                    if parsed["price_min"] is None
                    else min(parsed["price_min"], hint_min)
                )
            if hint_max is not None:
                parsed["price_max"] = (
                    hint_max
                    if parsed["price_max"] is None
                    else max(parsed["price_max"], hint_max)
                )
            if (hint_min is not None or hint_max is not None) and parsed[
                "currency"
            ] is None:
                parsed["currency"] = "EUR"

        if parsed["price_min"] is not None:
            event.price_min = parsed["price_min"]
        if parsed["price_max"] is not None:
            event.price_max = parsed["price_max"]
        if parsed["currency"] is not None:
            event.currency = parsed["currency"]

    event.is_explicit = event.is_explicit or parsed["explicit"]
    event.is_out_of_area = not parsed["in_target_city"]

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


async def classify_pending(
    db: AsyncSession, *, batch_size: int = LLM_CLASSIFY_BATCH_SIZE
) -> dict[str, Any]:
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

    # Bulk prefetch existing classifications for the whole batch in one query
    # (replaces N per-event SELECTs inside classify_event).
    existing_map: dict[int, EventClassification] = {}
    if events:
        event_ids = [e.id for e in events]
        existing_rows = (
            await db.scalars(
                select(EventClassification).where(
                    EventClassification.event_id.in_(event_ids)
                )
            )
        ).all()
        existing_map = {row.event_id: row for row in existing_rows}

    for event in events:
        ok = await classify_event(
            event,
            db,
            existing_classification=existing_map.get(event.id),
            prefetched=True,
        )
        if ok:
            succeeded += 1
        else:
            failed += 1

    log.info(
        "classify_pending: attempted=%d succeeded=%d failed=%d",
        attempted,
        succeeded,
        failed,
    )
    return {"attempted": attempted, "succeeded": succeeded, "failed": failed}
