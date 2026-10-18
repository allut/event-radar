"""LLM router: providers, task names, token/batch limits, classify fallbacks, venue extraction, newsletter extraction."""

from typing import Any

# LLM
LLM_MAX_PROMPT_CHARS = 1200  # cap on event text passed to classification prompt
IMPORTANT_INFO_MAX_CHARS = 1200  # cap on Piletilevi "important info" text in the prompt
PRICE_CONTEXT_MAX_CHARS = 700  # cap on the price-lines digest passed to the prompt
# Cap on each raw text scanned for price lines — bounds request-path work on a
# 30k-char organizer description (OWASP audit M-4).
PRICE_CONTEXT_INPUT_MAX_CHARS = 20_000

LLM_MAX_TOKENS = 400  # max completion tokens per LLM call
LLM_REASONING_MAX_TOKENS = 600  # ceiling (project hard cap); leaves room for reasoning + answer
LLM_DEDUP_CONFIDENCE_THRESHOLD: float = (
    0.7  # minimum confidence to accept LLM same=true verdict
)
LLM_CLASSIFY_BATCH_SIZE = 30  # max events processed per classify_pending run
LLM_REQUEST_TIMEOUT_SECONDS: float = 30.0
LLM_BATCH_FANOUT_CONCURRENCY = 5  # bounded in-flight LLM calls for classify/dedup/venue-extract batches

LLM_DEDUP_TITLE_MAX_LEN = 200
LLM_DEDUP_VENUE_MAX_LEN = 100
# llm_calls.task label for the dedup tiebreaker LLM call — shared by the fresh-call
# site and the cache-prefetch query so they can never drift out of sync.
LLM_TASK_DEDUP = "dedup"
# Bounds fresh (cache-miss) network calls per pass — bounds DB session lifetime
# against a slow or rate-limited fallback provider. Cache hits are cheap
# indexed lookups and are NOT counted against this cap; see llm_tiebreaker.py.
LLM_DEDUP_MAX_FRESH_LLM_CALLS_PER_PASS = 100
# Chunk size for the bulk llm_calls prefetch IN-list, to bound query size.
LLM_DEDUP_HASH_QUERY_CHUNK_SIZE = 500

# Backlog drain: when a periodic LLM job (dedup / classify) finishes a pass with
# work still undone, re-run it on this short interval instead of waiting for the
# next 6h cycle. Bounded by a pass cap so a provider outage can't spin forever.
LLM_BACKLOG_RETRY_SECONDS = 900  # 15 min between drain passes
LLM_BACKLOG_MAX_DRAIN_PASSES = 12  # ceiling; then defer to the next 6h cycle

LLM_CLASSIFY_WHY_GO_MAX_BULLETS = 3
# Per-bullet cap and scrub for LLM "why go" text that ships verbatim in the
# digest (OWASP audit L-5): URLs/emails are stripped, an explicit bullet is
# dropped.
LLM_CLASSIFY_WHY_GO_BULLET_MAX_CHARS = 200
LLM_OUTPUT_URL_OR_EMAIL_RE = r"(?:https?://|www\.)\S+|\S+@\S+\.\S+"
LLM_CLASSIFY_LANGUAGE_CODE_MAX_LEN = 5

LLM_CLASSIFY_VENUE_FALLBACK = "unknown"
LLM_CLASSIFY_DESC_FALLBACK = "(no description)"
LLM_CLASSIFY_PRICE_HINT_FALLBACK = "not stated"
LLM_CLASSIFY_IMPORTANT_INFO_FALLBACK = "(none)"
LLM_CLASSIFY_PRICE_CONTEXT_FALLBACK = "(none)"
LLM_CLASSIFY_EXPLICIT_DEFAULT = False
# llm_calls.task label for the stand-alone Promotion restriction assessment
# (organizer edits and the launch backfill).
LLM_TASK_PROMOTION_RESTRICTION = "promotion_restriction"
LLM_CLASSIFY_NON_EVENT_DEFAULT = False
LLM_CLASSIFY_IN_TARGET_CITY_DEFAULT = True
LLM_CLASSIFY_HAS_FREE_TIER_DEFAULT = False
# Tolerance (EUR) for matching an LLM-reported price against amounts literally
# present in price_hint/price_context — guards against float round-trip noise
# while still rejecting a genuinely invented number.
LLM_CLASSIFY_PRICE_MATCH_TOLERANCE = 0.01
# llm_calls.task label for the classification LLM call.
LLM_TASK_CLASSIFY = "classify"

# Venue address extraction — LLM pass that mines street addresses out of venue_name
# into venue_address so the event becomes geocodable.
LLM_TASK_VENUE_EXTRACT = "venue_extract"
# et/en direction markers that flag a venue_name as likely containing an address or
# being a pure direction phrase rather than a real venue name.
VENUE_NAME_DIRECTION_KEYWORDS: frozenset[str] = frozenset(
    {
        "algus",
        "kõrval",
        "asuv",
        "ees",
        "vastas",
        "juures",
        "taga",
        "meeting point",
        "in front of",
        "next to",
        "near",
    }
)
# A venue_name longer than this is treated as suspect (direction phrases run long).
VENUE_NAME_SUSPECT_MAX_LEN = 40
# Fresh (cache-miss) LLM call budget per geocode run for venue extraction.
VENUE_EXTRACT_MAX_FRESH_LLM_CALLS_PER_RUN = 50
# Max chars of venue_name fed into the extraction prompt.
VENUE_NAME_PROMPT_MAX_CHARS = 200


# Newsletter inbound email extraction
LLM_TASK_NEWSLETTER = "newsletter_extract"

NEWSLETTER_SUBJECT_MAX_LEN = 200
NEWSLETTER_BODY_MAX_LEN = 1500

LLM_PROVIDERS: list[dict[str, Any]] = [
    {
        "name": "groq",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "openai/gpt-oss-120b",
        "key_attr": "GROQ_API_KEY",
        # gpt-oss-120b is a reasoning model: reasoning tokens precede the answer
        # and count against max_tokens, so it gets a larger cap and lower effort.
        "max_tokens": LLM_REASONING_MAX_TOKENS,
        "params": {"reasoning_effort": "low"},
    },
    {
        "name": "cloudflare",
        # Base URL embeds the account id, so it comes from settings, not a literal here.
        "base_url_attr": "CLOUDFLARE_WORKERS_AI_BASE_URL",
        "model": "@cf/openai/gpt-oss-120b",
        "key_attr": "CLOUDFLARE_WORKERS_AI_API_KEY",
        # Same reasoning model as the Groq primary: reasoning tokens precede the
        # answer and count against max_tokens, so it gets a larger cap and lower effort.
        "max_tokens": LLM_REASONING_MAX_TOKENS,
        "params": {"reasoning_effort": "low"},
    },
    {
        "name": "mistral",
        "base_url": "https://api.mistral.ai/v1",
        "model": "mistral-small-latest",
        "key_attr": "MISTRAL_API_KEY",
    },
]

# An event whose suspect venue_name the LLM resolved to "no address" is not
# re-offered to the venue-extract pass until this window passes
# (events.venue_extract_attempted_at). Without it such rows requalify every run
# and, once GEOCODE_MAX_PER_RUN of them exist, starve newer candidates.
VENUE_EXTRACT_RETRY_INTERVAL_DAYS = 7
