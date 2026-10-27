# Big-O Audit Ledger

What's in here: the commit the last complexity audit covered, the costs accepted by design, the open findings, and the guards that already enforce the mechanical patterns.

## Baseline

- **The last audit covered every source file at commit `b212d367`.** The next one audits `git diff b212d367..HEAD` plus the callers of changed code, unless a full sweep is asked for.
- **The `big-o-audit` skill runs the audit and rewrites this file at the end.** It moves the baseline, drops fixed findings and adds new ones.

## Guards

These patterns fail a check, so an audit skips hunting them where the guard reaches.

- **`backend/tests/test_code_rules.py::test_routers_query_outside_loops` fails a router awaiting a `db` query, or a helper taking `db`, inside a loop.** Code outside `app/routers/` still needs reading.
- **`backend/tests/test_code_rules.py::test_llm_calls_pass_a_prefetched_cache` fails an `llm_json` call without `prefetched_cache=`.** A fan-out builds the map with `backend/app/llm/router.py::prefetch_llm_cache()`.
- **ESLint fails a `new Intl.*` inside a function outside `frontend/src/utils.ts`.** Use module scope or `cachedDateTimeFormat()` from there.

## Accepted by Design

An audit leaves these out of its report.

- **`backend/app/routers/browse.py::_browse_sql_path` runs an exact `COUNT(*)` per Explore page.** The total-results line needs it (#551). Revisit past about 50k upcoming events.
- **`backend/app/routers/public.py::_showcase_stmt` has no SQL `LIMIT`.** Series collapse runs after the load, so a limit could drop a series' only surviving instance.
- **`backend/app/promotions/withdraw.py::withdraw_all` ends each Promotion in its own transaction.** One refused refund must not roll back the rest.
- **`backend/app/dedup/rules.py::candidate_pair_ids_in_window`'s pair `LIMIT` caps rows returned, not Postgres work.** The time-window self-join stays cheap at current event counts.
- **`backend/app/routers/public.py::prerender_events` is unpaginated.** The prerender build needs every event, and the response is cached.
- **Serial, rate-limited crawls are deliberate.** See [conventions.md](conventions.md)'s External Fan-Out section.

## Open Findings

### Medium

- **`backend/app/ranking/score.py::build_daily_feeds` scores users × events × personas with no `await`.** Each page freezes the single process for seconds. Precompute per-event sets in `_precompute_event_factors`, score identical persona-only users once, and yield every few users.
- **`backend/app/routers/public.py::_load_showcase` hydrates the whole 60-day window to keep six events.** Concurrent cold-cache requests all run it. Select slim columns, collapse, hydrate the winners, and share one load per miss as `_score_cache_lock` in `backend/app/routers/browse.py` does.
- **`backend/app/publish.py::publish_pending` scans every classified event ever.** `_stamp_missing_fienta_publishers` scans every unstamped Fienta source row. Add partial indexes on both, and scope the call in `backend/app/routers/admin.py::admin_approve_submission` by `event_ids`.
- **`backend/app/promotions/request_queue.py::list_requests` calls `validate_grant` per row,** about two queries each. Load overlaps with one `IN` query and run one `cap_days` across the page's span, then check each row with `window_violations`.
- **`backend/app/claims/pinning.py::bulk_resolve_series_events` hydrates every future event of a series to keep one.** Use `DISTINCT ON (series_key)`, as `backend/app/claims/target_resolution.py::bulk_resolve_publisher_events` does.

### Low

- **`ix_event_classifications_quality_score` is ascending,** so `DESC NULLS LAST` sorts in memory. Recreate it as `quality_score DESC NULLS LAST`.
- **`backend/app/ingestion/geocode/__init__.py::geocode_pending` retries ended events forever.** Add `event_not_ended_filter`.
- **`backend/app/email/consent.py::reset_consent_for_wording_change` binds every consenter id.** Past asyncpg's 32,767-parameter limit it fails at boot. Use `UPDATE … RETURNING` feeding `INSERT … SELECT`.
- **`backend/app/promotions/owners.py::resolve_owner_ids` matches claims by nested scan.** Invert to events-by-publisher once.
- **`backend/app/promotions/cap.py::cap_days` walks every day per Promotion.** A difference array makes it linear.
- **`backend/app/promotions/organizer_view.py::promotions_list` filters request status in Python.** Move the filter into the query.
- **`backend/app/ingestion/http_client.py::host_is_allowed` feeds a DNS verdict cache with no bound.** Cap and evict as `backend/app/integrations/registry.py::CachedRegistryLookup` does.
- **`backend/app/dedup/rules.py::is_candidate_pair` lowercases both titles per pair.** Precompute one lowered map per pass.
- **`backend/app/ingestion/jobs.py::dedup_pass_drain_now` reloads the window up to twelve times.** Stop once a pass defers nothing.
- **HTML is parsed more than once per item.** `backend/app/ingestion/content_filters.py::content_flags` parses plain text, `backend/app/ingestion/sources/fienta.py::_fetch_detail` re-sanitizes, and `backend/app/claims/target_resolution.py::_resolve_piletilevi_target` parses its page twice.
- **`backend/app/routers/feed.py::get_feed` reloads signals for the sponsored event.** Fold it into the first batch.
- **`backend/app/ingestion/jobs.py::ingest_all_enabled` runs sources one after another.** Gather them behind a small semaphore.
- **`backend/app/ingestion/publisher_backfill.py::_raw_organizer_by_external_id` binds an unchunked `IN` list.** Chunk at `SQL_IN_CHUNK_SIZE`.
- **`frontend/src/routes/OrganizerPromotionRequest/OrganizerPromotionRequest.tsx` rebuilds its unavailable-days `Set` on every keystroke.** Memoize it.
- **`frontend/src/components/DatePicker/DatePicker.tsx` walks up to a year of days on every render.** Move the walk into a lazy `useState` initializer.
- **`frontend/src/components/PromotionTrust/PromotionWithdraw.tsx` merges and sorts up to 1,000 rows per render.** Memoize it.
- **`frontend/scripts/prerender.ts::createLimiter` queues with `Array.shift()`.** Use a head index, as `RateGate` does.
