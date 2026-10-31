# Big-O Audit Ledger

What's in here: the commit the last complexity audit covered, the costs accepted by design, the open findings, and the guards that already enforce the mechanical patterns.

## Baseline

- **The last audit covered every source file at commit `b212d367`.** The next one audits `git diff b212d367..HEAD` plus the callers of changed code, unless a full sweep is asked for.
- **The `big-o-audit` skill runs the audit and rewrites this file at the end.** It moves the baseline, drops fixed findings and adds new ones.

## Guards

These patterns fail a check, so an audit skips hunting them where the guard reaches.

- **`backend/tests/test_code_rules.py::test_routers_query_outside_loops` fails a router awaiting a `db` query, or a helper taking `db`, inside a loop.** Code outside `app/routers/` still needs reading.
- **`backend/tests/test_code_rules.py::test_llm_calls_pass_a_prefetched_cache` fails an `llm_json` call without `prefetched_cache=`.** A fan-out builds the map with `backend/app/llm/router.py::prefetch_llm_cache()`.
- **ESLint fails a `new Intl.*` inside a function outside `frontend/src/utils/intlFormat.ts`.** Use module scope or `cachedDateTimeFormat()` from there.
- **`backend/tests/test_bigo_indexes.py` fails when the planner stops using migration 0070's indexes** for the publish gate, the Fienta stamp or the quality sort.

## Accepted by Design

An audit leaves these out of its report.

- **`backend/app/routers/browse.py::_browse_sql_path` runs an exact `COUNT(*)` per Explore page.** The total-results line needs it (#551). Revisit past about 50k upcoming events.
- **`backend/app/routers/public.py::_showcase_stmt` has no SQL `LIMIT`.** Series collapse runs after the load, so a limit could drop a series' only surviving instance.
- **`backend/app/promotions/withdraw.py::withdraw_all` ends each Promotion in its own transaction.** One refused refund must not roll back the rest.
- **`backend/app/dedup/passes.py::candidate_pair_ids_in_window`'s pair `LIMIT` caps rows returned, not Postgres work.** The time-window self-join stays cheap at current event counts.
- **`backend/app/routers/public.py::prerender_events` is unpaginated.** The prerender build needs every event, and the response is cached.
- **Serial, rate-limited crawls are deliberate.** See [conventions.md](conventions.md)'s External Fan-Out section.
- **`backend/app/ingestion/adapter.py::insert_normalized_event` takes one savepoint per new event.** The savepoint keeps one bad row from rolling back the batch, and the scrape, not the insert, sets the pace.
- **`backend/app/routers/browse.py::explore_events` loads the Explore slot's signals in their own two queries.** It is a constant cost on page 1 only. Folding them in would thread the signal maps out of both serving paths.
- **Some HTML is parsed twice per item:** Fienta's detail description, Piletilevi's detail page, and the claim path's event page in `backend/app/claims/piletilevi_promoter.py::resolve_promoter_contact`. Each is a constant cost per item or per claim on a network-bound path.

## Open Findings

None. The fix pass after the `b212d367` audit closed every finding except the ones accepted above.
