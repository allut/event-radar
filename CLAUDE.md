# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Event Radar** is an AI-powered event discovery platform for Tallinn, Estonia. It ingests events from multiple sources, deduplicates and classifies them via LLM, then delivers a personalized "Daily 5" curated feed per user. Days 1–20 complete. Day 21 = soft launch (pending E2E QA).

The authoritative spec is `plan.md`.

## Commands

```bash
# Backend (Python 3.12, FastAPI)
cd backend
python -m venv venv          # create virtualenv (venv is gitignored)
# Activate it — pick the line for your shell:
venv\Scripts\Activate.ps1    # Windows PowerShell
venv\Scripts\activate.bat    # Windows cmd
source venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
alembic upgrade head          # apply migrations
uvicorn app.main:app --reload # dev server (port 8000)
pytest                        # run all tests
pytest tests/path/test_foo.py::TestClass::test_name  # single test

# Dev tooling (pip install -r requirements-dev.txt)
python -m mypy app             # type-check (mypy not on PATH — always invoke via `python -m mypy`)
```

```bash
# Frontend (Vite + React SPA)
cd frontend
npm install
npm run dev        # dev server (port 5173)
npm run build      # type-check + production build
npm run type-check # TypeScript check only
npm run lint       # ESLint (flat config in eslint.config.js)
```

## Architecture

```
Vite + React SPA (frontend, port 5173 in dev)
  ├── Routes: /login  /auth/verify  /onboarding  /  /events/:id  /settings
  ├── State: React Query (@tanstack/react-query) for server state
  └── API client: frontend/src/api/client.ts (Authorization: Bearer session-token auth)
        ↓
FastAPI Backend (single process on Render free tier, port 8000 in dev)
  ├── Routers: /auth  /admin  /onboarding  /events  /feed  /feedback  /users/me  /webhooks
  └── APScheduler (embedded, kept alive by Render Cron Job ping /internal/tick every 15 min)
      ├── Weekly Sun 03:00: sync_fienta_organizers (auto-discover new organizers)
      ├── Hourly:   ingest_all_enabled
      ├── 6-hourly: dedup_pass + classify_pending
      ├── Daily 06:00: build_daily_feeds
      └── Daily 07:00: send_daily_digests (one hour after feeds are built)
        ↓
Neon Postgres (eu-central-1, free tier, pgvector available for v1.1)
        ↓
LLM Router: Groq (primary) → Cerebras → Mistral (fallback chain)
```

**No Celery/Redis** — embedded APScheduler suffices for a single-process MVP.

## Data Flow

1. **Ingestion** — 4 source types: Fienta API (~15 Tallinn organizer IDs), Piletilevi HTML scraper, Telliskivi/Kultuurikatel/Fotografiska/KUMU/Estonia Concert Hall JSON-LD, Resend Inbound email webhook (parsed via `app/llm/newsletter_extractor.py`). Eventbrite removed (API deprecated for non-partners).
2. **Deduplication** — Two-stage: rule-based pre-filter (SQL time-window self-join + Python fuzzy title/venue, `app/dedup/rules.py`), then LLM tiebreaker only on the surviving candidate pairs (keeps token usage low, `app/dedup/llm_tiebreaker.py`). The scheduled job (`jobs.dedup_pass`) runs `run_dedup_pass_llm`, which degrades to the rule-only `run_dedup_pass` when no LLM provider key is configured.
3. **Classification** — LLM assigns fixed 12-category / 10-vibe taxonomy, quality score 0–1, 3-bullet "why go?" text. Fixed taxonomy prevents ontology drift.
4. **Ranking** — `score = 0.45·persona_affinity + 0.20·recency_boost + 0.20·feedback_signal + 0.10·quality_score + 0.05·locality_bonus`
5. **Daily 5 builder** — runs 06:00 Europe/Tallinn; scores events in next 14 days; MMR-lite diversity (max 2 per category); writes to `daily_feeds`.

## Key Database Tables

- `users` — email (citext unique), locale (et|en|ru), home_city, session_token_version (int, bumped to revoke all sessions — see Auth)
- `auth_magic_links` — token_hash (sha256), expires_at, used_at; one-use only
- `personas` — 5 static personas with JSONB affinity vectors; display names in et/en/ru
- `user_personas` — M2M join with weight (1.0 primary, 0.4 secondary)
- `sources` — ingestion source registry
- `raw_events` — source payload as JSONB
- `event_sources` — M2M: links events to source + external_id; unique index on `(source_id, external_id)` enforces ingestion idempotency at the DB level (migration 0007)
- `events` — normalized: slug, title_orig, description_orig, starts_at/ends_at, venue, lat/lng, price, status (draft→classified→published|cancelled), dedup_group_id
- `event_classifications` — categories[], vibes[], quality_score, why_go_bullets[3], why_go_localized JSONB ({locale: [bullets]}), language_detected, model_used
- `user_event_feedback` — like/dislike/bookmark/view/click_external signals
- `user_event_scores` — cached ranking score per (user, event); unique constraint. Cache is invalidated by deleting **all** rows for a user whenever that user records any feedback signal — the indirect-feedback term means a signal on one event shifts scores on every co-categorical event, so per-row invalidation would leave neighbours stale (`routers/feedback.py`).
- `daily_feeds` — user_id, feed_date, event_ids BigInteger[]

## LLM Usage Constraints

- **Hard cap:** ≤600 tokens per LLM call to avoid quota exhaustion.
- **Dedup cache:** Cache decisions by content hash — never re-call LLM for identical pairs.
- **Fallback order:** Groq (primary, `llama-3.3-70b-versatile`) → Cerebras (`gpt-oss-120b`) → Mistral (`mistral-small-latest`, overnight batch, 1B tok/mo). Provider chain defined in `app/constants.py::LLM_PROVIDERS`.
- Groq's 30 req/min burst means no sleep loop needed in the classification batch job.

## i18n

**Single source of truth:** `shared/i18n/{en,et,ru}.json` — split into `"ui"` (frontend strings) and `"email"` (backend digest/magic-link strings). `shared/personas.json` holds persona names + vibes per locale. `shared/app-config.json` holds cross-stack scalars and taxonomies. `shared/calendar.json` holds localized `day_names`/`month_names` (generated into the backend's `DAY_NAMES`/`MONTH_NAMES`).

**Workflow:** Edit the JSON files in `shared/` → run `python scripts/generate_shared.py` → commit both the JSON and the updated `_generated` files. Never edit `_generated/` directly.

- **Frontend** — `frontend/src/i18n.ts` re-exports helpers (`t`, `ti`, `personaName`, `personaVibe`) and imports strings from `frontend/src/_generated/i18nData.ts`. `frontend/src/constants.ts` imports `LOCALES`, `PERSONAS`, TTL, and weight thresholds from `frontend/src/_generated/sharedConstants.ts`.
- **Backend** — `backend/app/i18n.py` re-exports helpers (`t`, `ti`, `day_name`, `month_name`) and imports `TRANSLATIONS`, `DAY_NAMES`, `MONTH_NAMES` from `backend/app/_generated/i18n_data.py`. `backend/app/constants.py` imports cross-stack scalars and frozensets from `backend/app/_generated/shared_constants.py`.
- **Email digest** — `backend/app/email/digest.py` handles data formatting + assembly and Resend delivery. CSS lives in `backend/app/email/styles.py` (`DIGEST_CSS`); HTML markup templates live in `backend/app/email/templates.py` (`DIGEST_DOCUMENT`, `EVENT_BLOCK`, `EVENT_TITLE_LINK`, `EVENT_BULLET`, `EVENT_PRICE`). All subjects, labels, and day/month names resolved via `app/i18n.py`. New email types must follow the same three-file split: presentation CSS in `styles.py`, markup in `templates.py`, assembly + delivery in a dedicated module.
- **Drift guard** — `backend/tests/test_generated_sync.py` runs the generator into a temp dir and asserts byte-identical output. If it fails: `python scripts/generate_shared.py` and commit.

## Frontend Structure

Each component and route lives in its own folder containing `Name.tsx`, `Name.module.css`, and a one-line `index.ts` barrel (`export { default } from './Name'`). The barrel keeps import strings short — callers write `./components/EventCard`, not `./components/EventCard/EventCard`.

- Routes (pages) in `frontend/src/routes/`: `Login/`, `AuthVerify/`, `Onboarding/`, `Feed/`, `EventDetail/`, `Settings/`, `NotFound/`.
- Shared components in `frontend/src/components/`: `EventCard/`, `PersonaCard/`, `ErrorBoundary/`, `PageState/`, `LocaleSelector/`, `FeedbackButtonRow/`, `EmptyState/`. `EventCard/index.ts` also re-exports `type EventData`.
- Shared CSS base classes in `frontend/src/components/shared/`: `Card.module.css` (`.card`, `.cardAccentTop`, `.cardDangerTop`, `.cardElevated`, `.cardPage`) and `Button.module.css` (`.btnPrimary`, `.btnOutline`). Compose from these via CSS Modules `composes` — never copy-paste the same card/button rules into route or component stylesheets. Component CSS composes from `'../shared/X.module.css'`; route CSS from `'../../components/shared/X.module.css'`.
- API client in `frontend/src/api/client.ts`. React Query used for server state (`@tanstack/react-query`).
- Custom hooks in `frontend/src/hooks/`: `useFeedback.ts` (feedback signal dispatch).
- Auth helpers in `frontend/src/lib/auth.ts` (token storage, `isAuthenticated()`).

## Auth

Magic-link email via `itsdangerous` tokens (no third-party auth). Token generation/verification lives in `app/auth/tokens.py`; magic-link delivery in `app/auth/email.py` (Resend, 3k/mo free tier). The signed session token is the credential — it is **not** stored server-side, so there is no per-token row to delete.

Session tokens are issued after magic-link verification and passed as an `Authorization: Bearer <token>` header (`frontend/src/api/client.ts`, `routers/auth.py::get_current_user`). TTL is 7 days (`SESSION_TTL_DAYS`); magic-link TTL is `MAGIC_LINK_TTL_MINUTES`. Both are settings in `app/config.py` defaulting to values in `shared/app-config.json`.

**Session revocation:** each session token embeds a `v` (version) claim equal to `users.session_token_version` at issue time; `get_current_user` rejects any token whose `v` no longer matches the stored value. `POST /auth/logout-all` increments that counter (atomic `UPDATE ... RETURNING`, mirroring the magic-link consume pattern), invalidating every previously issued token — including the one making the request. This is the only server-side state in the auth flow.

**Known residual risk — magic token in URL query string:** `/auth/verify?token=...` carries the one-time sign-in token in the URL (`AuthVerify.tsx`). URLs can leak via browser history, `Referer` headers, and proxy/server access logs. This is mitigated by the token being single-use (atomic `UPDATE ... WHERE used_at IS NULL ... RETURNING`, closes the TOCTOU race) and short-lived (`MAGIC_LINK_TTL_MINUTES`), so a leaked link has a narrow exploitation window. Moving verification to a POST body would close this gap entirely but adds friction to the email-link UX (the whole point of magic links is a single click) — left as a documented trade-off rather than changed.

## Admin Endpoints

`/admin/*` uses HTTP Basic auth (`ADMIN_PASSWORD` env var). In development with no password set, any credentials are accepted (logs a warning). In production, the env var is required — unset = 503.

List endpoints that can grow unbounded (e.g. `/admin/dedup/groups`) are paginated via `limit`/`offset` query params with caps in `app/constants.py` (`ADMIN_*_PAGE_SIZE`, `ADMIN_*_MAX_PAGE_SIZE`). Pagination is by logical unit (dedup group, not row) so a single noisy cluster cannot dominate a page. Add the same pattern to any new admin list endpoint.

## Security Hardening

The backend was hardened against the OWASP Top 10 (2021). The middleware stack and these invariants are wired in `app/main.py`:

- **Rate limiting** — `slowapi` per-IP limiter lives in `app/rate_limit.py` (its own module to avoid a circular import between `main.py` and routers). Public unauthenticated endpoints carry `@limiter.limit(...)` with the limit string sourced from a `RATE_LIMIT_*` constant in `app/constants.py` (`/auth/request-link`, `/auth/verify`, `/webhooks/inbound-mail` today). Add the same decorator + constant to any new public endpoint. `ProxyHeadersMiddleware(trusted_hosts="*")` is registered **last** (so it runs outermost) to rewrite `request.client` from `X-Forwarded-For` before the limiter reads it — without it, Render's proxy would collapse all clients into one bucket.
- **Security headers** — the `add_security_headers` middleware sets CSP/`X-Content-Type-Options`/`X-Frame-Options`/`Referrer-Policy` on every response from the `SECURITY_HEADERS` dict in `app/constants.py`; HSTS (`HSTS_HEADER_*`) is added only outside development (safe only over HTTPS). The CSP is `default-src 'none'` — the app is a pure JSON API with no first-party HTML/script surface.
- **API docs** — `/docs`, `/redoc`, and `/openapi.json` are enabled **only** in development (`APP_ENV == "development"`); the strict CSP would block their CDN assets in production anyway.
- **CORS** — `CORSMiddleware` with `allow_credentials=False` (auth is a Bearer header, never a cookie); origins from `settings.CORS_ORIGINS`, methods/headers from `CORS_ALLOWED_METHODS`/`CORS_ALLOWED_HEADERS` constants.
- **`/internal/tick`** — guarded by a constant-time `X-Internal-Token` check against `INTERNAL_TOKEN`; fail-closed outside development.
- **External-URL sanitization** — untrusted `url`/`image_url` from source adapters pass through `safe_external_url()` (`app/ingestion/base.py`), which drops any scheme not in `SAFE_URL_SCHEMES` (guards stored XSS via `javascript:`/`data:` URLs). `SourceAdapter.run()` already applies this when persisting events; apply it to any new field that renders an untrusted URL into an `href`/`src`.
- **Dependency CVE audit** — `.github/workflows/dependency-audit.yml` runs `pip-audit` on push/PR to `master` and weekly (Mon 04:00 UTC) to catch newly-disclosed CVEs in pinned deps.

## Logging

`app/logging_config.py::configure_logging()` is the single logging entry point. It is called at import time in `app/main.py` — deliberately *after* uvicorn configures its own logging, so it runs last and wins. It strips the framework loggers (`uvicorn`, `uvicorn.error`, `uvicorn.access`, `sqlalchemy.engine`) of their own handlers and re-points them at the root logger, so every line (app, uvicorn, SQL echo) shares one timestamped format. `configure_logging()` is idempotent (safe under `--reload` and in tests).

- **Development** — human-readable text to the console **and** a rotating file under `backend/logs/` (sizes/names in the `LOG_*` constants). SQL echo logs at INFO.
- **Production** (`APP_ENV != development`) — JSON-lines (`JsonLogFormatter`) to the console. SQL echo drops to WARNING. If `LOG_SHIP_URL` is set, logs are also shipped to an HTTP drain (e.g. Axiom) via a `QueueHandler` → background `QueueListener` thread so the request path never blocks; auth is `Bearer LOG_SHIP_TOKEN`.
- **Never crash the app** — log-shipping network failures are swallowed (`handleError`); `shutdown_log_shipping()` stops the listener thread on app shutdown (wired into the lifespan in `main.py`).
- All logging literals (formats, date format, file size/backup count, queue size, timeouts) live in `app/constants.py` (`LOG_*`); `LOG_LEVEL` / `LOG_SHIP_URL` / `LOG_SHIP_TOKEN` are settings in `app/config.py`.

## Code Quality & Best Practices

This project follows production best practices throughout:

- **Backend constants** — all literals (numbers, strings, thresholds, weights, sentinel values) live in `app/constants.py`. Cross-stack scalars (TTLs, locale set, weights, signals, category/vibe taxonomies) are sourced from `shared/app-config.json` and imported via `app._generated.shared_constants`. Never define a constant near business logic — always add it to `app/constants.py` (or `shared/` + regenerate) first, then import it. Never duplicate constants across files.
- **Backend utilities** — all shared helper functions live in `backend/app/routers/utils.py`. Before writing a new utility function anywhere in the backend, check this file first. If the function is reusable, add it here and import it — never duplicate helpers across routers or modules.
- **Frontend constants** — all magic values (numbers, strings, breakpoints, timeouts, limits) live in `frontend/src/constants.ts`. Cross-stack values (`LOCALES`, `PERSONAS`, `MAGIC_LINK_EXPIRY_MINUTES`, `PERSONA_PRIMARY_WEIGHT_THRESHOLD`) are sourced from `shared/` and imported via `frontend/src/_generated/sharedConstants.ts`. Apply the same discipline: never inline a literal near component logic — add it to `constants.ts` (or `shared/` + regenerate) first. Never duplicate constants across components.
- **Frontend utilities** — all shared helper functions live in `frontend/src/utils.ts`. Before writing a new utility function anywhere in the frontend, check this file first. If the function is reusable, add it here and import it — never duplicate helpers across components or pages.
- **CSS design tokens** — the following categories are fully tokenized in `:root` (`frontend/src/index.css`) and **must never be hardcoded** in component stylesheets: colors (`--color-*`, named semantic vars), border-radius (`--radius*`), shadows, z-indices, transitions (`--transition`), and animation easing (`--easing`). When any of these are needed, define the token in `:root` first, then reference it via `var(--token-name)`. **Spacing and raw font-sizes** do not yet have a `:root` scale — they may be inline `rem`/`px` values until a spacing/typography scale is added. Exception: font-sizes that exactly match an existing heading token (`--heading-xl/lg/md/sm/xs`) must use the token, not the raw value.
- **CSS shared base classes** — structural CSS patterns (card chrome, button styles) live in `frontend/src/components/shared/`. Use CSS Modules `composes: baseClass from '...'` to inherit shared rules — **never duplicate card or button CSS** across route or component stylesheets. Add new shared patterns to the shared files and compose from them.
- **Retry logic** — all HTTP calls use `http_get()` from `app/ingestion/base.py`, which wraps `httpx` with tenacity exponential-backoff retry (3 attempts, 2–30s backoff). Retryable: 429/502/503/504 and `RequestError`. Non-retryable: 4xx except 429.
- **Presentation layer separation** — never inline static CSS or HTML markup inside business-logic or delivery modules. Extract CSS into a dedicated `styles.py` and HTML markup into a dedicated `templates.py` sibling, then import the constants into the assembly module. The email package (`app/email/styles.py`, `app/email/templates.py`, `app/email/digest.py`) is the canonical example: CSS constants in `styles.py`, `.format()`-style markup constants in `templates.py`, data formatting + Resend delivery in `digest.py`. Apply the same three-file split to any future rendering feature (new email types, report generation, etc.). Do not introduce a templating engine (Jinja2, etc.) — plain Python string constants with `str.format()` are sufficient and keep dependencies minimal.
- **Encapsulation** — a leading underscore signals module-private; never import a `_name` from another production module. If a helper is imported cross-module, drop the underscore to make the API surface honest. Exceptions: `_is_retryable`, `_find`, `_venue_compatible`, `_make_slug` are intentionally private (used only within their defining module). Tests may import private names for white-box testing — that is an accepted pattern.
- **Error visibility** — HTTP failures in source adapters propagate to `SourceAdapter.run()` so `IngestionRun.error` and `source.last_status` are always set correctly. Never swallow exceptions in `fetch_raw()`.
- **Taxonomy** — LLM classification uses the fixed 12-category / 10-vibe frozensets in `app/llm/taxonomy.py`. Use `validate_categories()` / `validate_vibes()` before persisting any LLM output.
- **Migrations** — always chain migrations correctly (`down_revision = "PREV"`). Keep migrations small and reversible. If a new unique index could collide with pre-existing duplicate rows (e.g. `event_sources(source_id, external_id)` in `0007`), include a defensive `DELETE` keeping the smallest `id` per key **before** `create_index` — never assume application-level gating prevents historical dupes.
- **Batch jobs — bulk-load, no N+1** — periodic jobs (`build_daily_feeds`, `classify_pending`, `run_dedup_pass`, `send_daily_digests`) must use a fixed number of queries independent of row count. Bulk-fetch all per-user / per-event data with one `WHERE col IN (...)` query and group in Python; never `SELECT` inside a `for user in users:` loop. When extending these jobs, group fetches before the inner loop, mirroring the pattern already in `ranking/score.py::build_daily_feeds` and `llm/classifier.py::classify_pending`.
- **External-API fan-out — bounded concurrency** — when sending many independent outbound calls (e.g. Resend digest emails), use `asyncio.gather(..., return_exceptions=True)` wrapped with an `asyncio.Semaphore` whose limit lives in `app/constants.py` (see `DIGEST_SEND_CONCURRENCY`). Pick the cap from the upstream provider's documented rate limit, leaving headroom for retries. Never serial-await one call at a time, and never unbounded-gather without a semaphore.
- **Dedup self-join pre-filter** — the shared `candidate_pair_ids_in_window()` helper (`app/dedup/rules.py`) SQL-pre-filters candidate pairs via an aliased self-join on a sargable `BETWEEN` time window. Both dedup passes consume it: `run_dedup_pass` (rule-only) feeds the pairs to `cluster_events`, and `run_dedup_pass_llm` (rule + LLM) runs the Python fuzzy `is_candidate_pair` check then the LLM tiebreaker on them. The Python fuzzy step always runs only on the pre-filtered pairs. Preserve this split: don't push the time check into Python, and don't push the fuzzy check into SQL.
- **Quote style** — Backend Python uses **double quotes** (enforced by Ruff `Q` rules in `backend/ruff.toml`: `inline-quotes`, `multiline-quotes`, `docstring-quotes` all set to `double`). Frontend TypeScript uses **single quotes** for JS/TS string literals and **double quotes** for JSX attributes (enforced by ESLint `quotes: ['error', 'single', { avoidEscape: true, allowTemplateLiterals: true }]` + `'jsx-quotes': ['error', 'prefer-double']` in `frontend/eslint.config.js`). Template literals and strings containing the preferred quote character may use the alternate form (`avoidEscape`). Run `ruff check --fix` and `eslint --fix` before committing.
- **Python lint rules** — Ruff is configured in `backend/ruff.toml` with `select = ["E", "F", "W", "Q"]` (pycodestyle errors/warnings, Pyflakes, quotes), `line-length = 88`, `ignore = ["E501"]` (long lines allowed when wrapping would hurt readability). `python -m ruff check backend` must pass clean before commit. (`ruff` is not on PATH — always invoke via `python -m ruff`.)
- **Type checking** — `mypy` (`>=1.11`, `backend/requirements-dev.txt`) must pass clean: `python -m mypy app` from `backend/`. No mypy config file exists — defaults are sufficient. A loop/result variable reused across blocks with structurally incompatible types (e.g. different ORM models) will fail under mypy's inference even though each block is independently correct; give each block its own variable name. Third-party imports with no type stubs (e.g. `apscheduler`) get a targeted `# type: ignore[import-untyped]` on the import line rather than a blanket per-module ignore.
- **Type annotations** — Use modern PEP 604 / PEP 585 syntax: `X | None` not `Optional[X]`, `list[T]` / `dict[K, V]` / `tuple[T, ...]` not `List` / `Dict` / `Tuple`. Annotate return types on all public functions (including FastAPI route handlers — `-> dict`, `-> list[Schema]`, `-> None`). Import from `typing` only for things still required there (e.g. `Any`, `TypeVar`, `Protocol`).
- **Shared test fixtures** — Common pytest fixtures (`mock_db`, `make_user`, `make_event`) live in `backend/tests/conftest.py`. Use them instead of inlining `AsyncMock()` DB scaffolding or constructing user/event objects by hand in each test. When a new fixture would be reused across two or more test files, add it to `conftest.py`.
- **Numeric truthiness** — never gate a numeric field on truthiness; `0` is falsy, so `price_raw.get("min") or fallback` and `raw.get("price") or {}` silently drop legitimate zero prices (free events). Use explicit `is not None` checks and `isinstance(x, dict)` guards. Currency normalization goes through `normalize_currency(raw, has_price)` in `app/ingestion/base.py`.

## Conventions

- All datetimes are timezone-aware — no naive datetimes anywhere. User-visible timestamps and scheduling logic use `zoneinfo` (`Europe/Tallinn`) via `TALLINN_TZ`. Auth/token expiry arithmetic (`generate_magic_token`, session TTL, `_mark_processed`) may use `datetime.now(timezone.utc)` since DST-ambiguity is undesirable for TTL math.
- Email columns use `citext` (case-insensitive) to prevent duplicate accounts.
- Persona affinity vectors and source config stored as JSONB for easy extension without migrations.
- Feedback decay formula: `0.9^days_since_feedback` — recent signals weighted higher, dislike is a hard exclude.
- Public event endpoints (`/events/{id}`) return only `status == published` events and never expose internal metadata (`dedup_group_id`, draft/cancelled rows). Filter at the query level (`routers/events.py`), not in the serializer.

## MVP Scope (do not cut)

All MVP scope implemented: dedup, LLM classification, persona-based personalization, magic-link auth, Daily 5 builder, email digest, bookmarks, i18n (et/en/ru), Settings page.
