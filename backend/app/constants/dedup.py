"""Dedup pass windows, fuzzy-match thresholds and chunk sizes."""

# Deduplication
DEDUP_LOOKBACK_DAYS = 30  # only re-cluster events that started within this window
# Upper bound on load_dedup_candidate_events — without it, an event scheduled
# arbitrarily far in the future is loaded as a full ORM object on every dedup
# pass (events rows are never deleted, so nothing else bounds this). Set well
# above any real event's lead time; a future event beyond this window simply
# isn't dedup-clustered until it comes within range on a later run.
DEDUP_LOOKAHEAD_DAYS = 400
TITLE_RATIO_THRESHOLD = 70  # rapidfuzz token_set_ratio threshold for title match
TITLE_RATIO_VENUE_BYPASS_THRESHOLD = 85  # near-exact title; on the LLM path, bypass
# the venue gate at/above this so cross-source dupes with differently-spelled venues
# (incl. cross-language spellings, e.g. "Estonia kontserdisaal" vs "Estonia Concert
# Hall") still reach the LLM tiebreaker (rule-only path stays strict)
VENUE_RATIO_THRESHOLD = 70  # rapidfuzz token_set_ratio threshold for venue match
TIME_WINDOW_HOURS = 12  # max |Δstart| in hours for two events to be dedup candidates
# cluster_events()'s unfiltered fallback (no candidate_pair_ids) is an O(N^2) Python
# enumeration — both production callers always pass pre-filtered pairs, so this path is
# test-only scaffolding today. Hard-cap it so a future caller invoking it on a large
# unfiltered event list fails loudly instead of silently degrading to quadratic time;
# well above any legitimate test's event count.
DEDUP_UNFILTERED_FALLBACK_MAX_EVENTS = 500
# candidate_pair_ids_in_window()'s SQL pair count is roughly N x d (d = events
# sharing a +/-TIME_WINDOW_HOURS neighbourhood) — quadratic in same-window
# listing density rather than in the lookback/lookahead window. Not a hard cap
# (the pass still runs), just a visibility threshold: crossing it logs a
# warning so a density spike shows up instead of silently growing pass time.
DEDUP_CANDIDATE_PAIR_WARN_THRESHOLD = 20000
# Hard cap for the same query — worst case (many events sharing one starts_at)
# is quadratic in same-window listing density with no LIMIT, materializing
# every pair into Python. The query orders newest-first (a.id DESC), so a
# truncated tail is the oldest pairs — earlier passes already saw them — and
# freshly ingested events are never starved. Kept above the warn threshold so
# a warning always fires before truncation would.
DEDUP_CANDIDATE_PAIR_MAX = 50_000

# Dedup summary fields that are a snapshot of corpus state recomputed on every
# pass (total events considered, candidate pairs, group counts) rather than
# work done during that pass — summing them across passes would inflate them
# by roughly a factor of `passes`. _aggregate_summaries (jobs.py) reports the
# last pass's value for these instead of summing.
AGGREGATE_LAST_VALUE_FIELDS = frozenset(
    {"total", "candidate_pairs", "grouped", "groups"}
)

# Rows per bulk UPDATE ... FROM (VALUES ...) in dedup/passes.py::bulk_assign_dedup_groups
# — 2 bind params per row, well under asyncpg's 32767-parameter cap.
DEDUP_BULK_UPDATE_CHUNK_SIZE = 5000

# strftime formats
DEDUP_PROMPT_DATE_FORMAT = "%Y-%m-%d %H:%M"
