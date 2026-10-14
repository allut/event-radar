# Pipeline

What's in here: the stage sequence, ingestion, dedup, classification, ranking, the Daily 5 builder, the publish gate, geocoding, detail-refetch, read paths, the Fienta organizer lifecycle, LLM limits and content filters.

## Data Flow

Each stage runs as a scheduled job. [backend-ops.md](backend-ops.md)'s Scheduled Jobs section owns the cadences and their order.

1. **Ingestion** — source adapters fetch and normalize events. See Ingestion.
2. **Deduplication** — rules, then an LLM tiebreaker, group duplicates under one canonical event. See Deduplication.
3. **Classification** — the LLM assigns taxonomy, quality, prices and filter flags. See Classification.
4. **Ranking** — a weighted score orders events per user. See Ranking.
5. **Daily 5 builder** — picks five diverse events per user. See Daily 5 Builder.
6. **Publish gate** — promotes `classified` events to `published`. See Publish Gate.
7. **Geocoding backfill** — fills missing coordinates. See Geocoding Backfill.
8. **Detail-refetch sync** — reconciles stored fields against each event's source page. See Detail-Refetch Sync.

## Ingestion

### Sources

- **Fienta is polled through its API.** `app/ingestion/sources/fienta.py` reads its organizer ids from the database; see Organizer Lifecycle (Fienta).
- **Piletilevi, KUMU and Estonia Concert Hall are HTML listing scrapers.** All three subclass `app/ingestion/sources/html_base.py::HtmlListingAdapter`.
- **Organizer self-submission has no polling adapter.** `POST /organizer/events` inserts on the `user_submission` source through `app/ingestion/adapter.py::insert_normalized_event()`. See [organizer-portal.md](organizer-portal.md).
- **Telliskivi, Kultuurikatel and Fotografiska are `enabled=False`** in `app/ingestion/registry.py`. Telliskivi's data was unfixably mis-dated. The other two wait for a rewrite onto `HtmlListingAdapter`.
- **Eventbrite was never added.** Its API closed to non-partners before integration.

### Fienta Detail Merge

For each new Fienta event, one not yet in `event_sources`, the adapter also fetches the detail page. It parses the schema.org JSON-LD into `raw["_detail"]`, with fetches bounded by `DETAIL_FETCH_CONCURRENCY`.

`fienta.py::normalize()` merges listing and detail by a fixed per-field authority, with no LLM involved:

| Field | Authority |
|---|---|
| `venue_name` | Listing wins; detail fills when missing |
| `venue_address` | The side carrying a 5-digit postal code; else listing wins, detail fills when empty |
| `lat` / `lng` | Detail JSON-LD only, gated to Estonia by `coords_in_estonia` |
| `price_min` / `price_max` | Listing's `app/ingestion/pricing.py::parse_price_from_string` baseline; a present detail offer price overrides each bound |

- **A missing `_detail` degrades to listing-only.** The merge never blocks ingest on a failed detail fetch.

### Skip Set

- **Adapters skip ids from `app/ingestion/adapter.py::ingest_skip_ids()`, not just stored ones.** It unions stored `event_sources` external ids with `raw_events` ids fetched within `INGEST_REJECT_RECHECK_DAYS` (7).
- **That stops a rejected event from being re-fetched every hourly run.** An event `normalize()` rejected gets one recheck a week instead.

### Images

- **Image URLs are rewritten to full resolution at ingest.** `html_base.py::full_res_wp_image()` strips WordPress's `-WxH` thumbnail suffix for concert.ee and kumu.ekm.ee. `piletilevi.py::full_res_piletilevi_image()` rewrites the `/height=N/` path segment. Their constants live in `app/ingestion/selectors.py`.

### Newsletter Inbound

- **The newsletter path is landed but dormant.** `app/routers/webhooks.py` accepts a Resend Inbound webhook, and `app/llm/newsletter_extractor.py` can parse it.
- **Its `raw_events` rows never become `events`.** `registry.py` registers the newsletter source without an adapter, so it is absent from `ADAPTER_REGISTRY`.
- **Extraction is skipped for every sender by default.** `NEWSLETTER_SENDER_ALLOWED_DOMAINS` is empty. See [security.md](security.md)'s Inbound Mail Webhook section before adding a domain.

## Deduplication

### Candidate Pairs

- **Dedup has two stages so the LLM sees few pairs.** A rule pre-filter (`app/dedup/rules.py`) runs first. The LLM tiebreaker (`app/dedup/llm_tiebreaker.py`) judges only the pairs that survive.
- **The scheduled `dedup_pass` runs `run_dedup_pass_llm`.** It falls back to the rule-only `run_dedup_pass` when no LLM provider key is set.
- **Near-exact titles bypass the venue check on the LLM path.** At `title_ratio >= TITLE_RATIO_VENUE_BYPASS_THRESHOLD` (85), cross-source duplicates with differently spelled venues still reach the tiebreaker. That includes cross-language spellings.

### Same-Day Title Unions

- **`apply_same_day_title_unions` groups same-day slots without an LLM call.** Events sharing a normalized title, a Tallinn calendar day and a compatible venue collapse into one group. `_venue_compatible` treats an unknown venue as compatible.
- **This folds timed-entry slots into one canonical event**, such as a museum's many same-day slots. The LLM path skips these pairs (`same_group`).
- **Multi-day series are not grouped across days.** Each day keeps its own canonical event. The Daily 5 builder and the Landing showcase collapse series at read time instead.

### Group Representative

The canonical member of a group is the one with `dedup_group_id == id`. It is chosen by these keys, in order:

1. **Status** — `_representative_status_rank` pins a published or classified member ahead of a draft one.
2. **Claim** — a claimed member beats an unclaimed one (`claimed_event_ids`).
3. **Quality** — `_event_quality_rank` prefers price, address, coordinates and description.
4. **Id** — `min(event_id)` breaks any remaining tie.

### Claimed Events

- **`load_claims_for_events()` finds each candidate's approved Claim by durable key, never by event id.** The key is a resolved `EventSource.publisher_id`, or else a recomputed Piletilevi `event_series_key`. So a re-ingested occurrence row re-matches its claim like the original did.
- **The recomputed series key uses that row's own `title_orig` and resolved venue name.** A linked `Venue`'s name wins over `Event.venue_name`, as in `resolve_venue_name()`.
- **Organizer retirement and source disablement need no claim-side handling.** They change `Publisher.status` and `Source.enabled`, and the claim lookup joins neither.
- **When two claimed events collide, `resolve_claim_dormancy()` makes the losing Claim a Dormant claim.** The winner is chosen as for any collision. The loser's pins stop applying, but the row is never deleted or revoked. The representative's own claim reactivates in the same pass.
- **Dormancy doesn't loosen duplicate-claim creation.** `Claim.status` still gates it. See `CONTEXT.md`'s Dormant claim entry.

## Classification

The LLM classifies each event against a fixed category and vibe taxonomy (`VALID_CATEGORIES`, `VALID_VIBES`). A fixed taxonomy prevents ontology drift. It also returns a 0–1 quality score and three "why go?" bullets.

| LLM output | Stored as |
|---|---|
| `is_explicit` | `Event.is_explicit` (NSFW layer 2) |
| `non_event` | OR-merged into `Event.is_non_event` (non-event layer 2) |
| `in_target_city` | Inverted into `Event.is_out_of_area`, read by the publish gate |
| `price_min` / `price_max` / `currency` | Parsed from `price_hint`, capped at `PRICE_HINT_MAX_CHARS` |
| `has_free_tier` | OR-merged into `Event.has_free_tier`; never unset once true |

### Prices

- **Ingest-set prices are authoritative.** `classify_event` writes LLM prices only when `event.price_min is None`. A source that parses prices at ingest, like Fienta, shows the LLM "not stated", so its answer must not overwrite them.
- **On the LLM-priced path, `_reconcile_event_price_fields` widens the envelope and never shrinks it.** It covers any literal €/EUR amount in `price_hint` (`eur_price_bounds_from_text` over `strip_fee_amounts`), catching a tier the model missed.
- **The widening only applies when the currency is unset or EUR.** A correctly detected non-EUR price stays clean of incidental €-looking matches.
- **`has_free_tier` only applies to a paid event (`price_min > 0`).** The classifier zeroes a hallucinated flag on a free event.

### Skipped and Ended Events

- **Events flagged by a layer-1 keyword prefilter skip the LLM call but still advance to `classified`.** Otherwise a flagged dedup representative would strand its whole group in `draft`.
- **`classify_pending` cancels ended drafts before each batch.** They can never pass the publish gate, so an LLM call on them is wasted.
- **The sweep spares a dedup representative with a live sibling** (`app/events/queries.py::no_live_dedup_sibling_clause()`). Cancelling it would orphan the sibling outside `canonical_event_filter()` until the next dedup pass.

## Ranking

`app/ranking/score.py` sums weighted terms. The weights are `SCORE_WEIGHT_*` constants in `app/constants/ranking.py`.

| Term | Signed in | Signed out |
|---|---|---|
| `persona_affinity` | 0.45 | 0.45 × a neutral constant |
| `recency_boost` | 0.20 | 0.25 |
| `feedback_signal` | 0.20 | dropped |
| `quality_score` | 0.10 | 0.125 |
| `locality_bonus` | 0.05 | 0.0625 |

- **`feedback_signal` maps the raw `[-1, 1]` feedback score to `[0, 1]` before weighting**, as `(fb + 1.0) / 2.0`.
- **Signed-out reads redistribute the dropped feedback weight.** Explore without a session has no feedback and no persona. The three remaining differentiating terms scale by `1/0.80` to absorb feedback's 0.20.

## Feedback Decay

- **Feedback decays as `FEEDBACK_DECAY_BASE ** days_since_feedback`** (0.9 per day, `app/ranking/score.py`). Recent signals weigh more than old ones.
- **A dislike is a hard exclude, not a negative weight.** The Daily 5 builder skips a disliked event and every event in its dedup group (`SCORE_HARD_EXCLUDE`).

## Daily 5 Builder

- **The builder scores events starting in the next 14 days and writes `daily_feeds`.** MMR-lite diversity caps each category at `DAILY_5_MAX_PER_CATEGORY` (2).
- **Its candidate window uses the publish gate's `event_not_ended_filter()`.** An ongoing event stays a candidate until it ends.

### Series Collapse

- **`app/events/queries.py::collapse_series_duplicates()` keeps one row per `event_series_key` before scoring.** A multi-date listing ingests as several rows with distinct dedup groups. Without the collapse, two of its dates could land in one Daily 5.
- **The nearest `starts_at` survives, with ties broken by event id.** The survivor is deterministic across builds. The collapse runs once per build, before scoring, cooldown and MMR.
- **`_load_candidate_events()` loads only `_CANDIDATE_EVENT_COLUMNS`.** A new downstream read of any other `Event` column must join that tuple. Otherwise the deferred attribute raises `MissingGreenlet`.

### Series Cooldown

- **A series shown to a user in the last `DAILY5_SERIES_COOLDOWN_DAYS` (3) moves to a cooled pool.** The series key is normalized title plus lowercased venue. So a recurring series isn't re-picked nightly while the fresh pool is healthy.
- **The cooldown window is bulk-fetched**: one feed query and one event query, with no per-user N+1. Suppression is per build and never persisted.

### Backfill Tiers

`app/ranking/score.py::_select_with_backfill()` guarantees five events by relaxing constraints tier by tier:

| Tier | Pool | Per-category cap | Picker |
|---|---|---|---|
| 1 | fresh | `DAILY_5_MAX_PER_CATEGORY` (2) | `_mmr_pick` |
| 2 | fresh | `DAILY_5_BACKFILL_MAX_PER_CATEGORY` (3) | `_greedy_fill` |
| 3 | cooled | `DAILY_5_BACKFILL_MAX_PER_CATEGORY` (3) | `_greedy_fill` |
| 4 | fresh | none | `_greedy_fill` |
| 5 | cooled | none | `_greedy_fill` |

- **Relaxed tiers prefer diversity over freshness.** Each pool is sorted by score once and reused by every tier that reads it.
- **The category cap and series cooldown are soft under scarcity.** A cooled series can reappear the next day, and a thin pool can yield three or more events in one category.

## Publish Gate

`app/publish.py::publish_pending()` promotes a `classified` event to `published` when every criterion holds. A failing event stays `classified`, and the returned summary counts each failure. The counters overlap.

| Criterion | Reject counter |
|---|---|
| `quality_score >= PUBLISH_MIN_QUALITY_SCORE` (0.4) | `fail_quality` |
| `is_explicit` is false | `fail_explicit` |
| `is_non_event` is false | `fail_non_event` |
| `is_out_of_area` is false | `fail_out_of_area` |
| Not ended (`event_not_ended_filter()`) | `fail_ended` |
| `title_orig` is present | `fail_no_title` |
| Any present `lat`/`lng` lies in `TALLINN_REGION_BBOX` | `fail_coords_bbox` |

- **An event is live until `ends_at`, or `starts_at` when `ends_at` is unset.** A past start with a future end stays live, which covers multi-day runs and exhibitions.
- **The bbox check is defense in depth.** An event without coordinates passes; only an out-of-bbox coordinate blocks.
- **The gate also holds back events from an unverified organizer** (`submitted_by_organizer_id`, NULL-safe for other events). See [organizer-portal.md](organizer-portal.md) for the review flow.

## Geocoding Backfill

`app/ingestion/geocode/__init__.py::geocode_pending()` fills missing coordinates in six sub-passes, in this order:

1. **Self-heal** — `_self_heal_out_of_bbox_coords()` clears stored coordinates outside `TALLINN_REGION_BBOX`. It runs first so a bad coordinate can't spread through sibling copy or the Nominatim cache.
2. **Venues** — `geocode/venue_pass.py::geocode_pending_venues()` geocodes organizer-saved `Venue` rows that have an address but no coordinates.
3. **Venue sync** — `_sync_venue_linked_coords()` copies each venue's coordinates onto its events.
4. **Venue-name extract** — `geocode/venue_extract.py::extract_address_from_venue_name()` mines addresses out of `venue_name`.
5. **Sibling copy** — `geocode/sibling_copy.py::copy_venue_from_siblings()` copies an address from a geocoded sibling.
6. **Nominatim** — `geocode/nominatim.py` geocodes the remaining addresses.

- **Nominatim calls run at 1 per second** (`GEOCODE_REQUEST_DELAY_SECONDS`), up to `GEOCODE_MAX_PER_RUN` per run. A failed address waits `GEOCODE_RETRY_INTERVAL_DAYS`, tracked by `geocode_attempted_at`. The venue pass uses the same cooldown on the venue's own column.

### Venue-Linked Events

- **A venue-linked event stores `venue_name` and `venue_address` as NULL.** With `Event.venue_id` set, it never enters the address-driven sub-passes 4–6. The venue pass is its only coordinate path.
- **Organizer create and edit never geocode inline.** The venue pass picks the venue up on its next run.
- **The venue sync is one bulk `UPDATE ... FROM`.** It fills events submitted before their venue resolved. It also carries a later venue address correction onto already-published events.

### Venue-Name Extract

- **An LLM moves street addresses glued into `venue_name` into `venue_address`.** A prefilter (ASCII digit, comma, direction keyword, length), pushed into SQL with a collation-independent twin, sends only suspect names to the LLM.
- **Decisions are cached in `llm_calls` by content hash.** Fresh calls per run are capped at `VENUE_EXTRACT_MAX_FRESH_LLM_CALLS_PER_RUN`.
- **A "no address" answer stamps `venue_extract_attempted_at`.** The event is skipped for `VENUE_EXTRACT_RETRY_INTERVAL_DAYS`, so it can't starve newer candidates.

### Sibling Copy

- **Siblings match on the canonical venue name.** `canonical_venue_name` strips a `(parens)` suffix and any address tail after the first comma. So "Sõltumatu Tantsu Lava" matches a "Sõltumatu Tantsu Lava (STL)" donor.
- **Matching uses a symmetric `fuzz.ratio >= VENUE_SIBLING_RATIO_THRESHOLD` (90).** `token_set_ratio` would score a short comma-split core 100 against an unrelated longer donor.
- **The ambiguity guard counts distinct coordinates, not addresses.** One venue often has several address spellings at one coordinate. A name spanning more than one coordinate is skipped and logged. Otherwise the most common address is copied, ties broken lexically.
- **`NON_GEOCODABLE_VENUE_NAMES`, such as "online", are skipped** as both target and donor.

### Nominatim Pass

- **The pass seeds a normalized-query → coordinates cache from every geocoded event.** A spelling variant of a known address costs no HTTP call.

## Detail-Refetch Sync

- **`app/ingestion/refetch.py::refetch_event_details()` re-reads every future event's `event.url`.** It parses the JSON-LD `Event` block through `app/ingestion/jsonld.py`. Then it reconciles venue, coordinates and price fields against the source.
- **Reconciliation updates a differing value and fills an empty one.** It never replaces a good stored value with nothing.
- **The parsing is generic JSON-LD, not Fienta-specific.** It no-ops on pages without an `Event` block. HTML-listing sources already fetch detail at ingest, so Fienta benefits most.
- **Piletilevi prices come from the store API, not JSON-LD.** Its detail pages carry no `offers`. Ingest and refetch both call `piletilevi.py::fetch_store_prices()`. Refetch asks only for events with no stored price (`piletilevi_store_price_fields()`), so a pre-sale event is priced on the first refetch after its sale opens.
- **A store-API 400 for a pre-sale or sold-out event is a business state, not a failure.** It logs at INFO, and the adapter logs a per-run count. Any other 400 still logs a WARNING. The codes live in `app/ingestion/selectors.py`.
- **A coordinate cleared by an address change is repaired by the next geocoding pass.**
- **A changed `venue_name` re-runs the explicit and non-event checks.** A published event that newly fails is demoted.

### Localized Text Backfill

- **Missing locales of `title_localized`/`description_localized` are filled from the page's locale variants** (`_backfill_localized_text`). The check is per locale and merges into the stored dict, so a partly filled column self-heals.
- **A stored title that looks like site boilerplate counts as missing** (`_is_suspect_locale_title`).
- **A locale pinned by a claim is skipped** (`Event.pinned_fields`, `app/claims/pinning.py::pin_key()`). A Dormant claim's pins count as absent (`bulk_dormant_pinned_event_ids()`). Price fields are never pinned.

### Candidates and Throttling

- **`_select_candidates` excludes organizer submissions on two independent signals:** `submitted_by_organizer_id IS NULL`, and no link to a `user_submission` source. The second catches a future insert that forgets the first.
- **That exclusion is a security boundary.** An organizer's `url` isn't host-pinned, so it must never be fetched. See [security.md](security.md)'s External URLs section.
- **Candidates are grouped by host.** Each host is walked sequentially with `REFETCH_REQUEST_DELAY_SECONDS` between requests. Up to `REFETCH_HOST_CONCURRENCY` hosts run in parallel.
- **A run handles at most `REFETCH_MAX_PER_RUN` events.** An event is re-checked only after `REFETCH_MIN_INTERVAL_DAYS`.

### Source-Gone Retirement

- **A detail page answering 404 or 410 (`REFETCH_GONE_STATUS_CODES`) means the source removed the event.** It isn't counted in `failed`. The run stamps `events.source_gone_since` on the first sighting and marks the event synced, so it moves to the back of the queue.
- **Any other status, a `RequestError` or an SSRF-guard `ValueError` is transient.** It counts in `failed` and leaves the event untouched.
- **A later successful fetch clears `source_gone_since`.**
- **An event gone for `REFETCH_GONE_CANCEL_AFTER_DAYS` is cancelled** with `cancellation_reason = source_gone`, through `app/events/cancellation.py::cancel_event_and_resolve_reports()` like every other cancel path. The wait keeps one bad response from the source from cancelling a live event.
- **A dedup representative with a live sibling is spared** (`no_live_dedup_sibling_clause()`) and retried next run.
- **Cancellations run once after the host walk, in one batched sibling query.** The run commits, then sends the reporter emails, so no one is told about a cancel that rolled back. The summary counts `source_gone` and `cancelled_gone`.

## Read Paths

Four user-facing surfaces read `published` events, plus two auxiliary public reads. They share the `public_event_filter()` + `select_events_with_classification()` + `serialize_event()` stack. [security.md](security.md)'s Public Reads section explains why visibility filters live in the query.

### Daily 5 Feed

- **`GET /feed` serves the pre-built `daily_feeds` snapshot.** It requires a session. See Daily 5 Builder.

### Explore

- **`GET /explore` (`app/routers/browse.py`) is optional-auth** (`get_optional_user`). Signed-out callers get the signed-out weights; signed-in callers get personalization. It is rate-limited by `RATE_LIMIT_BROWSE`.
- **It has two execution paths.** `_browse_sql_path` serves the non-personalized `date`/`price`/`quality` sorts in SQL. `_browse_scored_path` reuses `ranking/score.py` for `for_you` or `relevance`, since persona affinity and the feedback soft-filter can't be a SQL `ORDER BY`.
- **`q` is capped at `BROWSE_QUERY_MAX_LEN`.** `_keyword_filter` matches `%...%` against two trigram GIN indexes, so an unbounded string is cheap to send and expensive to scan.
- **Both paths page on `limit`/`offset` and return an exact `total` on every request.** There is no cursor. Each SQL sort ends in an `id` tie-breaker, so tied rows keep one order across pages. The frontend shows a numbered pager at `BROWSE_PAGE_SIZE`.

### Pagination

- **Every paged list returns `total`, `limit` and `offset` on every request.** There are no cursors, and `total` is counted every time. The envelope rule for admin lists is in [backend-ops.md](backend-ops.md)'s Pagination section.
- **Explore's scored path ranks at most `BROWSE_RELEVANCE_CEILING` (2,000) events.** The candidate query fetches the ceiling plus one row, ordered `starts_at, id`. Below the ceiling every match is ranked; one extra row means only the soonest 2,000 are scored.
- **An overflow sets `total_is_lower_bound: true` on the response and logs `explore_ceiling_overflow`.** The flag is set even when the filters then leave fewer rows, and is absent otherwise. `total` is the reachable count, so it drives the last page; the pager reads "… of 2,000+" and announces "of more than 2,000".
- **The score cache keeps each ranked id list as an `array("q")`, 8 bytes per id, beside the flag.** Signed 64-bit matches the BigInteger `Event.id`. A full cache stays near 32 MB, and the entry cap and 30 s TTL are unchanged. An overflow logs once per scoring pass, not per cache hit.

### Saved Events

- **`GET /feedback/events` (`app/routers/feedback.py`) lists the user's events carrying one preference signal**, most recent first. It is rate-limited by `RATE_LIMIT_FEEDBACK`.
- **The signal must be in `PREFERENCE_SIGNALS`** (like, dislike, bookmark), not the full `VALID_SIGNALS`. Passive `view`/`click_external` rows repeat per event, up to one per UTC day.
- **It pages by offset and returns the exact `total` on every request.** It orders by `(feedback.created_at, feedback.id)` descending, so signals given in the same instant keep one order across pages.
- **The `/saved` route keeps the signal tab in `?signal` beside `?page`.** The default `bookmark` tab is omitted, and a tab switch starts again at page 1.

### Landing Showcase

- **`GET /public/showcase` (`app/routers/public.py`) is the only user-facing list with no auth-dependent behaviour.** Explore is reachable signed out but branches on the user; the showcase never does. Never add a user-scoped field to its response.
- **It shows `SHOWCASE_EVENT_COUNT` (6) top-quality events this week** (`SHOWCASE_WINDOW_DAYS`). A thin week widens to `SHOWCASE_FALLBACK_WINDOW_DAYS`. It is rate-limited by `RATE_LIMIT_PUBLIC` and cached in-process per locale.
- **The SQL mirrors `_browse_sql_path`'s quality sort without any personalization.** The query is unlimited, because a LIMIT before the series collapse could drop a series' only surviving row.
- **After `collapse_series_duplicates()`, Python re-sorts and slices.** The keys match the SQL `ORDER BY`: narrow window first, `quality_score` descending with nulls last, then `starts_at`. The collapse survivor isn't always the row SQL ranked first.

### Landing Counts

- **`GET /public/counts` returns the live numbers behind Landing's hero, ticker and stat row.** It is cached in-process per locale for `PUBLIC_COUNTS_CACHE_TTL_SECONDS`.
- **`today_count` drives the top bar's pulse chip.** It counts exactly what `/explore?date=today` lists, so the chip agrees with the page its link opens. An ongoing exhibition counts.
- **That count combines four filters:** `public_event_filter()`, `canonical_event_filter()`, `event_not_ended_filter(now)` and `event_date_range_filter(today, today)`. The last lives in `app/events/queries.py`, shared with `browse.py`.
- **`today_count` is its own scalar query (`_today_count_stmt`).** A `FILTER` on `_aggregates_stmt` would inherit its `starts_at >= now` clause and drop ongoing runs.
- **The hero and ticker still read `tonight_events` and `tonight_is_fallback`.** The chip doesn't.

### Prerender Id Snapshot

- **`GET /public/prerender-events` returns `{id, updated_at}` for every published, canonical, not-ended event.** It is unauthenticated and rate-limited by `RATE_LIMIT_PUBLIC`. The prerender and the sitemap both read it; see [seo.md](seo.md)'s Targets section.
- **It is unpaginated on purpose.** The build needs one atomic snapshot of the id set, which paging would break.

## Organizer Lifecycle (Fienta)

A Fienta organizer here is a ticketing-source id that gets polled. It is not an `Organizer` account; see [organizer-portal.md](organizer-portal.md).

- **`FIENTA_ORGANIZER_IDS`/`FIENTA_ORGANIZER_NAMES` (`app/config.py`) are only a bootstrap seed.** `app/seeds.py::_upsert_fienta` copies them into `sources.config` on a fresh database.
- **At runtime `sources.config["organizer_ids"]` is the source of truth.** `FientaAdapter.fetch_raw()` reads only from there.

`app/ingestion/organizer_sync.py::sync_fienta_organizers()` runs weekly and walks each organizer through these steps:

1. **Detect** — an organizer returning 0 events is marked stale, with a first-seen time in `sources.config["stale_since"]`. A transient HTTP error neither flags nor clears staleness, so a network blip can't flip it.
2. **Skip at ingest** — `fetch_raw()` drops ids in `stale_organizer_ids` from the hourly poll. The weekly sync still re-probes them, so a revival is noticed.
3. **Revive** — an organizer returning events again has its `stale_since` entry cleared.
4. **Retire** — after `STALE_ORGANIZER_RETIRE_DAYS` (30) stale, the id moves to `retired_organizer_ids`. `_upsert_fienta` subtracts retired ids on every startup, so a retired seed id never comes back.
5. **Discover** — a city-filtered scan (`FIENTA_CITY_FILTER`) adds any unknown organizer with at least `ORGANIZER_MIN_EVENTS_FOR_AUTO_ADD` (3) Tallinn events. A retired organizer can rejoin this way.

- **The sync holds no DB connection during its ~2 min HTTP phase.** It rolls back after reading the config, then re-reads the source before writing. A server-side drop during the HTTP phase once killed a whole weekly run, since Neon keeps an idle-in-transaction connection alive but can still restart the compute.
- **The write phase retries once on a lost connection** (`ORGANIZER_SYNC_DB_WRITE_ATTEMPTS`). Config keys the sync doesn't own survive a concurrent admin edit.
- **`POST /admin/sync-organizers` runs the sync synchronously.** It is also stage 1 of `POST /admin/pipeline/run`.

### Publisher Mirroring

- **Every sync mirrors one `publishers` row per organizer id, active or retired** (`_sync_publishers()`). The mirror only reads `organizer_ids`/`retired_organizer_ids`, never writes them.
- **Ingest stamps each Fienta listing with its Publisher.** `FientaAdapter.fetch_organizer()` tags each item with its `organizer_id`, and `normalize()` carries it as `NormalizedEvent.publisher_external_id`.
- **`insert_normalized_event()` resolves that to `EventSource.publisher_id` from a per-run bulk lookup** (`adapter.py::load_publisher_lookup()`), never a per-row SELECT.
- **KUMU and Estonia Concert Hall each have one constant `publishers` row** with a NULL `external_id`, seeded by `seeds.py::seed_publishers()`. They match the same way, since their `publisher_external_id` is always `None`.
- **Piletilevi never stamps `publisher_id` at ingest.** Its Publisher resolves at claim time from the event page's promoter, through `app/claims/target_resolution.py::resolve_claim_target_live()`. See [organizer-portal.md](organizer-portal.md).

### Publisher Backfill

- **`app/ingestion/publisher_backfill.py::backfill_publisher_ids()` stamps missing `publisher_id`s on claimable listings.** That means published, not-ended Fienta, KUMU and Estonia Concert Hall `event_sources` rows. Piletilevi is out of scope.
- **Each call handles one bounded batch** and is a no-op once nothing is unstamped. [backend-ops.md](backend-ops.md) covers its schedule and CLI.
- **Fienta resolves in two steps.** One bulk SQL read takes each listing's freshest `raw_events.payload->>'organizer_id'` (`_raw_organizer_by_external_id`). A live organizer re-query then runs only for rows still unresolved.
- **The request path never crawls Fienta live.** An unstamped listing with no raw stamp is not claimable until the next backfill run.
- **An unresolved row waits `PUBLISHER_RESOLVE_RETRY_COOLDOWN` (7 days)**, tracked by `publisher_resolve_attempted_at`. The crawl is skipped when every unresolved row is cooling down. A failed organizer fetch stamps nothing.

## LLM Usage Constraints

`app/constants/llm.py::LLM_PROVIDERS` defines the fallback chain:

| Order | Provider | Model | Budget |
|---|---|---|---|
| 1 | Groq | `openai/gpt-oss-120b` | 30 requests/min burst |
| 2 | Cloudflare Workers AI | `@cf/openai/gpt-oss-120b` | 10,000 free Neurons/day |
| 3 | Mistral | `mistral-small-latest` | 1B tokens/month, overnight batch |

- **Calls are capped at `LLM_MAX_TOKENS` (400)** to avoid quota exhaustion.
- **The two `gpt-oss-120b` entries use `reasoning_effort=low` and `LLM_REASONING_MAX_TOKENS` (600).** That is the project hard cap. It keeps reasoning tokens from crowding out the JSON answer.
- **Dedup decisions are cached by content hash.** An identical pair never reaches the LLM twice.
- **The classification batch needs no sleep loop.** Groq's burst limit absorbs it.

### Backlog Drain

- **`dedup_pass` and `classify_pending` drain their backlog** through `app/ingestion/jobs.py::_drain_backlog()`. Each re-runs while work remains, every `LLM_BACKLOG_RETRY_SECONDS` (15 min), up to `LLM_BACKLOG_MAX_DRAIN_PASSES` (12). The rest waits for the next cycle.
- **Admin triggers drain synchronously with no sleep between passes** (`dedup_pass_drain_now()`, `classify_pending_drain_now()`). The caller is blocking on the HTTP response.

## Content Safety (NSFW / Explicit Content Filter)

Three layers, each cheaper than the next:

1. **Ingest-time keyword prefilter** — `app/ingestion/content_filters.py::is_explicit_text()` matches `EXPLICIT_KEYWORDS` (en/et/ru) by word-boundary regex and sets `Event.is_explicit`. It takes title, description, venue name and important info. A flagged event skips the LLM call; see Classification.
2. **LLM classification flag** — `app/llm/classifier.py` asks the model for `is_explicit` on events that pass layer 1, catching what the keyword list misses.
3. **Publish gate** — blocks the event as `fail_explicit`.

- **Localized values are scanned too.** See [security.md](security.md)'s Untrusted Values section.

## Non-Event Filter (gift cards / merch / webinars)

The same three layers catch listings that aren't attendable events. That covers gift cards and vouchers, merchandise, donations, and online-only webinars, courses and recordings. The audience wants in-person Tallinn events.

1. **Ingest-time keyword prefilter** — `content_filters.py::is_non_event_text()` matches `NON_EVENT_TITLE_KEYWORDS` against the title and `NON_EVENT_VENUE_KEYWORDS` against `venue_name`. It sets `Event.is_non_event`, and a flagged event skips the LLM call.
2. **LLM classification flag** — the model's `non_event` boolean is OR-merged into `Event.is_non_event`, never clearing a layer-1 flag.
3. **Publish gate** — blocks the event as `fail_non_event`.

- **Title keywords never match the description.** Descriptions mention "gift cards available" as a payment option.
- **In-person workshops and trainings with a set time are events.** The prompt says so explicitly.
- **Read paths filter `is_non_event` again as defense in depth.** That covers the Daily 5 candidate query, feed hydration (`routers/feed.py`), event detail (`routers/events.py`) and the digest query (`email/digest.py`).

## Pipeline Code Rules

- **New HTML-scraped sources subclass `HtmlListingAdapter`** (`app/ingestion/sources/html_base.py`). It owns pagination, parsing, dedup and detail fetches, so an adapter supplies only its selectors and field mapping.
- **Locale discovery lives in `app/ingestion/locale_urls.py`.** Per-locale page discovery and `fetch_locale_variants` are shared by `html_base.py`, `fienta.py` and `refetch.py`. Reuse them instead of writing hreflang logic in an adapter.
- **`app/ingestion/html_utils.py` holds the low-level BeautifulSoup helpers** such as `attr_str`. They sit apart from `html_base.py` to avoid a circular import with `locale_urls.py`.
- **`fetch_raw()` lets HTTP failures propagate to `SourceAdapter.run()`.** That is how `IngestionRun.error` and `source.last_status` get set. A swallowed exception makes a failed scrape look like a clean, empty run.
- **Filter LLM classification output against `VALID_CATEGORIES`/`VALID_VIBES` before persisting.** Unknown values are dropped silently (`app/llm/classifier.py::_parse_classification()`).
- **Dedup's time-window check stays in SQL; the fuzzy check stays in Python.** `app/dedup/rules.py::candidate_pair_ids_in_window()` pre-filters pairs with a sargable `BETWEEN` self-join. `run_dedup_pass` and `run_dedup_pass_llm` both consume it, and `is_candidate_pair` runs only on the pairs it returns.
