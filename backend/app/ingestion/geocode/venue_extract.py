"""LLM pass mining street addresses glued into venue_name into venue_address."""

import asyncio
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    GEOCODE_MAX_PER_RUN,
    LLM_BATCH_FANOUT_CONCURRENCY,
    LLM_DEDUP_HASH_QUERY_CHUNK_SIZE,
    LLM_TASK_VENUE_EXTRACT,
    VENUE_EXTRACT_MAX_FRESH_LLM_CALLS_PER_RUN,
    VENUE_NAME_DIRECTION_KEYWORDS,
    VENUE_NAME_MAX_LEN,
    VENUE_NAME_PROMPT_MAX_CHARS,
    VENUE_NAME_SUSPECT_MAX_LEN,
)
from app.llm.prompts import LLM_VENUE_EXTRACT_PROMPT_TEMPLATE, escape_prompt_delimiters
from app.llm.router import (
    LLMError,
    content_hash,
    llm_available,
    llm_http_client,
    llm_json,
)
from app.models.models import Event, LlmCall
from app.routers.utils import alternation_pattern

log = logging.getLogger(__name__)

_DIRECTION_KEYWORD_RE = alternation_pattern(VENUE_NAME_DIRECTION_KEYWORDS)


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
            venue=escape_prompt_delimiters(name[:VENUE_NAME_PROMPT_MAX_CHARS])
        )
        for name in by_name
    }
    hashes: dict[str, str] = {name: content_hash(prompt) for name, prompt in prompts.items()}

    cached_decisions = await _prefetch_venue_extract_cache(
        db, list(hashes.values())
    )
    mutated = 0
    mutated_names = 0

    # Filter pass: names needing a fresh call, capped at the run budget in
    # by_name (== candidates) order, so the fan-out below preserves the same
    # deferral priority the old sequential loop had.
    to_call: list[str] = []
    for name in by_name:
        if cached_decisions.get(hashes[name]) is None:
            if len(to_call) >= VENUE_EXTRACT_MAX_FRESH_LLM_CALLS_PER_RUN:
                log.debug("venue-extract: fresh-call budget reached, deferring %r", name)
                continue
            to_call.append(name)

    semaphore = asyncio.Semaphore(LLM_BATCH_FANOUT_CONCURRENCY)

    async def _extract_one(name: str, http_client: httpx.AsyncClient) -> dict | None:
        async with semaphore:
            try:
                # to_call is built from a cached_decisions miss above, so the
                # bulk prefetch already established there is no cached row —
                # pass an empty prefetched_cache so llm_json skips its own
                # per-call SELECT, which would otherwise run concurrently
                # against the shared AsyncSession across in-flight coroutines.
                result, _ = await llm_json(
                    LLM_TASK_VENUE_EXTRACT,
                    prompts[name],
                    db,
                    http_client=http_client,
                    prefetched_cache={},
                )
                return result
            except LLMError as exc:
                log.warning("venue-extract: LLM failed for %r: %s", name, exc)
                return None

    async with llm_http_client() as http_client:
        fresh_results = await asyncio.gather(
            *(_extract_one(name, http_client) for name in to_call),
            return_exceptions=True,
        )
    fresh_by_name: dict[str, dict] = {}
    for name, result in zip(to_call, fresh_results):
        if isinstance(result, BaseException):
            log.error("venue-extract: %r raised during LLM extract: %s", name, result)
            continue
        if result is not None:
            fresh_by_name[name] = result

    for name, events in by_name.items():
        prompt_hash = hashes[name]
        decision: dict | None = cached_decisions.get(prompt_hash)
        if decision is None:
            decision = fresh_by_name.get(name)
        if decision is None:
            continue

        # Validate and apply.
        if not isinstance(decision, dict):
            log.warning("venue-extract: malformed response for %r — skipping", name)
            continue

        raw_address = decision.get("venue_address")
        raw_name = decision.get("venue_name")

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
