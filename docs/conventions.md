# Code Quality Rationale

What's in here: the reasons behind CLAUDE.md's inline Code Quality Rules, the HTTP retry bypasses, the `fetch`-stub exceptions in frontend tests, and spec-work conventions.

CLAUDE.md states each rule. This doc says why it holds and where its edges are. Area mechanics live in the area doc that owns the code.

## Where Things Live

### Constants

- **One constants package per stack keeps every tunable in one place.** A literal inlined near business logic drifts from its twin elsewhere, and nobody finds it when the value changes.
- **The backend package has one file per domain, named after its docs-map area,** such as `app/constants/auth.py` or `app/constants/ingestion.py`. A group tuned or audited as a set gets its own file: `rate_limits.py`, `jobs.py` and `log_events.py`.
- **`app/constants/__init__.py` stays empty, so every import names the defining file.** A re-export facade adds a hop to go-to-definition and lets constants pile back into one place. Generated cross-stack values are imported from `app._generated.shared_constants` directly.
- **The frontend mirrors it in `frontend/src/constants/<domain>.ts`, with no `index.ts` barrel.** Each file imports with `.js` extensions because Pages Functions load it as unbundled ESM. Generated values come from `frontend/src/_generated/sharedConstants.ts` directly.
- **LLM prompts sit apart in `app/llm/prompts.py`** so prompt-engineering diffs stay clean. Scrape selectors sit apart in `app/ingestion/selectors.py` for the same reason.
- **A comment names a schedule constant and never restates its value or a UTC offset.** `CLEANUP_HOUR` stays true when the hour moves, but "Sun 03:30 EET" goes stale, and "EET" is the winter offset only. The `docs/backend-ops.md` cadence table is the one written copy, and `tests/test_scheduler.py` checks it against the registered triggers.
- **Cross-stack values live once in `shared/` and are generated into both stacks.** The backend imports `app._generated.shared_constants` and the frontend `frontend/src/_generated/sharedConstants.ts`, so the two can't disagree. `backend/tests/test_generated_sync.py` fails when the generated files drift.

### Helpers

- **Routers depend on domain packages, never the reverse.** A domain module that imports `app/routers/utils.py` pulls the HTTP layer into jobs and other domains, and invites import cycles.
- **One invariant stays in one file.** For example, `app/auth/admin_lockout.py` owns both the lockout counter and its eviction policy, and `admin_auth.py` imports from it. See [security.md](security.md)'s Admin Console Auth section.
- **Cross-router auth dependencies live in `app/auth/dependencies.py`** so no router imports another router's module. Router modules stay leaves of the import graph.
- **Every frontend request goes through `frontend/src/api/client.ts`.** It owns the per-track 401 handling, so a raw `fetch` misses the session-expiry redirect. See [frontend.md](frontend.md)'s API Client section.

### File Length

- **A source file over 700 lines splits by area, and line count only nominates it.** Cohesion decides: a long file with one job, such as a state machine or one auth track, reads better whole than cut along a seam that doesn't exist. Such a file joins the *stay whole* allowlist in `backend/tests/test_file_length.py` with a one-line reason.
- **A file waiting for its split sits on the *pending split* allowlist with its issue.** The test fails on an entry whose file is missing or at or under 700 lines, so each split removes its own entry.
- **The guard fails rather than warns.** Every guard here fails, and nobody reads a warning. The pre-commit hook runs it when `backend/app/` or `frontend/src/` is staged, and CI's backend suite picks it up.
- **Allowlisted files have no per-file ceiling.** A cap would be a second number to tune, and an allowlisted file already carries a recorded reason to stay long.
- **The scan covers the backend app's Python and the frontend source's TypeScript.** `_generated/`, test files and CSS are never counted.

### Outbound Adapters

- **Each external service the Promotions code calls sits behind a `Protocol` in `app/integrations/`.** `registry.py` is the Äriregister lookup and `payments.py` is Stripe. Domain code takes the adapter as an argument, and routers get it through `app/integrations/providers.py`.
- **Tests swap in `backend/tests/promotions/fakes.py`, never patch an SDK or `httpx`.** The fakes script found, deleted, not-found and outage for the register, and record every Stripe call. The Äriregister call itself goes through `http_get()`.

### Underscore Names

- **A leading underscore means module-private, so an imported `_name` is a dishonest API.** Drop the underscore once a second module needs the name.
- **The rule covers our own modules only.** A third-party library's documented export that starts with an underscore isn't ours to rename, such as `slowapi`'s `_rate_limit_exceeded_handler` in `app/rate_limit.py`.
- **Tests may import private names.** White-box testing is an accepted pattern here.

## CSS

- **Tokens make theming a token swap.** The light theme redefines `:root` tokens under `:root[data-theme="light"]`, so a hardcoded value in a module stays dark. See [design-system.md](design-system.md) §3.
- **Add a modifier class instead of restyling a shared base class.** Every consumer composes the base, so an in-place change for one page restyles all of them. See [design-system.md](design-system.md) §7 for the composing rules.

## Backend Behaviour

### Batch Jobs

- **A query inside a per-row loop makes a job's cost grow with its row count.** The scheduled jobs touch every user or every pending event, so an N+1 loop turns a seconds-long job into minutes.
- **Copy the existing shape when extending a job.** `app/ranking/daily_feed.py::build_daily_feeds()` and `app/llm/classifier.py::classify_pending()` fetch everything up front with `WHERE col IN (...)` and group in Python before the inner loop.
- **A fixed query count is proven against real Postgres.** Run the job at two sizes inside `count_statements(db)` and compare the lengths. The helper and the rolled-back `db` fixture live in `backend/tests/conftest.py`.

### External Fan-Out

- **A serial await is too slow, and an unbounded gather trips the provider's rate limit.** A semaphore-bounded `asyncio.gather` sits between the two.
- **Pick the cap from the provider's documented rate limit, with headroom for retries.** `app/constants/email.py::DIGEST_SEND_CONCURRENCY` is the model.
- **`return_exceptions=True` keeps one failed call from discarding the other results.** Each result is then checked on its own.
- **The Nominatim geocoding passes serial-await on purpose.** Nominatim's usage policy allows one request per second, which a concurrency cap can't express. See [pipeline.md](pipeline.md)'s Geocoding Backfill section.
- **The Fienta organizer probe in `app/ingestion/organizer_sync.py::_check_existing_organizers()` is serial on purpose too.** It waits on an `AsyncRateLimiter` between calls to respect Fienta's rate limit, so a gather would only queue behind the limiter.

### HTTP Retry

- **`app/ingestion/http_client.py::http_get()`/`http_post()` wrap `httpx` with tenacity exponential backoff plus jitter.** The `HTTP_RETRY_*` constants set the attempts and waits.
- **A 429's `Retry-After` is honoured instead of the backoff curve,** capped at `HTTP_RETRY_AFTER_MAX_SECONDS`. A source that rate-limits us is telling us exactly when to come back.
- **Only transient failures retry:** `HTTP_RETRYABLE_STATUS_CODES` and `httpx.RequestError`. Any other 4xx is our bug, and retrying it only adds load.

### HTTP Retry Bypasses

These groups skip `http_get()`/`http_post()`. Add another only with a reason recorded here.

- **Request-path Resend sends use `app/email/resend.py::send_resend_email()`, a single attempt.** A five-attempt backoff would stall the user's response for up to about 150 seconds. This covers the magic link, contact form, report notify, reporter outcome and claim resolution sends.
- **Fan-out Resend callers share one client instead of retrying per send.** The report-outcome, claim-expiry and Promotion sweeps and the restriction notices pass `resend_http_client()` into each `send_resend_email()` call.
- **`app/llm/router.py` calls each `LLM_PROVIDERS` entry directly.** The Groq → Cloudflare Workers AI → Mistral fallback chain is the retry strategy. A tenacity backoff underneath would fight its fast-fail-and-advance behaviour.
- **`app/logging_config.py` ships logs with a sync `httpx.Client`.** It runs on the `QueueListener` background thread, which can't await the async `http_post()`.
- **`app/integrations/payments.py` calls Stripe through the official `stripe` SDK.** The SDK signs requests, sets idempotency keys and verifies webhook signatures, and rebuilding that on `http_post()` would be riskier than the bypass. It is the only module that imports `stripe`.
- **`app/auth/google_oauth.py`'s `PyJWKClient` fetches Google's JWKS itself, with its own caching.** Routing it through `http_get()` would mean hand-rolling that cache. ADR 0002 records the same trade-off.

These are not bypasses, and they show where the line falls:

- **`app/email/digest.py` sends inside a scheduled batch job, not a request path,** so it routes through `http_post()`.
- **`google_oauth.py::exchange_code_for_id_token()` also routes through `http_post()`.** Only the JWKS fetch bypasses it.

### Numeric Fields

- **`0` is falsy, so a truthiness gate drops free events.** `price_raw.get("min") or fallback` and `raw.get("price") or {}` both lose a legitimate zero price. Use `is not None`, and `isinstance(x, dict)` for nested objects.
- **Currency goes through `app/ingestion/pricing.py::normalize_currency()`.** It falls back to `DEFAULT_CURRENCY` only when `has_price` is true, and drops a malformed code instead of guessing EUR.

## Style and Checks

### Quotes

- **The linters enforce quote style, so a fix-on-save settles it.** Ruff's `Q` rules in `backend/ruff.toml` require double quotes. ESLint's `quotes` and `jsx-quotes` rules in `frontend/eslint.config.js` require single quotes in TS and double in JSX.
- **A string that contains the preferred quote may use the other one.** ESLint's `avoidEscape` allows it, and template literals are always fine.

### Ruff

- **`E501` is ignored.** Long lines are allowed where wrapping would hurt readability.
- **`app/_generated` is excluded.** The generator owns those files, so they aren't hand-formatted.
- **Ruff enforces the annotation and datetime rules.** `UP006`/`UP007`/`UP035`/`UP045` require PEP 604/585 syntax, `ANN201` a public return type, and the `DTZ` rules an aware datetime. Tests are exempt from `ANN201`, since a test function returns `None`.
- **A parsed naive datetime chains `.replace(tzinfo=TALLINN_TZ)` onto the `strptime()` call.** `DTZ007` accepts the chained form but not a naive intermediate variable.

### Mypy

- **There is no mypy config file; the defaults are enough.**
- **Give a reused loop or result variable of an incompatible type its own name.** Mypy infers a variable's type from its first assignment, so reusing it for a different ORM model fails even when each block is correct.
- **A third-party import without stubs gets a targeted `# type: ignore[import-untyped]` on that line,** such as `apscheduler`. A blanket per-module ignore would hide real errors.

### Annotations

- **PEP 604/585 syntax (`X | None`, `list[T]`) is the modern form.** Import from `typing` only what still lives there, such as `Any`, `TypeVar` or `Protocol`.
- **Public functions annotate their return type, FastAPI handlers included.** The return type is the contract a caller reads.
- **Default-exported React components are exempt.** `tsc` infers the JSX return type exactly, so annotating each one is churn with no type-safety gain. Other public TS functions still annotate.

### Backend Test Fixtures

- **Shared fixtures keep DB scaffolding in one place.** Inlined `AsyncMock()` sessions and hand-built users or events drift apart as the models change. Check `backend/tests/conftest.py` and the package conftests before writing one.
- **A fixture used by two or more test files goes in the narrowest conftest that covers them.**

### Frontend Test Fixtures

- **Use `frontend/src/test/utils.tsx` for render and query wrappers.** Inlined `QueryClient` or router scaffolding drifts from the providers the app really uses.
- **Mock the `api` module, not `fetch`.** A module mock keeps a component test about the component, not the request plumbing underneath it.

### Fetch-Stub Exceptions

A test may stub global `fetch` only when its subject calls `fetch` itself. Add another site only with that reason.

- **`frontend/src/routes/Feed/Feed.logoutRedirect.test.tsx`** tests `api/client.ts`'s own 401 redirect surviving a logout race. Mocking `api` would remove the code path under test.
- **`api/client.test.ts`, `lib/githubRequest.test.ts`, `lib/seoAuditIssue.test.ts` and `scripts/prerender.test.ts`** each test code that calls `fetch` directly.
- **The Pages Functions tests under `frontend/tests/functions/`** test handlers that call `fetch` directly. See [frontend.md](frontend.md)'s Tests section for why they live outside `functions/`.

## Spec Work

- **Bug fixes and new behaviour need a test that failed before the change.** Three agents wrote code first on the Promotions spec, and review then found real defects in lock order and the withdraw refund.
- **Spec work lands on an integration branch, then flattens to linear commits on `master`.** Run `python scripts/linearize-branch.py <branch> --base master` for the plan, add `--apply` for the new tip, then `git merge --ff-only <tip>`.
- **One agent owns each migration number.** The orchestrator rechains `down_revision` at merge, and `backend/tests/test_migration_chain.py` catches a collision or a stale "Revises" line.

