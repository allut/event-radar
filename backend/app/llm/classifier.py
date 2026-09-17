"""LLM event classifier.

One LLM call per canonical event (dedup_group_id IS NULL OR == event.id).
Writes an ``EventClassification`` row and advances ``event.status`` to
``classified``.

Fixed taxonomy (14 categories, 10 vibes) prevents ontology drift.
Any LLM-returned value not in the taxonomy is silently dropped.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, cast

from sqlalchemy import ColumnElement, exists, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.constants import (
    CURRENCY_CODE_MAX_LEN,
    DEFAULT_CURRENCY,
    DEFAULT_USER_LOCALE,
    EVENT_STATUS_CANCELLED,
    EVENT_STATUS_CLASSIFIED,
    EVENT_STATUS_DRAFT,
    FREE_TIER_KEYWORDS,
    IMPORTANT_INFO_MAX_CHARS,
    LLM_BATCH_FANOUT_CONCURRENCY,
    LLM_CLASSIFY_BATCH_SIZE,
    LLM_CLASSIFY_DESC_FALLBACK,
    LLM_CLASSIFY_EXPLICIT_DEFAULT,
    LLM_CLASSIFY_HAS_FREE_TIER_DEFAULT,
    LLM_CLASSIFY_IMPORTANT_INFO_FALLBACK,
    LLM_CLASSIFY_IN_TARGET_CITY_DEFAULT,
    LLM_CLASSIFY_LANGUAGE_CODE_MAX_LEN,
    LLM_CLASSIFY_NON_EVENT_DEFAULT,
    LLM_CLASSIFY_PRICE_CONTEXT_FALLBACK,
    LLM_CLASSIFY_PRICE_HINT_FALLBACK,
    LLM_CLASSIFY_PRICE_MATCH_TOLERANCE,
    LLM_CLASSIFY_VENUE_FALLBACK,
    LLM_CLASSIFY_WHY_GO_MAX_BULLETS,
    LLM_MAX_PROMPT_CHARS,
    LLM_TASK_CLASSIFY,
    ORGANIZER_SUBMISSION_QUALITY_SCORE_CEILING,
    PRICE_HINT_MAX_CHARS,
    TALLINN_TZ,
    VALID_CATEGORIES,
    VALID_LOCALES,
    VALID_VIBES,
)
from app.llm.prompts import LLM_CLASSIFY_PROMPT_TEMPLATE, escape_prompt_delimiters
from app.ingestion.pricing import (
    eur_amounts_from_text,
    eur_price_bounds_from_text,
    normalize_currency,
    price_context_digest,
    strip_fee_amounts,
)
import httpx

from app.ingestion.sanitize import html_to_text
from app.llm.router import content_hash, llm_http_client, llm_json_or_none
from app.models.models import Event, EventClassification, LlmCall
from app.routers.utils import (
    alternation_pattern,
    canonical_event_filter,
    event_ended_filter,
    event_not_ended_filter,
)

log = logging.getLogger(__name__)

# Single-pass alternation instead of a K=3 any()-over-keywords scan per event
# (Big-O audit #5, item 2.10) — see alternation_pattern's own docstring.
_FREE_TIER_PATTERN = alternation_pattern(FREE_TIER_KEYWORDS)


def _price_context(event: Event) -> str:
    """Price-bearing lines from the FULL (untruncated) description + important_info.

    Distilled separately from the truncated prompt fields so a price tier past
    IMPORTANT_INFO_MAX_CHARS/LLM_MAX_PROMPT_CHARS (e.g. VAN GOGH's weekend/family
    tiers up to €52, past the 1200-char important_info cut) still reaches the LLM.
    """
    return price_context_digest(event.description_orig, event.important_info)


def _build_classify_prompt(event: Event, price_context: str | None = None) -> str:
    desc = (html_to_text(event.description_orig) or "").strip()
    if len(desc) > LLM_MAX_PROMPT_CHARS:
        desc = desc[:LLM_MAX_PROMPT_CHARS]
    price_hint = (event.price_hint or "").strip()[:PRICE_HINT_MAX_CHARS]
    important_info = strip_fee_amounts(html_to_text(event.important_info))
    important_info = (important_info or "").strip()[:IMPORTANT_INFO_MAX_CHARS]
    if price_context is None:
        price_context = _price_context(event)
    return LLM_CLASSIFY_PROMPT_TEMPLATE.format(
        title=escape_prompt_delimiters(event.title_orig),
        venue=escape_prompt_delimiters(event.venue_name or LLM_CLASSIFY_VENUE_FALLBACK),
        description=escape_prompt_delimiters(desc or LLM_CLASSIFY_DESC_FALLBACK),
        important_info=escape_prompt_delimiters(
            important_info or LLM_CLASSIFY_IMPORTANT_INFO_FALLBACK
        ),
        price_hint=price_hint or LLM_CLASSIFY_PRICE_HINT_FALLBACK,
        price_context=price_context or LLM_CLASSIFY_PRICE_CONTEXT_FALLBACK,
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
            if isinstance(raw_why_go.get(loc, []), list)
            else []
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
    non_event = bool(raw.get("non_event", LLM_CLASSIFY_NON_EVENT_DEFAULT))
    in_target_city = bool(
        raw.get("in_target_city", LLM_CLASSIFY_IN_TARGET_CITY_DEFAULT)
    )
    has_free_tier = bool(
        raw.get("has_free_tier", LLM_CLASSIFY_HAS_FREE_TIER_DEFAULT)
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
        "non_event": non_event,
        "in_target_city": in_target_city,
        "has_free_tier": has_free_tier,
    }


def _parse_price(value: Any) -> float | None:
    """Parse an LLM-returned price field. Negative values are treated as unstated."""
    try:
        price = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return price if price is not None and price >= 0 else None


def _validate_llm_prices(
    parsed: dict[str, Any], event: Event, price_context: str | None = None
) -> None:
    """Null out an LLM-reported price_min/price_max not backed by a literal amount
    in the source text. Mutates ``parsed`` in place.

    Guards against invented numbers — most notably the classify prompt's own JSON
    example amounts leaking into the answer (observed as a verbatim "10"/"20" on
    events with no stated price at all). A reported 0 is accepted only alongside a
    free keyword or a literal "0" amount, since "0" is also the model's likely
    guess for "no price found" despite the prompt instructing null for that case.

    Only the €/EUR amounts are extractable from the text (see eur_amounts_from_text),
    so — mirroring the existing hint-widening net's currency gate — a correctly
    detected non-EUR price is trusted as-is rather than being nulled for "not
    matching" a set this function has no way to build for that currency.
    """
    currency_val = parsed["currency"]
    if currency_val is not None and currency_val.upper() != DEFAULT_CURRENCY:
        return

    if price_context is None:
        price_context = _price_context(event)
    text = f"{event.price_hint or ''}\n{price_context}"
    amounts = eur_amounts_from_text(strip_fee_amounts(text))
    lowered = text.lower()
    is_free_signaled = _FREE_TIER_PATTERN.search(lowered) is not None or 0.0 in amounts

    def _is_backed(value: float | None) -> bool:
        if value is None:
            return True
        if value == 0:
            return is_free_signaled
        return any(abs(value - a) <= LLM_CLASSIFY_PRICE_MATCH_TOLERANCE for a in amounts)

    if not _is_backed(parsed["price_min"]):
        parsed["price_min"] = None
    if not _is_backed(parsed["price_max"]):
        parsed["price_max"] = None

    # has_free_tier only makes sense for a paid event (price_min > 0) that also
    # has a free-keyword/€0 mention in the text — otherwise it's an unenforced
    # LLM claim that can survive even after its price_min was just nulled above,
    # surfacing a "free options available" hint with no paid price behind it.
    price_min = parsed["price_min"]
    if parsed["has_free_tier"] and (
        price_min is None or price_min <= 0 or not is_free_signaled
    ):
        parsed["has_free_tier"] = False


def _persist_classification(
    db: AsyncSession,
    event: Event,
    parsed: dict[str, Any],
    model_used: str,
    existing: EventClassification | None,
) -> None:
    """Write the parsed classification to the existing row or insert a new one."""
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


def _reconcile_event_price_fields(event: Event, parsed: dict[str, Any]) -> None:
    """Write LLM-derived prices onto the event — only when ingest set none.

    Ingest-parsed prices are authoritative: Fienta parses price
    deterministically at ingest (price_min set, price_hint None), and the LLM —
    which sees "not stated" for those events and may still infer a number —
    must not overwrite them. price_min gates the whole tier: a source either
    establishes price at ingest (skip LLM price entirely) or defers price
    wholly to the LLM (price_min None → write). Once price_min is set, a later
    reclassify won't refresh price — acceptable; ingest prices are
    deterministic and LLM prices rarely change between runs.

    Before writing, deterministically widens (never shrinks) the LLM's
    envelope to cover any literal €/EUR amount in price_hint it under-reported
    (e.g. a skipped family/group tier). Gated to a None/EUR currency
    (case-insensitive) so a correctly-detected non-EUR price isn't polluted by
    an incidental €-looking match in price_hint.
    """
    if event.price_min is not None:
        return

    currency_val = parsed["currency"]
    if currency_val is None or currency_val.upper() == DEFAULT_CURRENCY:
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
        if (hint_min is not None or hint_max is not None) and parsed["currency"] is None:
            parsed["currency"] = DEFAULT_CURRENCY

    if parsed["price_min"] is not None:
        event.price_min = parsed["price_min"]
    if parsed["price_max"] is not None:
        event.price_max = parsed["price_max"]
    if parsed["currency"] is not None:
        event.currency = parsed["currency"]
    event.has_free_tier = event.has_free_tier or parsed["has_free_tier"]


def _apply_content_flags(event: Event, parsed: dict[str, Any]) -> None:
    """OR-merge all three of the LLM's content flags — a re-classification
    pass (e.g. on an organizer edit) must never *clear* a flag a prior pass
    set, even one with no deterministic keyword floor of its own
    (is_out_of_area, unlike is_explicit/is_non_event, has no prefilter that
    independently re-derives it — see OWASP audit F13)."""
    event.is_explicit = event.is_explicit or parsed["explicit"]
    event.is_non_event = event.is_non_event or parsed["non_event"]
    event.is_out_of_area = event.is_out_of_area or not parsed["in_target_city"]


async def classify_event(
    event: Event,
    db: AsyncSession,
    existing_classification: EventClassification | None = None,
    prefetched: bool = False,
    prompt: str | None = None,
    price_context: str | None = None,
    prefetched_cache: dict[str, tuple[dict[str, Any], str]] | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> bool:
    """Classify a single event and persist the result.

    Returns True on success, False if LLM call failed.
    The caller must commit the session.

    ``prefetched=True`` means the caller has already looked up any existing
    classification (passed via ``existing_classification``). When True, no
    per-event ``SELECT EventClassification`` is issued — the N+1 in the batch
    path collapses to one bulk prefetch.

    ``prompt``, when supplied by a batch caller that already built it for
    cache-key hashing (see ``classify_pending``), is reused instead of being
    rebuilt. ``price_context``, when supplied by that same caller, is reused
    instead of being recomputed — it backs a full BeautifulSoup parse over the
    untruncated description, the most expensive pure-CPU step in this path.
    ``prefetched_cache`` and ``http_client``, when supplied, are
    forwarded to ``llm_json`` so a batch run consults one bulk-loaded cache map
    and one shared HTTP client instead of a per-event ``SELECT`` and connection
    pool — mirrors the dedup tiebreaker's cache-aware batch loop.

    Events already flagged ``is_explicit`` or ``is_non_event`` (Layer 1 keyword
    prefilters) skip the LLM call entirely — token saving — but still advance to
    ``classified`` so a flagged dedup-group representative doesn't strand the
    rest of its cluster in ``draft``. The flags stay True regardless (the
    publish gate and read paths exclude them).
    """
    if event.is_explicit or event.is_non_event:
        event.status = EVENT_STATUS_CLASSIFIED
        return True

    if price_context is None:
        price_context = _price_context(event)
    if prompt is None:
        prompt = _build_classify_prompt(event, price_context=price_context)
    response = await llm_json_or_none(
        LLM_TASK_CLASSIFY,
        prompt,
        db,
        event_id=event.id,
        context=f"classify failed for event_id={event.id}",
        prefetched_cache=prefetched_cache,
        http_client=http_client,
    )
    if response is None:
        return False
    raw, model_used = response

    try:
        parsed = _parse_classification(raw)
    except Exception as exc:  # malformed LLM output shape
        log.warning("classify parse failed for event_id=%d: %s", event.id, exc)
        return False
    _validate_llm_prices(parsed, event, price_context=price_context)
    if (
        event.submitted_by_organizer_id is not None
        and parsed["quality_score"] is not None
    ):
        parsed["quality_score"] = min(
            parsed["quality_score"], ORGANIZER_SUBMISSION_QUALITY_SCORE_CEILING
        )

    if prefetched:
        existing = existing_classification
    else:
        existing = await db.scalar(
            select(EventClassification).where(EventClassification.event_id == event.id)
        )
    _persist_classification(db, event, parsed, model_used, existing)
    _reconcile_event_price_fields(event, parsed)
    _apply_content_flags(event, parsed)

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


def _no_live_dedup_sibling_clause(now: datetime) -> ColumnElement[bool]:
    """True when no other, still-live member points its ``dedup_group_id`` at
    this event's id.

    Guards the bulk-cancel below: a dedup-canonical representative must not be
    cancelled out from under a still-live sibling (same dedup group, not yet
    ended, not already cancelled) — that sibling's ``dedup_group_id`` would
    keep pointing at a cancelled id until the next ``dedup_pass`` reclusters,
    stranding it outside ``canonical_event_filter()`` (and hence unreachable by
    ``classify_pending``) for up to one 6h cycle. Ungrouped events (no row
    references their id as a group) and events with only already-ended or
    already-cancelled siblings are unaffected and cancel normally.
    """
    sibling = aliased(Event)
    return ~exists(
        select(1)
        .select_from(sibling)
        .where(
            sibling.dedup_group_id == Event.id,
            sibling.id != Event.id,
            sibling.status != EVENT_STATUS_CANCELLED,
            event_not_ended_filter(now, entity=sibling),
        )
    )


async def _cancel_ended_drafts(db: AsyncSession, now: datetime) -> int:
    """Bulk-cancel drafts that already ended — they can never pass the publish
    gate, so an LLM call (or batch slot) on them is wasted. Skips a
    dedup-canonical representative with a still-live sibling (see
    _no_live_dedup_sibling_clause) so that sibling isn't orphaned."""
    cancel_result = await db.execute(
        update(Event)
        .where(
            Event.status == EVENT_STATUS_DRAFT,
            event_ended_filter(now),
            _no_live_dedup_sibling_clause(now),
        )
        .values(status=EVENT_STATUS_CANCELLED)
    )
    return cast(CursorResult, cancel_result).rowcount


async def _prefetch_existing_classifications(
    db: AsyncSession, events: list[Event]
) -> dict[int, EventClassification]:
    """Bulk prefetch existing classifications for the whole batch in one query
    (replaces N per-event SELECTs inside classify_event)."""
    if not events:
        return {}
    existing_rows = (
        await db.scalars(
            select(EventClassification).where(
                EventClassification.event_id.in_([e.id for e in events])
            )
        )
    ).all()
    return {row.event_id: row for row in existing_rows}


async def _prefetch_classify_cache(
    db: AsyncSession, prompts_by_event_id: dict[int, str]
) -> dict[str, tuple[dict[str, Any], str]]:
    """Bulk-fetch cached classify LLM responses by content hash — the
    classify-batch analogue of the dedup tiebreaker's
    ``_prefetch_cached_decisions``/venue-extract's ``_prefetch_venue_extract_cache``.
    Passed to ``llm_json`` as ``prefetched_cache`` so each event's cache lookup
    is a local dict access instead of a per-event ``SELECT``.

    A classify prompt embeds title+description+price, so each hash is
    effectively unique across events — a batch rarely finds a hit here. Still
    worth doing for symmetry with the other two LLM passes and because
    ``LLM_CLASSIFY_BATCH_SIZE`` keeps the ``IN (...)`` list small (no chunking
    needed, unlike the dedup pass's much larger candidate-pair hash list).
    """
    if not prompts_by_event_id:
        return {}
    hashes = list({content_hash(p) for p in prompts_by_event_id.values()})
    rows = (
        await db.execute(
            select(LlmCall.content_hash, LlmCall.response_json, LlmCall.provider, LlmCall.model)
            .where(
                LlmCall.content_hash.in_(hashes),
                LlmCall.response_json.is_not(None),
            )
            .order_by(LlmCall.created_at)
        )
    ).all()
    return {
        row_hash: (response_json, f"{provider}/{model}")
        for row_hash, response_json, provider, model in rows
    }


async def classify_pending(
    db: AsyncSession, *, batch_size: int = LLM_CLASSIFY_BATCH_SIZE
) -> dict[str, Any]:
    """Classify all canonical draft events, up to ``batch_size`` per call.

    A "canonical" event is one with ``dedup_group_id IS NULL`` or
    ``dedup_group_id == event.id`` (the representative of its group).

    Before selecting the batch, any draft whose event has already ended
    (``event_ended_filter``) is bulk-cancelled — it can never pass the
    publish gate's ``fail_ended`` check even if classified, so spending an
    LLM call (or a batch slot) on it is wasted, and leaving it in ``draft``
    forever would otherwise strand it there indefinitely once its FIFO
    position falls behind newer arrivals. Excludes a dedup-canonical
    representative that still has a live sibling (see
    ``_no_live_dedup_sibling_clause``) so that sibling isn't orphaned.

    Returns a summary dict with ``attempted``, ``succeeded``, ``failed``,
    ``cancelled`` keys. The caller must commit the session.
    """
    now = datetime.now(tz=TALLINN_TZ)
    cancelled = await _cancel_ended_drafts(db, now)

    rows = (
        await db.scalars(
            select(Event)
            .where(
                Event.status == EVENT_STATUS_DRAFT,
                canonical_event_filter(),
                event_not_ended_filter(now),
            )
            .order_by(Event.id)
            .limit(batch_size)
        )
    ).all()
    events = list(rows)

    attempted = len(events)
    succeeded = 0
    failed = 0

    existing_map = await _prefetch_existing_classifications(db, events)

    # Built once here (not inside classify_event) so the same prompt string
    # backs both the cache prefetch below and the per-event LLM call —
    # skipped for already-flagged events, which never reach the LLM.
    # price_context is built alongside it and passed straight through to
    # classify_event, which would otherwise recompute it — price_context_digest
    # runs a full BeautifulSoup parse over the untruncated description, the
    # most expensive pure-CPU step in this path.
    price_context_by_event_id = {
        event.id: _price_context(event)
        for event in events
        if not (event.is_explicit or event.is_non_event)
    }
    prompts_by_event_id = {
        event.id: _build_classify_prompt(
            event, price_context=price_context_by_event_id[event.id]
        )
        for event in events
        if not (event.is_explicit or event.is_non_event)
    }
    prefetched_cache = await _prefetch_classify_cache(db, prompts_by_event_id)

    semaphore = asyncio.Semaphore(LLM_BATCH_FANOUT_CONCURRENCY)

    async def _classify_one(event: Event) -> bool:
        async with semaphore:
            return await classify_event(
                event,
                db,
                existing_classification=existing_map.get(event.id),
                prefetched=True,
                prompt=prompts_by_event_id.get(event.id),
                price_context=price_context_by_event_id.get(event.id),
                prefetched_cache=prefetched_cache,
                http_client=http_client,
            )

    async with llm_http_client() as http_client:
        results = await asyncio.gather(
            *(_classify_one(event) for event in events), return_exceptions=True
        )
    for event, result in zip(events, results):
        if isinstance(result, BaseException):
            log.error(
                "classify_pending: event_id=%d raised during classify: %s",
                event.id,
                result,
            )
            failed += 1
        elif result:
            succeeded += 1
        else:
            failed += 1

    log.info(
        "classify_pending: attempted=%d succeeded=%d failed=%d cancelled=%d",
        attempted,
        succeeded,
        failed,
        cancelled,
    )
    return {
        "attempted": attempted,
        "succeeded": succeeded,
        "failed": failed,
        "cancelled": cancelled,
    }
