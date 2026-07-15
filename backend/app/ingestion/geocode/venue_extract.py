"""LLM pass mining street addresses glued into venue_name into venue_address."""

import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    GEOCODE_MAX_PER_RUN,
    LLM_DEDUP_HASH_QUERY_CHUNK_SIZE,
    LLM_TASK_VENUE_EXTRACT,
    VENUE_EXTRACT_MAX_FRESH_LLM_CALLS_PER_RUN,
    VENUE_NAME_DIRECTION_KEYWORDS,
    VENUE_NAME_MAX_LEN,
    VENUE_NAME_PROMPT_MAX_CHARS,
    VENUE_NAME_SUSPECT_MAX_LEN,
)
from app.llm.prompts import LLM_VENUE_EXTRACT_PROMPT_TEMPLATE
from app.llm.router import LLMError, content_hash, llm_available, llm_json
from app.models.models import Event, LlmCall

log = logging.getLogger(__name__)

_DIRECTION_KEYWORD_RE = re.compile(
    r"\b(" + "|".join(re.escape(kw) for kw in sorted(VENUE_NAME_DIRECTION_KEYWORDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def is_suspect_venue_name(name: str) -> bool:
    """Return True if name likely contains an address or is a direction phrase.

    Flags when: contains a digit, contains a comma, matches a direction keyword,
    or exceeds VENUE_NAME_SUSPECT_MAX_LEN. Clean names like "KUMU" or
    "Sõltumatu Tantsu Lava (STL)" return False.
    """
    if any(ch.isdigit() for ch in name):
        return True
    if "," in name:
        return True
    if _DIRECTION_KEYWORD_RE.search(name):
        return True
    if len(name) > VENUE_NAME_SUSPECT_MAX_LEN:
        return True
    return False


async def _prefetch_venue_extract_cache(
    db: AsyncSession, hashes: list[str]
) -> dict[str, dict]:
    """Bulk-fetch cached venue-extract decisions for the given content hashes.

    One query per chunk (bounded by LLM_DEDUP_HASH_QUERY_CHUNK_SIZE), newest row
    per hash wins (dict overwrite with ascending order). Returns a map of
    content_hash → response_json dict. A row whose response_json is falsy is omitted
    so callers can treat absence as a cache miss.
    """
    cached: dict[str, dict] = {}
    unique_hashes = list(dict.fromkeys(hashes))
    for i in range(0, len(unique_hashes), LLM_DEDUP_HASH_QUERY_CHUNK_SIZE):
        chunk = unique_hashes[i : i + LLM_DEDUP_HASH_QUERY_CHUNK_SIZE]
        rows = (
            await db.execute(
                select(LlmCall.content_hash, LlmCall.response_json)
                .where(
                    LlmCall.task == LLM_TASK_VENUE_EXTRACT,
                    LlmCall.content_hash.in_(chunk),
                    LlmCall.response_json.is_not(None),
                )
                .order_by(LlmCall.created_at)
            )
        ).all()
        for row_hash, response_json in rows:
            if response_json:
                cached[row_hash] = response_json
    return cached


async def extract_address_from_venue_name(db: AsyncSession) -> int:
    """Mine street addresses out of venue_name into venue_address.

    Runs before copy_venue_from_siblings and Nominatim so a freshly-set
    venue_address becomes a geocoding target within the same run, and a NULLed
    junk name is excluded from sibling-copy donors/targets.

    Only processes events where venue_name IS NOT NULL and venue_address IS NULL.
    A Python prefilter skips clean names (no digit, no comma, no direction keyword,
    short) so the LLM only sees suspect strings. Decisions are grouped by the
    venue_name string and cached in llm_calls so identical strings are never
    re-called across runs. A fresh-call budget caps network calls per run.

    Returns the number of events mutated; the caller commits.
    """
    if not llm_available():
        return 0

    candidates = (
        await db.scalars(
            select(Event)
            .where(Event.venue_name.is_not(None), Event.venue_address.is_(None))
            .limit(GEOCODE_MAX_PER_RUN)
        )
    ).all()
    if not candidates:
        return 0

    # Group by venue_name string; only suspect names need LLM.
    by_name: dict[str, list[Event]] = {}
    for event in candidates:
        name = event.venue_name
        if name is None:
            continue
        if not is_suspect_venue_name(name):
            continue
        by_name.setdefault(name, []).append(event)

    if not by_name:
        return 0

    # Build prompts and hashes for bulk prefetch.
    prompts: dict[str, str] = {
        name: LLM_VENUE_EXTRACT_PROMPT_TEMPLATE.format(
            venue=name[:VENUE_NAME_PROMPT_MAX_CHARS]
        )
        for name in by_name
    }
    hashes: dict[str, str] = {name: content_hash(prompt) for name, prompt in prompts.items()}

    cached_decisions = await _prefetch_venue_extract_cache(
        db, list(hashes.values())
    )
    # Invert: hash → name for cache lookup
    fresh_calls = 0
    mutated = 0
    mutated_names = 0

    for name, events in by_name.items():
        prompt_hash = hashes[name]
        result: dict | None = cached_decisions.get(prompt_hash)

        if result is None:
            if fresh_calls >= VENUE_EXTRACT_MAX_FRESH_LLM_CALLS_PER_RUN:
                log.debug("venue-extract: fresh-call budget reached, deferring %r", name)
                continue
            try:
                result, _ = await llm_json(LLM_TASK_VENUE_EXTRACT, prompts[name], db)
                fresh_calls += 1
            except LLMError as exc:
                log.warning("venue-extract: LLM failed for %r: %s", name, exc)
                continue

        # Validate and apply.
        if not isinstance(result, dict):
            log.warning("venue-extract: malformed response for %r — skipping", name)
            continue

        raw_address = result.get("venue_address")
        raw_name = result.get("venue_name")

        new_address: str | None = (raw_address.strip() or None) if isinstance(raw_address, str) else None
        new_name: str | None = (
            (raw_name.strip()[:VENUE_NAME_MAX_LEN] or None)
            if isinstance(raw_name, str)
            else None
        )

        # Only rewrite venue_name when an address was actually mined. Shortening or
        # NULLing the name with no address payoff buys nothing and can break canonical
        # sibling matching (it stranded event 482: "Katharienthal Kohviku" no longer
        # matched its full-named EN sibling). No address → leave the event untouched.
        if new_address is None:
            continue

        for event in events:
            event.venue_address = new_address
            event.venue_name = new_name
            mutated += 1
        mutated_names += 1

    if mutated:
        log.info("venue-extract: mutated %d event(s) across %d distinct name(s)", mutated, mutated_names)
    return mutated
