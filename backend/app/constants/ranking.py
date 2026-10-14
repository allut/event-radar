"""Ranking and browse: Daily 5, score weights, signals, time slots, browse sorting and pagination, onboarding personas."""

from app._generated.shared_constants import (
    PERSONA_MAX_SELECTABLE,
    PERSONA_PRIMARY_WEIGHT,
    PERSONA_SECONDARY_WEIGHT,
    PERSONA_TERTIARY_WEIGHT,
    VALID_SIGNALS,
)

# Weight assigned to a persona by its rank (index) in the onboarding selection —
# index 0 (first pick) leads the feed, subsequent picks mix in at a lower weight.
PERSONA_RANK_WEIGHTS: tuple[float, ...] = (
    PERSONA_PRIMARY_WEIGHT,
    PERSONA_SECONDARY_WEIGHT,
    PERSONA_TERTIARY_WEIGHT,
)
# Guard: onboarding.py indexes PERSONA_RANK_WEIGHTS[i] for i up to PERSONA_MAX_SELECTABLE - 1.
# If persona_max_selectable is ever raised in shared/app-config.json without adding a
# matching weight here, that indexing would raise an uncaught IndexError instead of a
# clean validation error — fail fast at import time instead.
assert len(PERSONA_RANK_WEIGHTS) == PERSONA_MAX_SELECTABLE, (
    "PERSONA_RANK_WEIGHTS must have exactly PERSONA_MAX_SELECTABLE entries"
)

# Users per page in build_daily_feeds (score.py) — bounds the per-page
# personas_by_user/fb_by_user dicts and the event_rows x users
# scoring loop in RAM regardless of total registered-user count.
FEED_BUILD_USER_BATCH_SIZE = 500

# Ranking / scoring
DAILY_5_COUNT = 5
DAILY_5_MAX_PER_CATEGORY = 2
DAILY_5_BACKFILL_MAX_PER_CATEGORY = 3  # relaxed per-category cap during backfill;
# Tier-1 MMR keeps DAILY_5_MAX_PER_CATEGORY (2). Exceeded only by the final
# uncapped sweep, so the feed still reaches DAILY_5_COUNT when events are scarce.
DAILY_5_LOOKAHEAD_DAYS = 14
# _select_with_backfill truncates each scored pool to n * this multiplier via
# heapq.nlargest before running the MMR/backfill tiers, instead of sorting the
# whole pool — generous enough that the full-sort fallback is rarely needed
# (score.py Big-O audit H6).
DAILY_5_BACKFILL_TRUNCATION_MULTIPLIER = 40
# How many past days' feeds to scan for a recurring-series repeat before allowing
# that series back into a user's Daily 5 pool — keeps a multi-day series (one
# canonical event per day) from being re-picked night after night.
DAILY5_SERIES_COOLDOWN_DAYS = 3
RECENCY_DECAY_DAYS = 21
FEEDBACK_DECAY_BASE: float = 0.9  # per-day decay on feedback signal
FEEDBACK_INDIRECT_WEIGHT: float = 0.5  # weight of category-matched indirect signal
SCORE_HARD_EXCLUDE: float = (
    -2.0
)  # sentinel: outside [-1,1] clamp, cannot be a valid score
NEUTRAL_SCORE: float = 0.5  # neutral midpoint returned when a signal's data is unknown
SCORE_WEIGHT_AFFINITY: float = 0.45
SCORE_WEIGHT_RECENCY: float = 0.20
SCORE_WEIGHT_FEEDBACK: float = 0.20
SCORE_WEIGHT_QUALITY: float = 0.10
SCORE_WEIGHT_LOCALITY: float = 0.05
# Anonymous /explore scoring (#234): feedback_signal (0.20) is dropped — no
# event-level aggregate feedback signal exists anywhere in the codebase.
# persona_affinity keeps SCORE_WEIGHT_AFFINITY unchanged (it already returns
# NEUTRAL_SCORE with no persona). The freed 0.20 is redistributed by uniformly
# scaling the three remaining differentiating terms by 1/0.80 — a pure
# rescale that preserves their relative influence.
SCORE_WEIGHT_ANON_RECENCY: float = 0.25
SCORE_WEIGHT_ANON_QUALITY: float = 0.125
SCORE_WEIGHT_ANON_LOCALITY: float = 0.0625
# _time_slots_for_event() memoization cap (ranking/score.py) — bounds an lru_cache keyed
# on distinct starts_at values so repeated calls across users scoring the same event
# don't redo the astimezone conversion. Comfortably above the number of distinct
# starts_at values in one DAILY_5_LOOKAHEAD_DAYS candidate window.
TIME_SLOTS_CACHE_MAXSIZE = 4096

# Chunk size for the bulk pg_insert(...).on_conflict_do_update(...) upserts in
# build_daily_feeds (_persist_new_scores / _persist_daily_feeds). The Postgres
# wire protocol caps bind parameters at 32767 (int16); with 4 params/row and a
# realistic ~30 users x ~300 candidate events, a single unchunked statement can
# exceed that limit and raise at execute time. 1000 rows/chunk stays comfortably
# under the limit at either table's column count and mirrors the chunking
# already used for the LLM dedup hash IN-list (LLM_DEDUP_HASH_QUERY_CHUNK_SIZE).
SCORE_INSERT_CHUNK_SIZE = 1000

# GET /explore (app/routers/browse.py) — event discovery / search page.
# BROWSE_PAGE_SIZE itself is cross-stack (shared/app-config.json → app._generated.shared_constants).
BROWSE_MAX_PAGE_SIZE: int = 60
# ?q= keyword search — _keyword_filter builds a %...% pattern against two
# trigram GIN indexes; an unbounded string is cheap to send and expensive to
# scan, and RATE_LIMIT_BROWSE alone doesn't bound the per-request cost.
BROWSE_QUERY_MAX_LEN: int = 200

# Shared pagination validation floors — every `limit`/`offset` Query() across
# admin.py/browse.py/feedback.py enforces the same lower bound; centralized so
# it can't drift per-endpoint.
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MIN_OFFSET: int = 0
# The matching offset ceiling, PAGINATION_MAX_OFFSET, is cross-stack
# (shared/app-config.json → app._generated.shared_constants): `ge=` alone
# leaves offset unbounded, so an offset like 5_000_000 makes Postgres walk and
# discard that many rows on every request at the endpoint's full rate limit.
# The numbered pager (spec #551) caps its last reachable page at the same
# value, so a deep list shows "… of N+" instead of linking to a 422.
# Candidate cap for the Python-scored path (Path B: for_you=True OR sort=relevance —
# so also date/price/quality sort *under* for_you=True, not just relevance). Sorted
# soonest-first before capping, so the cap policy is a deliberate soonest-bias, not
# an arbitrary truncation: a date sort still yields globally-correct soonest-first
# results, but price/quality sort under for_you=True is only a true sort within the
# soonest BROWSE_RELEVANCE_MAX_CANDIDATES matches, not a global one — an accepted
# Path-B approximation at MVP scale (`total` in the response reflects at most this
# many rows when the cap is hit; see browse.py docstring).
BROWSE_RELEVANCE_MAX_CANDIDATES: int = 300
# _browse_scored_path scores+sorts the full (capped) candidate pool on every
# call, then slices a page — so every page of /explore pays
# O(candidates) again even though the ranked order didn't change.
# Memoizing the scored-and-sorted id list keyed by (user, filters, sort) turns
# an N-page read into one scoring pass. Short TTL bounds staleness (a like/
# dislike made mid-scroll takes up to this long to affect ranking); small
# max-entries bounds process memory — single Render process, no cross-process
# cache needed.
BROWSE_SCORE_CACHE_TTL_SECONDS: float = 30.0
# Raised from 512 (Big-O audit M10): at "hundreds of active users" toggling
# facets within one 30s TTL window, 512 distinct (user, filter) keys thrashed
# the LRU toward a near-zero hit rate. Each entry is a scored id list bounded
# by BROWSE_RELEVANCE_MAX_CANDIDATES (300), so this is still a small,
# single-process, bounded cache — not a per-row cost.
BROWSE_SCORE_CACHE_MAX_ENTRIES: int = 2048
# Fixed sentinel in place of a real user id for the anonymous-caller cache key
# (#234) — anonymous /explore traffic shares one cache entry per filter/sort
# combination rather than one per caller. Never collides with a real User.id
# (Postgres serial PKs start at 1).
BROWSE_ANON_CACHE_SENTINEL: int = 0
# How far back browse.py::_load_feedback_context looks for a user's like/dislike
# history when scoring /explore (Path B). user_event_feedback is preserved
# indefinitely by policy (see docs/backend-ops.md "Data Retention"), so an unbounded load
# grows with the user's lifetime activity on every /explore request. The
# FEEDBACK_DECAY_BASE (0.9) decay makes a signal this old numerically
# negligible (0.9^90 ~= 0.0000265) to score_event() anyway, so the cutoff drops
# no meaningfully-weighted signal.
FEEDBACK_HISTORY_LOOKBACK_DAYS = 90

# For-you soft-filter: events below this persona_affinity() score ([0, 1], see
# ranking/score.py) are hidden from the For-you pool. Tuned below NEUTRAL_SCORE (0.5)
# so an event with no strong signal either way still surfaces; only a
# below-neutral (poor) match is filtered out.
BROWSE_FORYOU_MIN_AFFINITY: float = 0.4
BROWSE_SORT_RELEVANCE = "relevance"
BROWSE_SORT_DATE = "date"
BROWSE_SORT_PRICE = "price"
BROWSE_SORT_QUALITY = "quality"
VALID_BROWSE_SORTS: frozenset[str] = frozenset(
    {BROWSE_SORT_RELEVANCE, BROWSE_SORT_DATE, BROWSE_SORT_PRICE, BROWSE_SORT_QUALITY}
)
# Sorts expressible as pure SQL ORDER BY — reachable via Path A (_browse_sql_path)
# when for_you=False. relevance always needs Python scoring (persona affinity),
# so it's deliberately excluded.
BROWSE_SQL_SORTS: frozenset[str] = frozenset(
    {BROWSE_SORT_DATE, BROWSE_SORT_PRICE, BROWSE_SORT_QUALITY}
)
# Sentinel for "no comparable value" in a Python sort key (e.g. missing quality_score),
# so unranked rows always sort last regardless of ascending/descending direction.
BROWSE_NEG_INF = float("-inf")
# /users/me preferred_categories/preferred_vibes (serialize_user) — a persona
# affinity_vector entry counts as "in the user's taste" once its weight clears this
# bar. Used by the frontend to decide the For-you⇄All-events auto-flip.
PREFERRED_TASTE_MIN_WEIGHT: float = 0.5

# Feedback signals
SIGNAL_LIKE = "like"
SIGNAL_DISLIKE = "dislike"
SIGNAL_BOOKMARK = "bookmark"
# Explicit preference signals — current-state (one row per user/event), enforced by
# the partial unique index in migration 0019. "view"/"click_external" (the rest of
# VALID_SIGNALS) are passive analytics signals that stay append-only/multi-row and
# must never share that index — see feedback.py::record_feedback.
PREFERENCE_SIGNALS: frozenset[str] = frozenset(
    {SIGNAL_LIKE, SIGNAL_DISLIKE, SIGNAL_BOOKMARK}
)
# Guard: if shared/app-config.json signals ever diverge from these sentinels, fail fast.
assert SIGNAL_LIKE in VALID_SIGNALS, f"{SIGNAL_LIKE!r} missing from VALID_SIGNALS in shared/app-config.json"
assert SIGNAL_DISLIKE in VALID_SIGNALS, f"{SIGNAL_DISLIKE!r} missing from VALID_SIGNALS in shared/app-config.json"
assert SIGNAL_BOOKMARK in VALID_SIGNALS, f"{SIGNAL_BOOKMARK!r} missing from VALID_SIGNALS in shared/app-config.json"
assert PREFERENCE_SIGNALS <= VALID_SIGNALS, "PREFERENCE_SIGNALS must be a subset of VALID_SIGNALS"
# SQL predicate for the migration-0019 partial unique index over preference
# signals. Derived from PREFERENCE_SIGNALS so the upsert's index_where can never
# drift from the set of signals it covers. sorted() makes it deterministic;
# element order is irrelevant to Postgres ON CONFLICT arbiter selection, which
# matches by predicate implication, so this stays equivalent to migration 0019.
PREFERENCE_SIGNALS_SQL_PREDICATE = "signal IN ({})".format(
    ", ".join(f"'{s}'" for s in sorted(PREFERENCE_SIGNALS))
)

# Partial-index predicate for the passive analytics signals ("view"/
# "click_external" — everything in VALID_SIGNALS outside PREFERENCE_SIGNALS):
# migration 0055's one-row-per-(user, event, signal, UTC day) unique index
# (OWASP audit #9). Derived from PREFERENCE_SIGNALS like the predicate above.
PASSIVE_SIGNALS_SQL_PREDICATE = f"NOT ({PREFERENCE_SIGNALS_SQL_PREDICATE})"

# Time-of-day / day-of-week slots derived from event.starts_at (Europe/Tallinn).
# An event can match multiple slots simultaneously (e.g. Saturday evening → weekend + evening).
# late_night: 22:00–05:59  |  evening: 18:00–21:59  |  daytime: 10:00–17:59  |  morning: 06:00–09:59
# weekend: Sat/Sun  |  weekday: Mon–Fri
TIME_SLOT_LATE_NIGHT = "late_night"
TIME_SLOT_EVENING = "evening"
TIME_SLOT_DAYTIME = "daytime"
TIME_SLOT_MORNING = "morning"
TIME_SLOT_WEEKEND = "weekend"
TIME_SLOT_WEEKDAY = "weekday"
WEEKEND_START_WEEKDAY = 5  # Monday=0 … Saturday=5, Sunday=6

VALID_TIMES: frozenset[str] = frozenset(
    {
        TIME_SLOT_LATE_NIGHT,
        TIME_SLOT_EVENING,
        TIME_SLOT_DAYTIME,
        TIME_SLOT_MORNING,
        TIME_SLOT_WEEKEND,
        TIME_SLOT_WEEKDAY,
    }
)
TIME_LATE_NIGHT_START = 22
TIME_EVENING_START = 18
TIME_DAYTIME_START = 10
TIME_MORNING_START = 6

# routers/browse.py, routers/feedback.py
ERROR_INVALID_SORT = "sort must be one of {sorts}"
ERROR_INVALID_SIGNAL = "Invalid signal. Must be one of: {signals}"
ERROR_INVALID_PREFERENCE_SIGNAL = "signal must be one of: {signals}"

# routers/onboarding.py
ERROR_PERSONA_COUNT = "Select between 1 and {max_selectable} personas."
ERROR_PERSONA_DUPLICATE = "Persona slugs must not repeat."
ERROR_PERSONA_UNKNOWN = "Unknown persona slug(s): {missing}"
