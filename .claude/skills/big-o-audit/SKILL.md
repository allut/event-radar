---
name: big-o-audit
description: Audit code for algorithmic-complexity costs (N+1 queries, nested scans, unbounded loads), scoped to changes since the last audit.
disable-model-invocation: true
---

The deliverable is a **report** in chat: findings ranked by severity, each with a fix. Code changes wait for the user to pick findings from it.

## Steps

1. **Read the ledger, `docs/big-o-audit.md`.** Done when you hold its baseline commit, its accepted cases and its open findings.

2. **Fix the scope.** By default it is every non-test source file in `git diff --name-only <baseline>..HEAD`, plus the callers of the functions those files change. A full sweep happens only when the user asks for one. Done when you hold the file list and its line count.

3. **Split the scope into at most three slices by area,** and skip an empty slice:
   - backend request path: `app/routers/`, `auth/`, `email/`, `models/`, `events/`, the top-level `app/*.py`, `backend/scripts/`
   - backend pipeline: `ingestion/`, `dedup/`, `llm/`, `ranking/`, `claims/`, `promotions/`, `integrations/`, `constants/`
   - frontend and tooling: `frontend/src/`, `frontend/scripts/`, `frontend/functions/`, root `scripts/`

   A scope under about 3k lines needs no agents; audit it yourself.

4. **Give each slice to a read-only agent.** The prompt carries the checklist below, the ledger's Guards and Accepted sections, and the realistic sizes: events 10k–100k, users in the thousands, Daily 5 candidates 500–2k. Each agent reads every file in its slice in full and returns two things:
   - per finding: location, the complexity with what n stands for, request path or scheduled job, severity, and a fix naming an existing helper
   - a per-file coverage list

   Done when every file in scope appears in a coverage list.

5. **Verify every Medium-or-higher finding against the code yourself** before it reaches the report. Drop what the ledger already accepts or a guard already enforces.

6. **Report** in tiers. Tier 1 is correctness or a blocked event loop, then Medium, then Low. Close with the coverage count.

7. **Rewrite the ledger:**
   - Set the baseline to the audited `HEAD`.
   - Remove findings that are gone, and add the new ones.
   - Move anything the user accepts to Accepted by Design, with its reason.

   Then run `bash backend/scripts/scratch-test.sh --no-db tests/test_docs_style.py`. Done when the guard passes.

## Checklist

- **Per-row query:** an `await` on the session inside a loop, or a helper per row that queries. Read the helper; the loop hides it.
- **Shared session under `gather`:** concurrent coroutines querying one `AsyncSession`, or lazily loading a relationship in async code.
- **Nested scan:** `in`, `.find`, `.includes` or `.index` over a list inside a loop, where a dict or set would do.
- **Unbounded load:** whole tables or windows pulled into Python, then filtered, sorted or sliced there.
- **Index gap:** a hot `WHERE` or `ORDER BY` that no index in `backend/app/models/models.py` serves, `NULLS` ordering included.
- **Repeated work:** parsing, normalising or constructing the same thing per item or per render, a full sort where top-k would do, or spread-accumulate in a loop.
- **Waterfall:** serial awaits of independent I/O, or one request per list item.
- **Unbounded cache:** module-level state that only grows.
